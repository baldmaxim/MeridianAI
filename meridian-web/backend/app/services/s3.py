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


def presign_put(key: str, ttl: int | None = None,
                sse: str | None = None, kms_key_id: str | None = None) -> str:
    """Presigned PUT. ContentType намеренно НЕ подписываем (проще CORS, нет рассинхрона).

    Этап 22: опциональный server-side encryption. sse/kms передаём в подпись ТОЛЬКО если заданы —
    тогда браузер обязан прислать совпадающие x-amz-server-side-encryption[-…] заголовки (см. CORS).
    """
    s = get_settings()
    params = {"Bucket": s.s3_bucket, "Key": key}
    if sse:
        params["ServerSideEncryption"] = sse
        if kms_key_id:
            params["SSEKMSKeyId"] = kms_key_id
    return _client().generate_presigned_url(
        "put_object", Params=params, ExpiresIn=ttl or s.s3_presign_ttl,
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


async def upload_file(local_path: str, key: str, content_type: str | None = None) -> None:
    """Серверная загрузка файла в S3 (Задача 3: архив сжатого аудио встречи).

    boto3 upload_file стримит с диска (не грузит файл в RAM целиком).
    """
    s = get_settings()
    extra = {"ContentType": content_type} if content_type else None

    def _u():
        _client().upload_file(local_path, s.s3_bucket, key, ExtraArgs=extra)

    await asyncio.to_thread(_u)


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


async def copy_object(src_key: str, dst_key: str) -> None:
    """Серверная копия объекта в том же бакете (без скачивания байтов на backend).

    Используется когда batch-задача берёт исходник из мини-облака (stash): копируем в
    собственный batch_audio-ключ, чтобы удаление задачи/файла было независимым.
    """
    s = get_settings()

    def _c():
        _client().copy_object(
            Bucket=s.s3_bucket, Key=dst_key,
            CopySource={"Bucket": s.s3_bucket, "Key": src_key},
        )

    await asyncio.to_thread(_c)


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
