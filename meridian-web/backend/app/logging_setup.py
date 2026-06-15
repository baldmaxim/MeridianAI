"""JSON-логирование с редакцией секретов и request_id (корп. стандарт §20).

Реализовано на stdlib logging (без structlog), чтобы все существующие
`logging.getLogger(...).info(...)` вызовы автоматически попадали в JSON
с редакцией — без переписывания кодовой базы.
"""

import json
import logging
import re
import sys
from contextvars import ContextVar

# request_id текущего запроса — выставляется middleware (см. main.py)
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Значения этих ключей (в extra/args) маскируем целиком
_SENSITIVE_KEYS = {
    "token", "access_token", "refresh_token", "authorization", "password",
    "secret", "client_secret", "cookie", "set-cookie", "api_key", "apikey",
    "encrypted_key", "jwt", "x-amz-signature",
}

# Скраб в свободном тексте: token=…, user:pass@, presigned-подписи S3
_PATTERNS = [
    (re.compile(r"(token=)[^&\s]+", re.I), r"\1***"),
    (re.compile(r"(://[^:/@\s]+:)[^@\s]+@"), r"\1***@"),
    (re.compile(r"(X-Amz-Signature=)[^&\s]+", re.I), r"\1***"),
    (re.compile(r"(X-Amz-Credential=)[^&\s]+", re.I), r"\1***"),
]

# Поля extra, которые выносим в JSON (структурный access-лог)
_EXTRA_FIELDS = ("method", "path", "status", "duration_ms", "event")


def _scrub(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


def redact_secrets(text: str) -> str:
    """Публичный хелпер: скрабит токены/пароли/presigned-подписи в произвольной строке."""
    return _scrub(text or "")


def truncate_for_log(value, max_chars: int = 500) -> str:
    """Обрезать значение для безопасного лога (после редакции секретов)."""
    s = redact_secrets(str(value if value is not None else ""))
    return s if len(s) <= max_chars else s[:max_chars] + "…"


def safe_log_value(value, max_chars: int = 500) -> str:
    """Алиас: редакция + обрезка. Для transcript/prompt/chunks/payload в логах."""
    return truncate_for_log(value, max_chars)


class RedactionFilter(logging.Filter):
    """Маскирует секреты в сообщении и строковых аргументах до форматирования."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: ("***" if str(k).lower() in _SENSITIVE_KEYS
                        else _scrub(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
            else:
                record.args = tuple(
                    _scrub(a) if isinstance(a, str) else a for a in record.args
                )
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Скраб финального сообщения ловит секреты в args любого типа
        # (например httpx логирует URL-объект, а не строку).
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "msg": _scrub(record.getMessage()),
        }
        for k in _EXTRA_FIELDS:
            if k in record.__dict__:
                v = record.__dict__[k]
                payload[k] = _scrub(v) if isinstance(v, str) else v
        if record.exc_info:
            payload["exc"] = _scrub(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(dev_mode: bool = False, level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    root.addHandler(handler)
    root.setLevel(level)

    # Шумные логгеры
    for noisy in ("sqlalchemy", "watchfiles", "aiosqlite"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # Дефолтный uvicorn access-лог отключаем: он пишет полный путь с ?token=.
    # Доступ логируем сами (редактированно) в RequestContextMiddleware.
    logging.getLogger("uvicorn.access").disabled = True
