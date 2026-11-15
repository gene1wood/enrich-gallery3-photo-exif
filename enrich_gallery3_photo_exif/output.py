"""Small helpers for printing coloured output."""

import click


def error(message: str) -> None:
    """
    Print an error message in red to STDERR.

    :param message: The message
    :type message: str
    """
    click.secho(message, fg="red", err=True)


def echo_option(key: str, text: str, default: str | None) -> None:
    """
    Print a menu option, highlighting it if it is the default.

    :param key: The option's key
    :type key: str
    :param text: The option's description
    :type text: str
    :param default: The default option's key
    :type default: str | None
    """
    is_default = key == default
    click.secho(
        f"{key} {text}" + ("  (default)" if is_default else ""),
        fg="green" if is_default else None,
        bold=is_default,
    )
