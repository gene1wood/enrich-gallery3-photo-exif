"""Command line entry point."""

import argparse
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

import click
import mariadb

from .config import get_config_path, load_config, setup_logging
from .db import connect_to_db, get_album_info, get_db_content, pick_album
from .interactive import bulk_phase, edit_photo
from .metadata import detect_format, read_metadata_bulk
from .output import error

logger = logging.getLogger(__name__)


DESCRIPTION = (
    "Interactive utility for enriching the metadata of photos and movies "
    "stored in a Gallery3 installation."
)
IGNORED_FILES = {".htaccess"}


def get_menu(conn: mariadb.Connection, album_id: int) -> list[dict[str, Any]]:
    """
    Enrich database photo entries with EXIF data from the filesystem.

    Reports inconsistencies between the database and the filesystem and
    drops entries which can't be edited.

    :param conn: An open MariaDB connection
    :type conn: mariadb.Connection
    :param album_id: The Gallery3 album ID
    :type album_id: int
    :returns: The photos which can be edited
    :rtype: list[dict]
    """
    file_list = get_db_content(conn, album_id)

    fs_files = {p.name for p in Path.cwd().iterdir() if p.is_file()}
    db_files = {p["filename"] for p in file_list}

    missing_from_db = fs_files - db_files - IGNORED_FILES
    missing_from_fs = db_files - fs_files

    for message, names in (
        ("Files present in filesystem but missing from Gallery3", missing_from_db),
        ("Files present in Gallery3 but missing from filesystem", missing_from_fs),
    ):
        if names:
            click.secho(f"{message}: {', '.join(sorted(names))}", fg="yellow")
            if not click.confirm("Do you want to continue?"):
                sys.exit(0)

    candidates = []
    for photo in file_list:
        if photo["filename"] in missing_from_fs:
            continue
        fmt = detect_format(Path(photo["filename"]))
        if fmt is None:
            logger.warning("Skipping %s: unsupported file format", photo["filename"])
            continue
        photo["format"] = fmt
        candidates.append(photo)

    metadata = read_metadata_bulk([Path(photo["filename"]) for photo in candidates])
    menu = []
    for photo in candidates:
        found = metadata.get(Path(photo["filename"]).resolve())
        if found is None:
            logger.warning("Skipping %s: cannot read metadata", photo["filename"])
            continue
        (
            photo["exif_description"],
            photo["datetime_original"],
            photo["tags"],
            photo["exif_comment"],
        ) = found
        menu.append(photo)

    if not menu:
        error("No editable photos found")
        sys.exit(1)
    return menu


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse command line arguments.

    :param argv: Arguments to parse, defaulting to ``sys.argv``
    :type argv: list[str] | None
    :returns: The parsed arguments
    :rtype: argparse.Namespace
    """
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=get_config_path(),
        help="path to the YAML config file (default: %(default)s)",
    )
    parser.add_argument(
        "-l",
        "--log-file",
        type=Path,
        help="log to this file instead of STDOUT",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="log at DEBUG level",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """
    Main interactive loop for editing EXIF metadata.

    :param argv: Arguments to parse, defaulting to ``sys.argv``
    :type argv: list[str] | None
    """
    args = parse_args(argv)
    config = load_config(args.config)

    log_cfg = config.get("logging") or {}
    log_file = args.log_file or (
        Path(log_cfg["file"]).expanduser() if log_cfg.get("file") else None
    )
    level = (
        logging.DEBUG if args.verbose else str(log_cfg.get("level", "WARNING")).upper()
    )
    setup_logging(level, log_file)

    if not shutil.which("exiftool"):
        error("exiftool is required but was not found in PATH")
        sys.exit(1)

    conn = connect_to_db(config)
    try:
        album_id = pick_album(conn)
        album = get_album_info(conn, album_id)
        file_list = get_menu(conn, album_id)
    finally:
        conn.close()

    last_date = bulk_phase(file_list, album)
    next_photo_number = 1
    max_len = max(len(p["filename"]) for p in file_list)

    while True:
        for i, photo in enumerate(file_list, start=1):
            index = (
                click.style(f"{i:<2}", fg="green")
                if i == next_photo_number
                else f"{i:<2}"
            )
            click.echo(
                f"{index} {photo['filename']:<{max_len}} "
                f"'{photo['datetime_original']}' "
                f"D:'{photo['description']}' "
                f"T:'{photo['title']}' "
                f"ED:'{photo['exif_description']}'"
            )

        choice = click.prompt(
            "Enter number (0 to quit)",
            default=next_photo_number if next_photo_number <= len(file_list) else 0,
            type=click.IntRange(0, len(file_list)),
        )
        if choice == 0:
            break
        next_photo_number = choice + 1
        last_date = edit_photo(file_list[choice - 1], last_date, album)
