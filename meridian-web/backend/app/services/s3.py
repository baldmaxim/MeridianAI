"""S3-совместимое хранилище (§15): presigned upload/download, идемпотентное удаление.

Сетевые вызовы boto3 синхронные → оборачиваем в asyncio.to_thread.
Генерация presigned URL локальна (без сети). ContentType при presign НЕ задаём —
браузеру не нужно слать совпадающий заголовок (проще CORS, нет рассинхрона подписи).
"""

import asyncio
import os
import uuid
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from ..config import get_settings

_NOT_FOUND = {"404", "NoSuchKey", "NotFound"}


@lru_cache
def _client():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        region_name=s.s3_region,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        config=Config(signature_version="s3v4"),
    )


def object_key(user_id: int, purpose: str, filename: str) -> str:
    """Серверный ключ объекта (§15: не строится из пользовательского ввода)."""
    ext = os.path.splitext(filename or "")[1].lower()[:10]
    return f"meridian/{user_id}/{purpose}/{uuid.uuid4().hex}{ext}"


def presign_put(key: str, ttl: int | None = None) -> str:
    s = get_settings()
    return _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": s.s3_bucket, "Key": key},
        ExpiresIn=ttl or s.s3_presign_ttl,
    )


def presign_get(key: str, ttl: int | None = None, download_name: str | None = None) -> str:
    s = get_settings()
    params = {"Bucket": s.s3_bucket, "Key": key}
    if download_name:
        params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
    return _client().generate_presigned_url(
        "get_object", Params=params, ExpiresIn=ttl or s.s3_presign_ttl
    )


async def head_object(key: str) -> dict | None:
    """Метаданные объекта или None, если отсутствует."""
    s = get_settings()

    def _h():
        try:
            r = _client().head_object(Bucket=s.s3_bucket, Key=key)
            return {"size": r["ContentLength"], "content_type": r.get("ContentType")}
        except ClientError as e:
            if e.response["Error"]["Code"] in _NOT_FOUND:
                return None
            raise

    return await asyncio.to_thread(_h)


async def download_to(key: str, dest_path: str) -> None:
    s = get_settings()
    await asyncio.to_thread(_client().download_file, s.s3_bucket, key, dest_path)


async def put_bytes(key: str, data: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
    """Серверная загрузка байтов в S3 (например, извлечённый текст документа)."""
    s = get_settings()

    def _p():
        _client().put_object(Bucket=s.s3_bucket, Key=key, Body=data, ContentType=content_type)

    await asyncio.to_thread(_p)


async def ping() -> tuple[bool, str]:
    """Лёгкая проверка связности S3 (head_bucket). Не раскрывает секретов."""
    s = get_settings()
    if not s.s3_enabled:
        return False, "not configured"

    def _h():
        try:
            _client().head_bucket(Bucket=s.s3_bucket)
            return True, "ok"
        except ClientError as e:
            return False, str(e.response.get("Error", {}).get("Code", "error"))
        except Exception as e:  # сетевые/конфиг ошибки — без деталей с секретами
            return False, type(e).__name__

    return await asyncio.to_thread(_h)


async def delete_object(key: str) -> None:
    """Идемпотентно (§15): удаление отсутствующего объекта = успех."""
    s = get_settings()

    def _d():
        try:
            _client().delete_object(Bucket=s.s3_bucket, Key=key)
        except ClientError as e:
            if e.response["Error"]["Code"] in _NOT_FOUND:
                return
            raise

    await asyncio.to_thread(_d)
