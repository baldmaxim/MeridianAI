"""Настройки агента распознавания.

Файл лежит рядом с агентом (его кладёт установщик), иначе — в профиле пользователя.
Токен задаётся в Meridian: Админка → «Распознавание сканов» → «Подключить компьютер».
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = "meridian-ocr-agent.json"

DEFAULT_CONFIG: dict = {
    "server_url": "https://meridianai.ru",
    "token": "",
    "lmstudio_base_url": "http://127.0.0.1:1234/v1",
    # Пусто, если LM Studio без ключа доступа (по умолчанию так).
    "lmstudio_api_key": "",
    "model": "chandra-ocr-2",
    # 200 DPI — обычные документы; 300 — мелкий текст и плохие сканы (дольше).
    "dpi": 200,
    # Не больше Parallel requests, с которым модель запущена в LM Studio.
    "concurrency": 4,
    "page_timeout_seconds": 300,
    # Как часто спрашивать сервер, когда очередь пуста.
    "poll_interval_seconds": 60,
}


@dataclass(frozen=True, slots=True)
class Config:
    server_url: str
    token: str
    lmstudio_base_url: str
    lmstudio_api_key: str
    model: str
    dpi: int
    concurrency: int
    page_timeout_seconds: int
    poll_interval_seconds: int

    @property
    def api(self) -> str:
        return self.server_url.rstrip("/") + "/api/ocr-agent"


def config_path() -> Path:
    override = os.environ.get("MERIDIAN_OCR_AGENT_CONFIG")
    if override:
        return Path(override)
    beside = Path(__file__).resolve().parent.parent / CONFIG_NAME
    if beside.exists():
        return beside
    return Path.home() / ".meridian-ocr" / CONFIG_NAME


def load(path: Path | None = None) -> Config:
    """Читает настройки. Нет файла — создаёт шаблон и объясняет, что вписать."""
    target = path or config_path()
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(
            f"Создан файл настроек: {target}\n"
            "Впишите токен агента из Meridian (Админка → «Распознавание сканов» → "
            "«Подключить компьютер») и запустите снова."
        )

    # utf-8-sig: PowerShell 5.1 пишет JSON с меткой порядка байтов.
    raw = json.loads(target.read_text(encoding="utf-8-sig"))
    merged = {**DEFAULT_CONFIG, **raw}

    token = str(merged["token"]).strip()
    if not token:
        raise SystemExit(f"В {target} не задан token — возьмите его в админке Meridian.")
    if not token.isascii():
        # Токен уходит заголовком HTTP, заголовок обязан быть ASCII. Из буфера обмена
        # иногда приезжают «умные» кавычки или неразрывный пробел.
        raise SystemExit(f"В {target} токен содержит нелатинские символы — скопируйте его заново.")

    return Config(
        server_url=str(merged["server_url"]).strip(),
        token=token,
        lmstudio_base_url=str(merged["lmstudio_base_url"]).strip().rstrip("/"),
        lmstudio_api_key=str(merged["lmstudio_api_key"]).strip(),
        model=str(merged["model"]).strip() or "chandra-ocr-2",
        dpi=max(72, min(400, int(merged["dpi"]))),
        concurrency=max(1, min(8, int(merged["concurrency"]))),
        page_timeout_seconds=max(30, int(merged["page_timeout_seconds"])),
        poll_interval_seconds=max(10, int(merged["poll_interval_seconds"])),
    )
