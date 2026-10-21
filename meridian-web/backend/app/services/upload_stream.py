"""Потоковое сохранение multipart-загрузки на диск с лимитом размера."""

import os
from pathlib import Path

from fastapi import UploadFile

CHUNK_SIZE = 1024 * 1024  # 1 MiB


class UploadTooLargeError(Exception):
    """Загрузка превысила допустимый размер; частичный файл уже удалён."""


async def save_upload_limited(file: UploadFile, dest: str | Path, max_bytes: int) -> int:
    """Пишет файл чанками по 1 MiB. При превышении max_bytes удаляет частичный файл
    и бросает UploadTooLargeError. Возвращает записанный размер."""
    total = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise UploadTooLargeError()
                out.write(chunk)
    except BaseException:
        if os.path.exists(dest):
            os.remove(dest)
        raise
    return total
