"""Безопасная работа с пользовательскими именами файлов."""

import os

from fastapi import HTTPException


def safe_filename(name: str) -> str:
    """Свести имя к базовому и отклонить path traversal (§).

    `../../etc/passwd` → отклоняется; обычное `смета.pdf` → возвращается как есть.
    Используется при сохранении/удалении загруженных файлов на диске.
    """
    base = os.path.basename(name or "")
    if base in ("", ".", "..") or "/" in base or "\\" in base or "\x00" in base:
        raise HTTPException(status_code=400, detail="Недопустимое имя файла")
    return base
