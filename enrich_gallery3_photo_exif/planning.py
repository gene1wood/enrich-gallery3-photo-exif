"""Working out what should be written to each photo, without any I/O."""

from datetime import datetime, timedelta
from typing import Any

from .metadata import EXIF_DATE_FORMAT, IPTC_KEYWORD_BYTES

# How the overview colours a field: unchanged, newly added, or overwritten
STATE_COLORS = {"same": "green", "add": "cyan", "change": "yellow"}


DATE_SOURCES = {"1": "existing", "2": "last+5", "3": "Gallery3", "4": "album year"}


def description_choices(photo: dict[str, Any]) -> tuple[dict[str, str | None], str]:
    """
    List the description options for a photo and pick the default.

    :param photo: The photo being edited
    :type photo: dict
    :returns: The options keyed ``"1"`` to ``"4"`` and the default's key
    :rtype: tuple[dict, str]
    """
    choices = {
        "1": photo["exif_description"],
        "2": photo["description"],
        "3": photo["title"],
        "4": "",
    }

    if photo["exif_description"] is not None:
        default = "1"
    elif photo["description"] and not photo["title"]:
        default = "2"
    elif photo["title"]:
        default = "3"
    else:
        default = "4"
    return choices, default


def date_choices(
    photo: dict[str, Any], last_date: datetime | None, year_hint: datetime | None
) -> tuple[dict[str, str | None], str | None]:
    """
    List the capture date options for a photo and pick the default.

    :param photo: The photo being edited
    :type photo: dict
    :param last_date: The date of the previously edited photo, if any
    :type last_date: datetime | None
    :param year_hint: January 1st of the year in the album's path, if any
    :type year_hint: datetime | None
    :returns: The options keyed ``"1"`` to ``"4"`` (see :data:`DATE_SOURCES`)
        and the default's key, None if there are no options
    :rtype: tuple[dict, str | None]
    """

    def fmt(date: datetime | None) -> str | None:
        return date.strftime(EXIF_DATE_FORMAT) if date else None

    choices = {
        "1": photo["datetime_original"],
        "2": fmt(last_date + timedelta(minutes=5) if last_date else None),
        "3": fmt(photo.get("captured")),
        "4": fmt(year_hint),
    }
    # Prefer data about this photo over guesses from its neighbours
    default = next((key for key in ("1", "3", "2", "4") if choices[key]), None)
    return choices, default


def wanted_tags(album: dict[str, Any], photo: dict[str, Any]) -> dict[str, list[str]]:
    """
    Combine the album's tags with the photo's own Gallery3 tags.

    :param album: The album info from :func:`get_album_info`
    :type album: dict
    :param photo: The photo being edited
    :type photo: dict
    :returns: The tag lists to store, keyed like :data:`TAG_FIELDS`
    :rtype: dict
    """
    extra = photo.get("gallery_tags", [])
    wanted = {
        key: list(dict.fromkeys([*values, *extra]))
        for key, values in album["tags"].items()
    }
    if photo.get("format") == "jpeg":
        # IPTC limits each keyword, so cut long ones at a character boundary
        wanted["iptc_keywords"] = list(
            dict.fromkeys(
                keyword.encode()[:IPTC_KEYWORD_BYTES].decode(errors="ignore")
                for keyword in wanted["keywords"]
            )
        )
    return wanted


def pending_comments(photo: dict[str, Any]) -> list[str]:
    """
    List the Gallery3 comments not already stored in the file.

    :param photo: The photo being edited
    :type photo: dict
    :returns: The formatted comments
    :rtype: list[str]
    """
    existing = photo.get("exif_comment") or ""
    return [comment for comment in photo.get("comments", []) if comment not in existing]


def plan_photo(
    photo: dict[str, Any], last_date: datetime | None, year_hint: datetime | None
) -> dict[str, Any] | None:
    """
    Work out what the default choices would write for a photo.

    :param photo: The photo being planned
    :type photo: dict
    :param last_date: The date planned for the previous photo, if any
    :type last_date: datetime | None
    :param year_hint: January 1st of the year in the album's path, if any
    :type year_hint: datetime | None
    :returns: The ``description``, ``date`` and ``date_source``, or None if
        there's no date to default to
    :rtype: dict | None
    """
    dates, date_key = date_choices(photo, last_date, year_hint)
    if date_key is None:
        return None
    descriptions, description_key = description_choices(photo)
    return {
        "description": descriptions[description_key],
        "date": datetime.strptime(dates[date_key], EXIF_DATE_FORMAT),
        "date_source": DATE_SOURCES[date_key],
    }


def plan_is_noop(
    photo: dict[str, Any], plan: dict[str, Any], wanted: dict[str, list[str]]
) -> bool:
    """
    Tell whether writing a plan would change nothing in the file.

    :param photo: The photo being planned
    :type photo: dict
    :param plan: The plan from :func:`plan_photo`
    :type plan: dict
    :param wanted: The tags from :func:`wanted_tags`
    :type wanted: dict
    :returns: True if the file already has everything
    :rtype: bool
    """
    existing = photo.get("tags") or {}
    return (
        (plan["description"] or None) == photo["exif_description"]
        and plan["date"].strftime(EXIF_DATE_FORMAT) == photo["datetime_original"]
        and all(
            tag in existing.get(key, [])
            for key, values in wanted.items()
            for tag in values
        )
        and not pending_comments(photo)
    )


def diff_fields(
    photo: dict[str, Any], plan: dict[str, Any], wanted: dict[str, list[str]]
) -> list[tuple[str, str, str]]:
    """
    Compare a photo's metadata with what a plan would write.

    :param photo: The photo being planned
    :type photo: dict
    :param plan: The plan from :func:`plan_photo`
    :type plan: dict
    :param wanted: The tags from :func:`wanted_tags`
    :type wanted: dict
    :returns: A (field, state, text) tuple for the date, description, tags and
        comments. The state is ``same``, ``add`` (nothing there before) or
        ``change`` (an existing value is overwritten)
    :rtype: list[tuple[str, str, str]]
    """
    fields = []

    old, new = photo["datetime_original"], plan["date"].strftime(EXIF_DATE_FORMAT)
    source = f" ({plan['date_source']})"
    if old == new:
        fields.append(("date", "same", new))
    elif old is None:
        fields.append(("date", "add", new + source))
    else:
        fields.append(("date", "change", f"{old} → {new}{source}"))

    old, new = photo["exif_description"], plan["description"] or None
    if old == new:
        fields.append(("description", "same", f"'{old}'" if old else "(none)"))
    elif old is None:
        fields.append(("description", "add", f"'{new}'"))
    else:
        shown = f"'{new}'" if new else "(none)"
        fields.append(("description", "change", f"'{old}' → {shown}"))

    existing = photo.get("tags") or {}
    # The other lists hold the same tags in other forms, so name only these
    shown = [
        tag for tag in wanted["tags_list"] if tag not in existing.get("tags_list", [])
    ]
    complete = all(
        tag in existing.get(key, []) for key, values in wanted.items() for tag in values
    )
    # Existing tags are only at risk, and only asked about, if the file is written
    lost = (
        list(
            dict.fromkeys(
                tag
                for key, values in wanted.items()
                for tag in existing.get(key, [])
                if tag not in values
            )
        )
        if not plan_is_noop(photo, plan, wanted)
        else []
    )
    if lost:
        text = f"{', '.join(f'+{tag}' for tag in shown) or 'nothing new'}; will ask about existing: {', '.join(lost)}"
        fields.append(("tags", "change", text))
    elif not complete:
        text = ", ".join(f"+{tag}" for tag in shown) or "completing keyword fields"
        fields.append(("tags", "add", text))
    else:
        fields.append(("tags", "same", "all present"))

    pending = len(pending_comments(photo))
    if pending:
        fields.append(("comments", "add", f"{pending} to review (you approve each)"))
    else:
        fields.append(("comments", "same", "none new"))
    return fields
