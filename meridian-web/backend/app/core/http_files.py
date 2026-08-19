"""Заголовки скачивания файлов (RFC 6266/5987).

HTTP-заголовки кодируются latin-1, поэтому кириллица в `filename="..."` роняет
ответ (UnicodeEncodeError). Имя передаём через `filename*=UTF-8''...`,
а в `filename=` кладём ASCII-фолбэк для старых клиентов.
"""

import os
from urllib.parse import quote

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def safe_download_name(name: str) -> str:
    """Basename без управляющих символов, кавычек и разделителей пути."""
    base = os.path.basename((name or "").replace("\\", "/"))
    for ch in ('"', "\r", "\n", ";"):
        base = base.replace(ch, "")
    return base.strip()[:200] or "download"


def ascii_fallback(name: str) -> str:
    """ASCII-версия имени: транслит кириллицы, остальное — подчёркивания."""
    out = []
    for ch in name:
        low = ch.lower()
        if low in _TRANSLIT:
            t = _TRANSLIT[low]
            out.append(t.upper() if ch.isupper() and t else t)
        elif ch.isascii() and (ch.isalnum() or ch in "._- "):
            out.append(ch)
        else:
            out.append("_")
    name = "".join(out).strip()
    return name if name.strip("._") else "download"


def content_disposition(name: str, disposition: str = "attachment") -> str:
    """Значение Content-Disposition, безопасное для latin-1 заголовков."""
    safe = safe_download_name(name)
    return (
        f"{disposition}; filename=\"{ascii_fallback(safe)}\"; "
        f"filename*=UTF-8''{quote(safe, safe='')}"
    )
