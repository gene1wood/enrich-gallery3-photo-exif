"""Configuration file and logging setup."""

import logging
import sys
from pathlib import Path
from typing import Any

import platformdirs
import yaml

from .output import error

logger = logging.getLogger(__name__)


APP_NAME = "enrich-gallery3-photo-exif"


def get_config_path() -> Path:
    """
    Return the default path to the YAML configuration file.

    :returns: The config file path inside the user's XDG config directory
    :rtype: Path
    """
    return platformdirs.user_config_path(APP_NAME) / "config.yaml"


def load_config(config_path: Path) -> dict[str, Any]:
    """
    Load configuration from the YAML config file.

    Exits if the config file does not exist or is invalid.

    :param config_path: Path to the YAML config file
    :type config_path: Path
    :returns: The parsed configuration
    :rtype: dict
    """
    if not config_path.exists():
        error(f"Config file not found: {config_path}")
        sys.exit(1)

    if config_path.stat().st_mode & 0o077:
        logger.warning(
            "Config file %s contains a password but is accessible by other users",
            config_path,
        )

    try:
        with config_path.open("r") as fh:
            config = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        error(f"Failed to read config file: {exc}")
        sys.exit(1)

    if not isinstance(config, dict):
        error(f"Config file is empty or not a mapping: {config_path}")
        sys.exit(1)
    return config


def setup_logging(level: int | str, log_file: Path | None) -> None:
    """
    Configure logging to a file or STDOUT.

    :param level: The logging level
    :type level: int | str
    :param log_file: File to log to, or None to log to STDOUT
    :type log_file: Path | None
    """
    handler: logging.Handler = (
        logging.FileHandler(log_file) if log_file else logging.StreamHandler(sys.stdout)
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=level, handlers=[handler], force=True)
