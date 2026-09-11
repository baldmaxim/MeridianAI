"""Агент распознавания сканов: сервер Meridian, S3 и LM Studio подменены, сети нет."""

from __future__ import annotations

import io
import json

import httpx
import pytest

from meridian_ocr_agent import main as agent
from meridian_ocr_agent.config import Config, load
from meridian_ocr_agent.ocr import ModelUnavailable, clean_ocr_text, ensure_model

SERVER = "https://srv.test"
LM = "http://lm.test/v1"
PDF_URL = "https://s3.test/doc.pdf"

# Настоящий класс: тесты цикла подменяют httpx.AsyncClient, а мир строит клиент на нём.
_RealAsyncClient = httpx.AsyncClient


def make_pdf(pages: int) -> bytes:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(595, 842)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def config(**over) -> Config:
    base = dict(server_url=SERVER, token="tok", lmstudio_base_url=LM, lmstudio_api_key="",
                model="chandra-ocr-2", dpi=72, concurrency=2, page_timeout_seconds=30,
                poll_interval_seconds=10)
    base.update(over)
    return Config(**base)


class World:
    """Подменённый мир: что пришло на сервер и в LM Studio."""

    def __init__(self, *, pages=3, models=("chandra-ocr-2",), lm_fail_calls=(), page_409=False,
                 pdf_bytes=None, token_ok=True, task=None):
        self.pdf = pdf_bytes if pdf_bytes is not None else make_pdf(pages)
        self.models = list(models)
        self.lm_fail = set(lm_fail_calls)
        self.page_409 = page_409
        self.token_ok = token_ok
        self.task = task
        self.lm_calls = 0
        self.lm_bodies: list[dict] = []
        self.pages: dict[int, str] = {}
        self.calls: list[str] = []
        self.failed: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == PDF_URL:
            return httpx.Response(200, content=self.pdf)
        if url == f"{LM}/models":
            return httpx.Response(200, json={"data": [{"id": m} for m in self.models]})
        if url == f"{LM}/chat/completions":
            self.lm_calls += 1
            self.lm_bodies.append(json.loads(request.content))
            if self.lm_calls in self.lm_fail:
                return httpx.Response(500, json={"error": "boom"})
            fence = "`" * 3
            return httpx.Response(200, json={"choices": [{"message": {
                "content": f"{fence}markdown\nСтраница текст {self.lm_calls}\n{fence}"}}]})
        if url.startswith(SERVER):
            path = url[len(SERVER) + len("/api/ocr-agent"):]
            self.calls.append(path)
            if request.headers.get("Authorization") != "Bearer tok" or not self.token_ok:
                return httpx.Response(401, json={"detail": "no"})
            data = json.loads(request.content or b"{}")
            if path == "/claim":
                return httpx.Response(200, json={"task": self.task})
            if path == "/heartbeat":
                return httpx.Response(200, json={"ok": True, "agent": "ПК"})
            if path.endswith("/pages"):
                if self.page_409:
                    return httpx.Response(409, json={"detail": "задача не арендована этим агентом"})
                self.pages[data["page_number"]] = data["text"]
                return httpx.Response(200, json={"ok": True, "pages_done": len(self.pages)})
            if path.endswith("/complete"):
                return httpx.Response(200, json={"ok": True})
            if path.endswith("/fail"):
                self.failed.append(data["error"])
                return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    def client(self) -> httpx.AsyncClient:
        return _RealAsyncClient(transport=httpx.MockTransport(self.handler))


def task(pages_done=(), max_pages=150):
    return {"task_id": 7, "document_id": 13, "file_name": "Договор ГП.pdf", "pdf_url": PDF_URL,
            "lease_seconds": 600, "max_pages": max_pages, "pages_done": list(pages_done)}


# ---------- распознавание документа ----------

async def test_pages_are_recognized_and_submitted_then_completed():
    world = World(pages=3)
    async with world.client() as client:
        outcome = await agent.process_task(client, config(), task())
    assert "распознано 3 стр." in outcome
    assert sorted(world.pages) == [1, 2, 3]
    assert all(t.startswith("Страница текст") for t in world.pages.values())  # обёртка снята
    assert world.calls[-1] == "/tasks/7/complete"
    parts = world.lm_bodies[0]["messages"][0]["content"]
    assert {p["type"] for p in parts} == {"text", "image_url"}


async def test_ready_pages_are_skipped_after_reboot():
    world = World(pages=3)
    async with world.client() as client:
        await agent.process_task(client, config(), task(pages_done=[1, 3]))
    assert list(world.pages) == [2] and world.lm_calls == 1


async def test_page_is_retried_once():
    world = World(pages=1, lm_fail_calls={1})
    async with world.client() as client:
        await agent.process_task(client, config(), task())
    assert world.lm_calls == 2 and list(world.pages) == [1]


async def test_page_failing_twice_fails_whole_task():
    """Частичный текст опаснее отсутствующего — документ не завершается."""
    world = World(pages=1, lm_fail_calls={1, 2})
    async with world.client() as client:
        outcome = await agent.process_task(client, config(concurrency=1), task())
    assert "не распозналась" in outcome
    assert world.failed and "/tasks/7/complete" not in world.calls


async def test_lost_lease_stops_work():
    world = World(pages=2, page_409=True)
    async with world.client() as client:
        with pytest.raises(agent.LeaseLost):
            await agent.process_task(client, config(), task())
    assert "/tasks/7/complete" not in world.calls


async def test_not_a_pdf_is_reported():
    world = World(pdf_bytes="<html>ссылка истекла</html>".encode("utf-8"))
    async with world.client() as client:
        outcome = await agent.process_task(client, config(), task())
    assert "не открылся" in outcome and "не PDF" in world.failed[0]


async def test_too_many_pages_are_refused_without_recognition():
    world = World(pages=3)
    async with world.client() as client:
        await agent.process_task(client, config(), task(max_pages=2))
    assert world.lm_calls == 0 and "больше лимита" in world.failed[0]


# ---------- цикл ----------

async def test_model_off_means_no_claim_but_heartbeat(monkeypatch):
    """Выключенная модель не должна сжигать попытки распознавания на сервере."""
    world = World(models=("qwen36-27b-mtp",), task=task())
    monkeypatch.setattr(agent.httpx, "AsyncClient", lambda **kw: world.client())
    assert await agent.run(config(), once=True) == 0
    assert "/claim" not in world.calls and "/heartbeat" in world.calls


async def test_rejected_token_stops_agent(monkeypatch):
    world = World(token_ok=False)
    monkeypatch.setattr(agent.httpx, "AsyncClient", lambda **kw: world.client())
    assert await agent.run(config(), once=True) == 2


async def test_idle_queue_sends_heartbeat(monkeypatch):
    world = World(task=None)
    monkeypatch.setattr(agent.httpx, "AsyncClient", lambda **kw: world.client())
    assert await agent.run(config(), once=True) == 0
    assert world.calls == ["/claim", "/heartbeat"]


# ---------- LM Studio ----------

async def test_missing_model_is_explained():
    world = World(models=("qwen36-27b-mtp", "lift"))
    async with world.client() as client:
        with pytest.raises(ModelUnavailable, match="не загружена модель chandra-ocr-2.*qwen36-27b-mtp"):
            await ensure_model(client, config())


async def test_lmstudio_down_is_explained():
    def down(request):
        raise httpx.ConnectError("refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as client:
        with pytest.raises(ModelUnavailable, match="не отвечает"):
            await ensure_model(client, config())


@pytest.mark.parametrize("raw,expected", [
    ("`" * 3 + "markdown\n# ДОГОВОР\n" + "`" * 3, "# ДОГОВОР"), ("  текст ", "текст"), (None, ""),
])
def test_clean_text(raw, expected):
    assert clean_ocr_text(raw) == expected


# ---------- настройки ----------

def test_missing_config_creates_template(tmp_path):
    path = tmp_path / "agent.json"
    with pytest.raises(SystemExit, match="Создан файл настроек"):
        load(path)
    assert json.loads(path.read_text(encoding="utf-8"))["model"] == "chandra-ocr-2"


def test_non_ascii_token_is_refused(tmp_path):
    path = tmp_path / "agent.json"
    path.write_text(json.dumps({"token": "abc«def»"}, ensure_ascii=False), encoding="utf-8-sig")
    with pytest.raises(SystemExit, match="нелатинские"):
        load(path)


def test_config_reads_bom_and_clamps(tmp_path):
    path = tmp_path / "agent.json"
    path.write_text(json.dumps({"token": "tok", "concurrency": 99, "dpi": 10}), encoding="utf-8-sig")
    cfg = load(path)
    assert cfg.concurrency == 8 and cfg.dpi == 72
    assert cfg.api == "https://meridianai.ru/api/ocr-agent"
