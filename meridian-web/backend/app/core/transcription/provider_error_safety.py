"""Safe provider error logging (Этап 20).

Превращает provider HTTP-ошибку в безопасную сводку БЕЗ raw response body / API keys / headers.
По умолчанию body-preview выключен; включается только явным config-флагом и всё равно редактирует
секреты и обрезает. Никогда не возвращает raw transcript/audio/ключи/Authorization.
"""

import hashlib
import re
from typing import Any, Optional

# Паттерны секретов/заголовков для редакции (если preview включён).
_SECRET_PATTERNS = [
    # bearer ПЕРВЫМ: иначе header-паттерн съест «Bearer» и оставит токен (он за пробелом)
    (re.compile(r"(?i)\bbearer\s+[^\"',}\s]+"), "Bearer [REDACTED]"),
    (re.compile(r"\bsk[_-][A-Za-z0-9_-]{4,}"), "[REDACTED_KEY]"),  # sk_live_..., sk-..., с underscores
    # header «name [": ] <value>» — поддержка quoted (JSON) и unquoted значений; value до кавычки/
    # запятой/скобки/пробела (char-class bounded → не перепрыгивает разделители, как старый \S+)
    (re.compile(r"(?i)\b(authorization|xi-api-key|x-api-key|api[-_]?key)\b[\"']?\s*[:=]\s*[\"']?[^\"',}\s]+"),
     r"\1: [REDACTED]"),
    # длинные токены без зависимости от \b (ловим и после '(' / без разделителя слева)
    (re.compile(r"(?<![A-Za-z0-9_\-])[A-Za-z0-9_\-]{40,}"), "[REDACTED_TOKEN]"),
]

_MAX_CONTENT_TYPE = 80


def _redact_all(text: str) -> str:
    """Применить все паттерны редакции секретов к строке (без обрезки)."""
    t = str(text)
    for pat, repl in _SECRET_PATTERNS:
        t = pat.sub(repl, t)
    return t


def redact_provider_error_text(text: Optional[str], max_chars: int = 0) -> Optional[str]:
    """Редактированный (без секретов) обрезанный preview. None, если preview не запрошен (max_chars<=0)."""
    if not text or max_chars is None or int(max_chars) <= 0:
        return None
    return _redact_all(text)[:int(max_chars)]


def _maybe_preview(body: str) -> Optional[str]:
    """Body preview только если включено в config (default false) и max_chars>0. Секреты редактируются."""
    try:
        from ...config import get_settings
        s = get_settings()
        enabled = bool(getattr(s, "transcription_provider_error_body_preview_enabled", False))
        max_chars = int(getattr(s, "transcription_provider_error_body_preview_max_chars", 0))
    except Exception:  # noqa: BLE001 — отсутствие config не должно ломать логирование
        return None
    if not enabled:
        return None
    return redact_provider_error_text(body, max_chars)


def safe_provider_error_summary(exc: Any, *, provider: str = "unknown") -> dict:
    """Безопасная сводка provider-ошибки. Без raw body / ключей / Authorization / headers (кроме
    content-type). Только provider/error_type/status_code/body_chars/body_hash/content_type."""
    out = {
        "provider": str(provider)[:40] if provider else "unknown",
        "error_type": type(exc).__name__,
        "status_code": None,
        "response_body_chars": None,
        "response_body_hash": None,
        "content_type": None,
    }
    resp = getattr(exc, "response", None)
    if resp is None:
        return out
    out["status_code"] = getattr(resp, "status_code", None)
    headers = getattr(resp, "headers", None)
    if headers is not None:
        try:
            ct = headers.get("content-type") or headers.get("Content-Type")
            if ct:
                # content-type тоже редактируем: враждебный сервер мог вписать туда ключ
                out["content_type"] = _redact_all(str(ct))[:_MAX_CONTENT_TYPE]
        except Exception:  # noqa: BLE001
            pass
    body = None
    try:
        body = resp.text
    except Exception:  # noqa: BLE001
        body = None
    if body:
        out["response_body_chars"] = len(body)
        out["response_body_hash"] = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()[:16]
        preview = _maybe_preview(body)
        if preview is not None:
            out["response_body_preview"] = preview
    return out
