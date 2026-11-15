"""The prompts and screens used to review and apply changes."""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from .metadata import EXIF_DATE_FORMAT, TAG_FIELDS, update_file
from .output import echo_option, error
from .planning import (
    STATE_COLORS,
    date_choices,
    description_choices,
    diff_fields,
    pending_comments,
    plan_is_noop,
    plan_photo,
    wanted_tags,
)

logger = logging.getLogger(__name__)


def prompt_description(photo: dict[str, Any]) -> str:
    """
    Ask the user what the EXIF description should be.

    :param photo: The photo being edited
    :type photo: dict
    :returns: The chosen description
    :rtype: str
    """
    choices, default = description_choices(photo)

    click.secho(photo["filename"], bold=True)
    echo_option("1", f"Existing: {photo['exif_description']}", default)
    echo_option("2", f"Descr   : {photo['description']}", default)
    echo_option("3", f"Title   : {photo['title']}", default)
    echo_option("4", "None", default)
    click.echo("Custom")

    while True:
        value = click.prompt(
            "What would you like the EXIF description to be",
            default=default,
        )
        if value not in choices:
            return value
        if choices[value] is not None:
            return choices[value]
        error(f"Option {value} is empty, choose another")


def prompt_datetime(
    photo: dict[str, Any],
    last_date: datetime | None,
    year_hint: datetime | None = None,
) -> datetime:
    """
    Ask the user what the capture date should be.

    :param photo: The photo being edited
    :type photo: dict
    :param last_date: The date of the previously edited photo, if any
    :type last_date: datetime | None
    :param year_hint: January 1st of the year in the album's path, if any
    :type year_hint: datetime | None
    :returns: The chosen date
    :rtype: datetime
    """
    choices, default = date_choices(photo, last_date, year_hint)

    echo_option("1", f"Existing : {choices['1']}", default)
    echo_option("2", f"Last+5   : {choices['2']}", default)
    echo_option("3", f"Gallery3 : {choices['3']}", default)
    echo_option("4", f"Album yr : {choices['4']}", default)
    click.echo("Custom")

    while True:
        value = click.prompt(
            "What would you like the capture date to be (YYYY:MM:DD HH:MM:SS)?",
            default=default,
        )
        value = choices.get(value, value)
        try:
            return datetime.strptime(value or "", EXIF_DATE_FORMAT)
        except ValueError:
            error(f"Invalid date, expected {EXIF_DATE_FORMAT}")


def resolve_tags(
    photo: dict[str, Any], wanted: dict[str, list[str]]
) -> dict[str, list[str]]:
    """
    Decide which tags to write, asking first if that would drop existing ones.

    Writing a tag list replaces it, so if the file already has tags which
    aren't in ``wanted`` the user chooses to overwrite them, merge them with
    the wanted tags, or keep the existing tags and write none.

    :param photo: The photo being edited
    :type photo: dict
    :param wanted: The album's tag lists, keyed like :data:`TAG_FIELDS`
    :type wanted: dict
    :returns: The tag lists to write, empty lists to leave the tags untouched
    :rtype: dict
    """
    existing = photo.get("tags") or {}
    lost = {
        key: [tag for tag in existing.get(key, []) if tag not in wanted[key]]
        for key in wanted
    }
    lost = {key: tags for key, tags in lost.items() if tags}
    if not lost:
        return wanted

    click.secho(f"{photo['filename']} has tags that would be replaced:", fg="yellow")
    for key, tags in lost.items():
        click.echo(f"  {TAG_FIELDS[key][2]}: {', '.join(tags)}")
    choice = click.prompt(
        "(o)verwrite them, (m)erge them with the album tags, or (k)eep them "
        "and skip the album tags",
        type=click.Choice(["o", "m", "k"]),
        default="m",
    )
    if choice == "o":
        return wanted
    if choice == "k":
        return {key: [] for key in wanted}
    return {
        key: [
            *existing.get(key, []),
            *(t for t in wanted[key] if t not in existing.get(key, [])),
        ]
        for key in wanted
    }


def approve_comments(photo: dict[str, Any]) -> str | None:
    """
    Ask the user to approve each new comment, as some may be spam.

    Approved comments are appended to the comment already in the file.

    :param photo: The photo being edited
    :type photo: dict
    :returns: The full comment to store, or None if nothing was approved
    :rtype: str | None
    """
    approved = []
    for comment in pending_comments(photo):
        click.secho(f"\n{photo['filename']} comment:", bold=True)
        click.secho(comment, fg="yellow")
        if click.confirm("Add this comment?", default=False):
            approved.append(comment)
    if not approved:
        return None
    return "\n\n".join(filter(None, [photo.get("exif_comment"), *approved]))


def save_photo(
    photo: dict[str, Any],
    description: str,
    date: datetime,
    last_date: datetime | None,
    album: dict[str, Any],
) -> datetime | None:
    """
    Resolve tags and comments with the user, then write a photo's metadata.

    :param photo: The photo being saved
    :type photo: dict
    :param description: The description to store
    :type description: str
    :param date: The capture date to store
    :type date: datetime
    :param last_date: The date of the previously saved photo, if any
    :type last_date: datetime | None
    :param album: The album info from :func:`get_album_info`
    :type album: dict
    :returns: ``date``, or ``last_date`` if saving failed
    :rtype: datetime | None
    """
    path = Path(photo["filename"])
    tags = resolve_tags(photo, wanted_tags(album, photo))
    comment = approve_comments(photo)

    try:
        logger.info("Writing metadata to %s", path)
        update_file(path, photo["format"], description, date, tags, comment)
    except Exception as exc:
        error(f"Failed to update {path}, file left unchanged: {exc}")
        logger.exception("Failed to update %s", path)
        return last_date

    click.secho(f"Updated {path}", fg="green")
    photo["exif_description"] = description or None
    photo["datetime_original"] = date.strftime(EXIF_DATE_FORMAT)
    for key, values in tags.items():
        if values:
            photo["tags"][key] = values
    if comment is not None:
        photo["exif_comment"] = comment
    return date


def edit_photo(
    photo: dict[str, Any], last_date: datetime | None, album: dict[str, Any]
) -> datetime | None:
    """
    Interactively edit and save the metadata of one photo or movie.

    :param photo: The photo being edited
    :type photo: dict
    :param last_date: The date of the previously edited photo, if any
    :type last_date: datetime | None
    :param album: The album info from :func:`get_album_info`
    :type album: dict
    :returns: The date applied to the photo, or ``last_date`` if saving failed
    :rtype: datetime | None
    """
    description = prompt_description(photo)
    date = prompt_datetime(photo, last_date, album["year_hint"])
    return save_photo(photo, description, date, last_date, album)


def show_overview(
    file_list: list[dict[str, Any]],
    plans: list[dict[str, Any] | None],
    album: dict[str, Any],
) -> None:
    """
    Print what the plans would change in every photo, colour coded by field.

    :param file_list: The photos from :func:`get_menu`
    :type file_list: list[dict]
    :param plans: The plan for each photo, None where there's no date to use
    :type plans: list[dict | None]
    :param album: The album info from :func:`get_album_info`
    :type album: dict
    """
    click.echo(
        "Legend: "
        + click.style("unchanged", fg="green")
        + ", "
        + click.style("added", fg="cyan")
        + ", "
        + click.style("overwritten", fg="yellow")
        + ", "
        + click.style("needs your input", fg="red")
    )
    for i, (photo, plan) in enumerate(zip(file_list, plans), start=1):
        head = f"{i:<3}{photo['filename']}"
        if plan is None:
            click.secho(f"{head}  needs your input: no date available", fg="red")
            continue
        fields = diff_fields(photo, plan, wanted_tags(album, photo))
        changed = [field for field in fields if field[1] != "same"]
        if not changed:
            click.secho(f"{head}  no change", fg="green")
            continue
        click.secho(head, bold=True)
        for name, state, text in changed:
            click.secho(f"     {name:<12}{text}", fg=STATE_COLORS[state])
        unchanged = [name for name, state, _ in fields if state == "same"]
        if unchanged:
            click.secho(f"     unchanged: {', '.join(unchanged)}", fg="green")


def bulk_phase(
    file_list: list[dict[str, Any]], album: dict[str, Any]
) -> datetime | None:
    """
    Show what the default choices would do to every photo, and offer to apply them.

    Tag conflicts and comments are still confirmed one at a time. Photos with
    no date to default to are left for the individual menu.

    :param file_list: The photos from :func:`get_menu`
    :type file_list: list[dict]
    :param album: The album info from :func:`get_album_info`
    :type album: dict
    :returns: The date of the last photo written, if any
    :rtype: datetime | None
    """
    last_date = None
    plans = []
    for photo in file_list:
        plan = plan_photo(photo, last_date, album["year_hint"])
        plans.append(plan)
        if plan:
            last_date = plan["date"]

    show_overview(file_list, plans, album)

    todo = [
        (photo, plan)
        for photo, plan in zip(file_list, plans)
        if plan and not plan_is_noop(photo, plan, wanted_tags(album, photo))
    ]
    if not todo:
        return None

    choice = click.prompt(
        f"Apply these to the {len(todo)} photos above? (y)es, (n)o and go "
        "through each photo, or (q)uit",
        type=click.Choice(["y", "n", "q"]),
    )
    if choice == "q":
        sys.exit(0)
    if choice == "n":
        return None

    last_date = None
    for photo, plan in todo:
        last_date = save_photo(
            photo, plan["description"], plan["date"], last_date, album
        )
    return last_date
