"""Reading photos, tags, comments and albums from the Gallery3 database."""

import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import click
import mariadb

from .output import error


def connect_to_db(config: dict[str, Any]) -> mariadb.Connection:
    """
    Establish a MariaDB connection using credentials from the config.

    :param config: The parsed configuration
    :type config: dict
    :returns: An open MariaDB connection
    :rtype: mariadb.Connection
    """
    db_cfg = config.get("database") or {}

    try:
        return mariadb.connect(
            user=db_cfg["user"],
            password=db_cfg["password"],
            host=db_cfg.get("host", "localhost"),
            port=db_cfg.get("port", 3306),
            database=db_cfg["database"],
        )
    except KeyError as exc:
        error(f"Missing database setting in config file: {exc}")
    except mariadb.Error as exc:
        error(f"Error connecting to MariaDB: {exc}")
    sys.exit(1)


def pick_album(conn: mariadb.Connection) -> int:
    """
    Determine the Gallery3 album corresponding to the current directory.

    The current directory name is treated as the album slug.

    :param conn: An open MariaDB connection
    :type conn: mariadb.Connection
    :returns: The selected album ID
    :rtype: int
    """
    slug = Path.cwd().name
    cur = conn.cursor()
    cur.execute(
        "SELECT id, relative_path_cache FROM items WHERE type='album' AND slug=?",
        (slug,),
    )
    albums = {str(album_id): path for album_id, path in cur}

    if not albums:
        error(f"No album found with slug '{slug}'")
        sys.exit(1)

    click.echo(f"Current working directory: {Path.cwd()}")
    for album_id, path in albums.items():
        click.echo(f"{album_id}:{path}")

    if len(albums) == 1:
        return int(next(iter(albums)))
    return int(click.prompt("Enter ID", type=click.Choice(list(albums))))


def clean_tag(value: str) -> str:
    """
    Make a string safe to use as one tag.

    A ``/`` or ``|`` would be read as a tag hierarchy separator.

    :param value: The raw tag
    :type value: str
    :returns: The tag with separators replaced by ``-``
    :rtype: str
    """
    return re.sub(r"[/|]", "-", value.strip())


def format_comment(
    created: int,
    guest_name: str | None,
    text: str,
    name: str | None,
    full_name: str | None,
    guest: int | None,
) -> str:
    """
    Format a Gallery3 comment for storing in a file.

    :param created: When the comment was made, in epoch seconds
    :type created: int
    :param guest_name: The name a guest gave
    :type guest_name: str | None
    :param text: The comment
    :type text: str
    :param name: The commenter's username, for registered users
    :type name: str | None
    :param full_name: The commenter's full name, for registered users
    :type full_name: str | None
    :param guest: Whether the commenter is the guest user
    :type guest: int | None
    :returns: ``[YYYY-MM-DD Full Name (username)] comment``
    :rtype: str
    """
    if guest or not (name or full_name):
        author = guest_name or "Guest"
    elif full_name and full_name != name:
        author = f"{full_name} ({name})" if name else full_name
    else:
        author = name or ""
    date = datetime.fromtimestamp(created).strftime("%Y-%m-%d")
    return f"[{date} {author}] {text.strip()}"


def get_db_content(conn: mariadb.Connection, album_id: int) -> list[dict[str, Any]]:
    """
    Fetch photo metadata from the Gallery3 database for a given album.

    Only photos and movies are returned, not sub-albums. Each also gets its
    Gallery3 tags and its published comments.

    :param conn: An open MariaDB connection
    :type conn: mariadb.Connection
    :param album_id: The Gallery3 album ID
    :type album_id: int
    :returns: Dicts containing filename, description, title, captured,
        gallery_tags and comments
    :rtype: list[dict]
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, description, title, captured FROM items "
        "WHERE parent_id=? AND type IN ('photo', 'movie') ORDER BY name",
        (album_id,),
    )
    rows = cur.fetchall()

    cur.execute(
        "SELECT it.item_id, t.name FROM items_tags it "
        "JOIN tags t ON t.id = it.tag_id JOIN items i ON i.id = it.item_id "
        "WHERE i.parent_id=? ORDER BY t.name",
        (album_id,),
    )
    gallery_tags = defaultdict(list)
    for item_id, tag in cur.fetchall():
        gallery_tags[item_id].append(clean_tag(tag))

    cur.execute(
        "SELECT c.item_id, c.created, c.guest_name, c.text, u.name, u.full_name, "
        "u.guest FROM comments c JOIN items i ON i.id = c.item_id "
        "LEFT JOIN users u ON u.id = c.author_id "
        "WHERE i.parent_id=? AND c.state='published' ORDER BY c.created, c.id",
        (album_id,),
    )
    comments = defaultdict(list)
    for item_id, *comment in cur.fetchall():
        comments[item_id].append(format_comment(*comment))

    file_list = []
    for item_id, filename, description, title, captured in rows:
        # If title is redundant with description, discard title
        if description and title and description.startswith(title):
            title = None

        file_list.append(
            {
                "filename": filename,
                "description": description,
                "title": title,
                "captured": datetime.fromtimestamp(captured) if captured else None,
                "gallery_tags": gallery_tags[item_id],
                "comments": comments[item_id],
            }
        )

    return file_list


def get_album_info(conn: mariadb.Connection, album_id: int) -> dict[str, Any]:
    """
    Derive the tags and a date hint for an album's contents.

    The album's path (``1993/valley-view``) becomes a hierarchical tag, and its
    title a plain one. A four digit first path component is taken as a year.

    :param conn: An open MariaDB connection
    :type conn: mariadb.Connection
    :param album_id: The Gallery3 album ID
    :type album_id: int
    :returns: A dict with ``tags`` (lists keyed ``tags_list``, ``hierarchical``
        and ``keywords``) and ``year_hint`` (a datetime or None)
    :rtype: dict
    """
    cur = conn.cursor()
    cur.execute("SELECT relative_path_cache, title FROM items WHERE id=?", (album_id,))
    path, title = cur.fetchone() or ("", "")
    parts = [part for part in (path or "").split("/") if part]
    title = clean_tag(title or "")

    tags_list = ["/".join(parts)] if parts else []
    if title and title not in tags_list:
        tags_list.append(title)
    keywords = list(dict.fromkeys([*parts, title] if title else parts))

    year_hint = None
    if parts and re.fullmatch(r"\d{4}", parts[0]):
        year_hint = datetime(int(parts[0]), 1, 1)

    return {
        "tags": {
            "tags_list": tags_list,
            "hierarchical": ["|".join(parts)] if parts else [],
            "keywords": keywords,
        },
        "year_hint": year_hint,
    }
