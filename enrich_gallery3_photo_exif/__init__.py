"""
enrich_gallery3_photo_exif

Interactive utility for enriching EXIF metadata of photos stored in a
Gallery3 installation.

The script:
- Determines the Gallery3 album based on the current working directory
- Cross-references database entries with files on disk
- Allows interactive selection of the description and capture date
- Writes the description, capture date and album-derived tags back to the
  files using exiftool

Database credentials are loaded from a YAML configuration file located
in an XDG-compliant config directory.
"""

from .cli import main

__all__ = ["main"]
