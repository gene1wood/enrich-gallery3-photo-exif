# enrich-gallery3-photo-exif

A command-line tool that copies metadata out of a [Gallery3](https://github.com/gallery/gallery3) database and writes it into the photo and video files themselves. Gallery3 keeps descriptions, capture dates, tags and comments in MariaDB rather than in the files, so that information is lost when you move the files to another photo manager such as [Immich](https://immich.app/). This tool reads each album's data from the database and, after you confirm the changes, embeds it in the files' EXIF, IPTC and XMP metadata using exiftool. It supports JPEG and MP4 files.

# Usage

```
pip install enrich-gallery3-photo-exif
mkdir -p ~/.config/enrich-gallery3-photo-exif
cp config.example.yaml ~/.config/enrich-gallery3-photo-exif/config.yaml
chmod 600 ~/.config/enrich-gallery3-photo-exif/config.yaml
cd /path/to/gallery3/var/albums/1993/foo
enrich-gallery3-photo-exif
```

Run it from inside an album directory; the directory name is used as the album slug.

First it lists every photo with what the default choices would write, colour coded by field: green is unchanged, cyan is added where there was nothing before, yellow is overwritten or has existing tags you'll be asked about, and red needs your input. Each photo lists its changed fields and then what stays the same. Then it asks whether to apply them to all of them at once. Answer `y` to apply them, `n` to go through the photos one at a time, or `q` to quit. Photos which already have everything are marked "no change" and skipped, and photos with no date to default to are left for the one-at-a-time menu. Tag conflicts and comments are still confirmed individually either way.

In the one-at-a-time menu, pick a photo by number, then choose its description and capture date. Enter `0` to quit. Options: `-c/--config`, `-l/--log-file`, `-v/--verbose`.

The `mariadb` Python package requires the MariaDB Connector/C library (for example `libmariadb-dev` on Debian) to be installed.

# Supported formats

[exiftool](https://exiftool.org/) must be installed and on your `PATH`; it does all the reading and writing.

| Format | Description stored in | Date stored in |
| --- | --- | --- |
| JPEG | EXIF `ImageDescription` | EXIF `DateTimeOriginal` |
| MP4 | `Description` item | `CreateDate` in the `mvhd`, `tkhd` and `mdhd` headers |

Formats are detected from file content. Other files (PNG, GIF and so on) are skipped with a warning. MP4 dates have no timezone, so the time you enter is stored as if it were UTC. File modification and access times are preserved.

# Tags

Every file also gets tags so they show up as tags in Immich: tags derived from its album, plus its own Gallery3 tags (`items_tags` and `tags`). For an album at `1993/johnson-junior` titled "Johnson Junior High", with a photo tagged "Lego" in Gallery3:

| Tag | Value |
| --- | --- |
| `XMP-digiKam:TagsList` (read first by Immich) | `1993/johnson-junior`, `Johnson Junior High`, `Lego` |
| `XMP-lr:HierarchicalSubject` | `1993\|johnson-junior`, `Lego` |
| `XMP-dc:Subject` (keywords) | `1993`, `johnson-junior`, `Johnson Junior High`, `Lego` |
| `IPTC:Keywords` (JPEG only) | `1993`, `johnson-junior`, `Johnson Junior High`, `Lego` |

Writing replaces a list, so if a file already has tags that aren't in the wanted tags you're asked whether to overwrite them, merge them with the wanted tags, or keep them and skip the wanted tags. A `/` or `|` in a Gallery3 tag is replaced with `-`. IPTC limits each keyword to 64 bytes, so longer ones are cut at a character boundary there (the XMP lists are not limited). IPTC is the classic keyword field and is read by older photo software; MP4 has no IPTC, so videos get the XMP tags only.

# Comments

Published Gallery3 comments are offered one at a time, since some may be spam, and you approve each (the default is no). Approved comments are appended as `[YYYY-MM-DD Full Name (username)] text`, using `guest_name` for guests, to EXIF `UserComment` in JPEGs and the `Comment` item in MP4s. Immich doesn't display these. Comments already in the file are not asked about again, and ones you decline are asked about again next time.

# Date suggestions

When choosing the date you can pick the existing one, the previous photo plus 5 minutes, the date stored in Gallery3 (`captured`), or January 1st of the year at the start of the album path. The default is the first of existing, Gallery3, previous+5 and album year that is available.

# Development

The package is split by responsibility, from the bottom up: `output` (coloured printing), `config`, `db` (Gallery3 queries), `metadata` (everything that runs exiftool), `planning` (deciding what to write, with no I/O), `interactive` (prompts and screens) and `cli` (argument parsing and `main`). Run the tests with `pip install -e '.[dev]' && pytest`; they need `exiftool` and skip the file tests without it.
