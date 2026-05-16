import logging
import sys
from pathlib import Path
from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

_theme = Theme(
    {
        "proxy": "cyan",
        "vpn": "green",
        "ai": "magenta",
        "plugin": "yellow",
        "mcp": "blue",
        "error": "bold red",
        "warn": "bold yellow",
    }
)

console = Console(theme=_theme)

_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = RichHandler(
            console=console,
            show_time=True,
            show_path=False,
            rich_tracebacks=True,
            markup=True,
        )
        handler.setLevel(level)
        logger.addHandler(handler)

    logger.propagate = False
    _loggers[name] = logger
    return logger
