"""Каталог страниц и дефолты доступа по ролям (page-access).

Единый источник правды: какие страницы существуют, что всегда доступно
(защита от само-локаута) и какой набор у роли по умолчанию.

Сид Alembic-миграции 0015 дублирует эти дефолты литерально (миграция не должна
импортировать app-код). После старта авторитетен ЭТОТ модуль.
"""

# Порядок важен — в этом порядке рисуется матрица в админ-панели.
PAGE_CATALOG: list[dict[str, str]] = [
    {"key": "objects", "label": "Проекты"},
    {"key": "batch", "label": "Оффлайн распознавание"},
    {"key": "dir-objects", "label": "Справочники · Объекты"},
    {"key": "dir-departments", "label": "Справочники · Отделы"},
    {"key": "knowledge", "label": "База знаний"},
    {"key": "ai-settings", "label": "AI-профили"},
    {"key": "settings", "label": "Настройки / Админ-панель"},
]

PAGE_KEYS: list[str] = [p["key"] for p in PAGE_CATALOG]

# Всегда доступно всем ролям (нельзя выключить в матрице) — лендинг/фоллбэк.
ALWAYS_ALLOWED_ALL: set[str] = {"objects"}

# Доп. always-allowed по роли. admin не должен спрятать сам хаб настроек/матрицу.
ALWAYS_ALLOWED_BY_ROLE: dict[str, set[str]] = {"admin": {"settings"}}

# Дефолты — повторяют ТЕКУЩЕЕ поведение до миграции:
#   admin — всё; user — только Проекты + Оффлайн распознавание.
DEFAULT_ALLOWED: dict[str, list[str]] = {
    "admin": list(PAGE_KEYS),
    "user": ["objects", "batch"],
}


def always_allowed_for(role_name: str) -> set[str]:
    """Ключи, которые роль имеет всегда (независимо от строки конфига)."""
    return ALWAYS_ALLOWED_ALL | ALWAYS_ALLOWED_BY_ROLE.get(role_name, set())


def _sort_by_catalog(keys: set[str]) -> list[str]:
    return [k for k in PAGE_KEYS if k in keys]


def default_pages_for(role_name: str) -> list[str]:
    """Набор по умолчанию для роли (с учётом always-allowed), в порядке каталога."""
    base = set(DEFAULT_ALLOWED.get(role_name, ["objects"]))
    return _sort_by_catalog(base | always_allowed_for(role_name))


def normalize_allowed(role_name: str, keys) -> list[str]:
    """Очистить список ключей: выбросить неизвестные, до-добавить always-allowed."""
    valid = {k for k in keys if k in PAGE_KEYS}
    return _sort_by_catalog(valid | always_allowed_for(role_name))
