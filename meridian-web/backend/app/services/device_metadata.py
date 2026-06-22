"""Лёгкий парсер User-Agent → короткий ярлык устройства (напр. «iPhone · Safari»).

Назначение — только подпись устройства в шапке участников встречи (эфемерно, в памяти
комнаты). Сырой UA НЕ хранится и НЕ пишется в логи/БД (это фингерпринт-данные). Без внешних
зависимостей: грубая, но достаточная эвристика по подстрокам. Pure-функция, легко тестируется.
"""


def device_label_from_user_agent(ua: str | None) -> str | None:
    """Вернуть «<ОС/устройство> · <браузер>» или None, если UA пуст/не распознан."""
    if not ua or not isinstance(ua, str):
        return None
    s = ua.lower()

    # ОС / класс устройства
    if "iphone" in s:
        os_name = "iPhone"
    elif "ipad" in s:
        os_name = "iPad"
    elif "android" in s:
        os_name = "Android"
    elif "windows" in s:
        os_name = "Windows"
    elif "macintosh" in s or "mac os" in s:
        os_name = "Mac"
    elif "cros" in s:
        os_name = "ChromeOS"
    elif "linux" in s:
        os_name = "Linux"
    else:
        os_name = None

    # Браузер (порядок важен: спец-движки до Chrome; Chrome до Safari)
    if "yabrowser" in s:
        browser = "Yandex"
    elif "edg" in s:
        browser = "Edge"
    elif "opr" in s or "opera" in s:
        browser = "Opera"
    elif "firefox" in s or "fxios" in s:
        browser = "Firefox"
    elif "chrome" in s or "crios" in s:
        browser = "Chrome"
    elif "safari" in s:
        browser = "Safari"
    else:
        browser = None

    parts = [p for p in (os_name, browser) if p]
    return " · ".join(parts) if parts else None
