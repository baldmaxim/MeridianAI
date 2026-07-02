"""Document storage abstraction (Этап 22) — тонкий безопасный слой поверх services/s3.

Не дублирует S3-клиент: переиспользует `services.s3` (креды/клиент только из env/AWS-chain,
никогда из БД/настроек встречи). Централизует то, что нужно для production-хардонинга presigned
загрузки документов:
- валидация расширения (авторитетно), размера, content-type (allow-list, мягкая);
- построение object key БЕЗ raw filename (uuid + extension);
- presigned PUT (+ опциональный SSE, если сконфигурирован; ContentType не подписываем — см. s3.py);
- HEAD-проверка на confirm (существование + размер + content-type);
- download в secure tempfile для парсера/RAG и его удаление;
- safe_storage_ref для логов (без bucket/key/URL/filename).

Ничего не логирует: сырой текст, имя файла, presigned URL, bucket/key. Backend != s3 → отдаёт
`is_enabled()==False`, вызывающий уходит на legacy multipart.
"""

import hashlib
import os
import shutil
import tempfile

from ..config import get_settings
from . import s3

# content-type, которые считаем «неизвестными» → доверяем расширению (не отклоняем).
_GENERIC_CONTENT_TYPES = {"", "application/octet-stream", "binary/octet-stream", "application/x-download"}


class DocumentStorageError(Exception):
    """Безопасная ошибка валидации/хранилища (сообщение без секретов/PII)."""


def is_enabled() -> bool:
    """Presigned-S3 путь активен (S3 сконфигурирован И kill-switch включён)."""
    return get_settings().document_s3_upload_active


def storage_backend() -> str:
    return "s3" if is_enabled() else "local"


def allowed_content_types() -> set[str]:
    return get_settings().document_s3_allowed_content_types_set


def max_upload_bytes() -> int:
    return int(get_settings().document_s3_max_upload_bytes)


def presign_expires() -> int:
    return int(get_settings().document_s3_presign_expires_seconds or get_settings().s3_presign_ttl)


def extension_of(filename: str | None) -> str:
    return os.path.splitext(filename or "")[1].lower()


def _reject_path_traversal(filename: str | None) -> None:
    name = filename or ""
    if not name or "\x00" in name or "/" in name or "\\" in name:
        raise DocumentStorageError("Недопустимое имя файла")


def validate_upload(filename: str | None, content_type: str | None, size_bytes: int | None) -> str:
    """Провалидировать заявку на загрузку. Возвращает нормализованное расширение или бросает
    DocumentStorageError с безопасным сообщением. Расширение — авторитетная проверка; content-type —
    мягкая (пустой/октет-стрим → доверяем расширению)."""
    _reject_path_traversal(filename)
    s = get_settings()
    ext = extension_of(filename)
    if ext not in s.document_allowed_extensions_set:
        allowed = ", ".join(sorted(s.document_allowed_extensions_set))
        raise DocumentStorageError(f"Формат {ext or '?'} не поддерживается. Допустимые: {allowed}")
    if size_bytes is not None:
        if int(size_bytes) < 0:
            raise DocumentStorageError("Некорректный размер файла")
        if int(size_bytes) > max_upload_bytes():
            mb = max_upload_bytes() // (1024 * 1024)
            raise DocumentStorageError(f"Файл слишком большой (макс. {mb} МБ)")
    ct = (content_type or "").strip().lower()
    if ct and ct not in _GENERIC_CONTENT_TYPES and ct not in allowed_content_types():
        raise DocumentStorageError("Тип содержимого не разрешён")
    return ext


def build_object_key(user_id: int, filename: str | None) -> str:
    """S3 object key: `documents/{uuid}{ext}` под общим префиксом — БЕЗ raw filename (только uuid+ext)."""
    return s3.object_key(user_id, get_settings().document_s3_prefix_effective, filename or "document")


def create_presigned_put(key: str, content_type: str | None = None) -> tuple[str, dict]:
    """Presigned PUT URL + заголовки, которые браузер обязан прислать. По умолчанию SSE нет →
    заголовки пустые/только advisory Content-Type. При настроенном SSE — x-amz-* заголовки."""
    s = get_settings()
    sse = (s.document_s3_sse or "").strip()
    kms = (s.document_s3_kms_key_id or "").strip()
    headers: dict[str, str] = {}
    if sse:
        url = s3.presign_put(key, ttl=presign_expires(), sse=sse, kms_key_id=(kms or None))
        headers["x-amz-server-side-encryption"] = sse
        if kms:
            headers["x-amz-server-side-encryption-aws-kms-key-id"] = kms
    else:
        url = s3.presign_put(key, ttl=presign_expires())
    ct = (content_type or "").strip()
    if ct:
        headers["Content-Type"] = ct  # не подписан → advisory; браузер шлёт как есть
    return url, headers


async def head_object(key: str) -> dict | None:
    return await s3.head_object(key)


def validate_head(meta: dict | None) -> dict:
    """Проверить метаданные после загрузки (существование, размер ≥0 и ≤ лимита, content-type)."""
    if not meta:
        raise DocumentStorageError("Объект не загружен в хранилище")
    size = meta.get("size")
    if size is not None:
        if int(size) < 0:
            raise DocumentStorageError("Некорректный размер загруженного файла")
        if int(size) > max_upload_bytes():
            raise DocumentStorageError("Загруженный файл превышает лимит размера")
    ct = (meta.get("content_type") or "").strip().lower()
    if ct and ct not in _GENERIC_CONTENT_TYPES and ct not in allowed_content_types():
        raise DocumentStorageError("Тип содержимого загруженного файла не разрешён")
    return meta


async def download_to_tempfile(key: str, ext: str = "") -> str:
    """Скачать объект в secure temp-файл; вернуть путь. Директорию удаляет cleanup_tempfile.

    При ошибке скачивания сами убираем tmpdir (иначе он утёк бы: путь наружу не вернулся)."""
    tmpdir = tempfile.mkdtemp(prefix="meridian_docstore_")
    local = os.path.join(tmpdir, "src" + (ext or ""))
    try:
        await s3.download_to(key, local)
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    return local


def cleanup_tempfile(path: str | None) -> None:
    """Удалить temp-файл вместе с его временной директорией (best-effort, идемпотентно)."""
    if not path:
        return
    shutil.rmtree(os.path.dirname(path), ignore_errors=True)


async def delete_object(key: str) -> None:
    await s3.delete_object(key)


def safe_storage_ref(key: str | None) -> str:
    """Безопасная для логов ссылка на объект: хэш ключа + расширение. Без bucket/key/filename/URL."""
    if not key:
        return "none"
    ext = os.path.splitext(key)[1].lower()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    return f"s3:{digest}{ext}"
