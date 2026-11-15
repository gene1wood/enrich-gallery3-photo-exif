"""Reading and writing photo and movie metadata with exiftool."""

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


EXIF_DATE_FORMAT = "%Y:%m:%d %H:%M:%S"


# Tags Immich reads, in the order it prefers them
READ_TAGS = [
    "-ImageDescription",
    "-Description",
    "-DateTimeOriginal",
    "-CreationDate",
    "-CreateDate",
    "-TagsList",
    "-HierarchicalSubject",
    "-Subject",
    "-IPTC:Keywords",
    "-UserComment",
    "-ItemList:Comment",
]


# For each tag list: the tag to write, the name exiftool reports it under, and
# what to call it when asking the user
TAG_FIELDS = {
    "tags_list": ("XMP-digiKam:TagsList", "TagsList", "TagsList"),
    "hierarchical": (
        "XMP-lr:HierarchicalSubject",
        "HierarchicalSubject",
        "HierarchicalSubject",
    ),
    "keywords": ("XMP-dc:Subject", "Subject", "Keywords"),
    # IPTC is the classic keyword field in JPEGs, which older software reads
    "iptc_keywords": ("IPTC:Keywords", "Keywords", "IPTC Keywords"),
}


IPTC_KEYWORD_BYTES = 64


def detect_format(path: Path) -> str | None:
    """
    Identify a file's metadata format from its content, not its extension.

    :param path: The file to inspect
    :type path: Path
    :returns: ``"jpeg"``, ``"mp4"`` or None if the format isn't supported
    :rtype: str | None
    """
    with path.open("rb") as fh:
        header = fh.read(12)
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header[4:8] == b"ftyp":
        return "mp4"
    return None


def as_list(value: Any) -> list[str]:
    """
    Normalize an exiftool JSON value, which is bare when there is one item.

    :param value: A missing value, a scalar or a list
    :returns: The items as strings
    :rtype: list[str]
    """
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def read_metadata_bulk(
    paths: list[Path],
) -> dict[Path, tuple[str | None, str | None, dict[str, list[str]], str]]:
    """
    Read the description and capture date of many files with one exiftool run.

    The date is the first valid one of ``DateTimeOriginal``, ``CreationDate``
    and ``CreateDate``, the order Immich prefers.

    :param paths: The files to read
    :type paths: list[Path]
    :returns: The description, the date as ``YYYY:MM:DD HH:MM:SS`` and the
        existing tag lists (keyed like :data:`TAG_FIELDS`) and the existing comment,
        keyed by resolved path. Files exiftool can't read are absent
    :rtype: dict
    """
    if not paths:
        return {}
    result = subprocess.run(
        ["exiftool", "-j", "-d", EXIF_DATE_FORMAT, *READ_TAGS, "-@", "-"],
        input="\n".join(str(path.resolve()) for path in paths),
        capture_output=True,
        text=True,
        check=False,
    )
    if not result.stdout.strip():
        raise RuntimeError(f"exiftool failed: {result.stderr.strip()}")

    found = {}
    for record in json.loads(result.stdout):
        date = None
        for key in ("DateTimeOriginal", "CreationDate", "CreateDate"):
            try:
                datetime.strptime(str(record.get(key)), EXIF_DATE_FORMAT)
            except ValueError:
                continue  # missing, or zeroed as in a never-dated MP4
            date = str(record[key])
            break
        description = record.get("ImageDescription") or record.get("Description")
        tags = {
            key: as_list(record.get(name)) for key, (_, name, _) in TAG_FIELDS.items()
        }
        found[Path(record["SourceFile"])] = (
            str(description) if description else None,
            date,
            tags,
            str(record.get("UserComment") or record.get("Comment") or ""),
        )
    return found


def build_exiftool_args(
    fmt: str,
    description: str,
    date: datetime,
    tags: dict[str, list[str]],
    comment: str | None = None,
) -> list[str]:
    """
    Build the exiftool assignments for one file.

    JPEGs get EXIF ``ImageDescription`` and ``DateTimeOriginal``. MP4s get the
    ``Description`` item and the creation time of the movie, track and media
    headers. Both get the tags as XMP, and JPEGs also as IPTC keywords. Tag lists are assigned by repeating
    ``-TAG=value``, which replaces the list and so is safe to repeat.

    :param fmt: The format returned by :func:`detect_format`
    :type fmt: str
    :param description: The description to store, empty to clear it
    :type description: str
    :param date: The capture date to store
    :type date: datetime
    :param tags: Values keyed like :data:`TAG_FIELDS`. ``iptc_keywords`` is
        only valid for JPEGs
    :type tags: dict
    :param comment: The comment to store, or None to leave it alone
    :type comment: str | None
    :returns: The exiftool arguments
    :rtype: list[str]
    """
    stamp = date.strftime(EXIF_DATE_FORMAT)
    if fmt == "jpeg":
        args = [f"-ImageDescription={description}", f"-DateTimeOriginal={stamp}"]
    else:
        # MP4 dates carry no timezone, so exiftool stores the value as UTC
        args = [
            f"-ItemList:Description={description}",
            f"-CreateDate={stamp}",
            f"-TrackCreateDate={stamp}",
            f"-MediaCreateDate={stamp}",
        ]
    for key, (tag, _, _) in TAG_FIELDS.items():
        args += [f"-{tag}={value}" for value in tags.get(key, [])]
    if tags.get("iptc_keywords"):
        args.append("-IPTC:CodedCharacterSet=UTF8")
    if comment is not None:
        args.append(
            f"-{'UserComment' if fmt == 'jpeg' else 'ItemList:Comment'}={comment}"
        )
    return args


def update_file(
    path: Path,
    fmt: str,
    description: str,
    date: datetime,
    tags: dict[str, list[str]],
    comment: str | None = None,
) -> None:
    """
    Update a file's metadata without risking the original or its mtime.

    exiftool writes the edited copy to a temporary file which then atomically
    replaces the original, so a failure never truncates it. The original's
    permissions and access and modification times are carried over.

    :param path: The file to update
    :type path: Path
    :param fmt: The format returned by :func:`detect_format`
    :type fmt: str
    :param description: The description to store
    :type description: str
    :param date: The capture date to store
    :type date: datetime
    :param tags: Values keyed ``tags_list``, ``hierarchical`` and ``keywords``
    :type tags: dict
    :param comment: The comment to store, or None to leave it alone
    :type comment: str | None
    """
    stat = path.stat()
    tmp = path.with_name(f".tmp-{path.name}")
    try:
        result = subprocess.run(
            [
                "exiftool",
                "-charset",
                "filename=UTF8",
                "-charset",
                "exif=UTF8",
                "-charset",
                "quicktime=UTF8",
                "-charset",
                "iptc=UTF8",
                *build_exiftool_args(fmt, description, date, tags, comment),
                "-o",
                str(tmp),
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not tmp.exists():
            raise RuntimeError(f"exiftool failed: {result.stderr.strip()}")
        if result.stderr.strip():
            logger.warning("exiftool on %s: %s", path, result.stderr.strip())
        shutil.copymode(path, tmp)
        os.utime(tmp, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
