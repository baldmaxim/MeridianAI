"""Журнал агента.

Агент запускается заданием планировщика через pythonw.exe — без консоли, sys.stderr там None.
Поэтому журнал — файл рядом с настройками, а консоль добавляется, только если она есть.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from meridian_ocr_agent.config import config_path

FORMAT = "%(asctime)s %(levelname)s %(message)s"


def setup(*, verbose: bool = False) -> Path:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")  # консоль Windows по умолчанию cp866

    directory = config_path().parent / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "agent.log"

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter(FORMAT, datefmt="%d.%m %H:%M:%S")

    file_handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        root.addHandler(console)
    # httpx пишет строку на каждый запрос — в журнале агента это шум.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return path
