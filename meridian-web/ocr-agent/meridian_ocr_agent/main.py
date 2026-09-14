"""Цикл агента: взять скан из очереди Meridian, распознать локально, сдать текст.

Направление обращено, как в агенте MailHub: сервер не достучится до компьютера за NAT,
поэтому агент сам ходит на сервер по HTTPS. На компьютере не открыт ни один входящий порт.

Страницы сдаются по одной. Это продлевает аренду задачи и позволяет после перезагрузки
продолжить с того же места — сервер при выдаче сообщает, какие страницы уже готовы.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
import time
from typing import Any

import httpx

from meridian_ocr_agent import VERSION, log
from meridian_ocr_agent.config import Config, load
from meridian_ocr_agent.ocr import (
    LmStudioError,
    ModelUnavailable,
    ensure_model,
    page_count,
    recognize_page_detailed,
    render_page,
)

logger = logging.getLogger("meridian_ocr_agent")

SERVER_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 300
PAGE_RETRIES = 2


class TokenRejected(Exception):
    """Сервер не принял токен — агента отозвали или токен вписан неверно."""


class LeaseLost(Exception):
    """Задачу забрали, пока компьютер спал: работать над ней дальше незачем."""


async def server_post(client: httpx.AsyncClient, config: Config, path: str,
                      payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = await client.post(f"{config.api}{path}", json=payload or {},
                                 headers={"Authorization": f"Bearer {config.token}"},
                                 timeout=SERVER_TIMEOUT)
    if response.status_code == 401:
        raise TokenRejected("сервер не принял токен агента — возьмите новый в админке Meridian")
    if response.status_code == 409:
        raise LeaseLost(response.json().get("detail", "задача больше не наша"))
    response.raise_for_status()
    return response.json()


async def download_pdf(client: httpx.AsyncClient, url: str) -> bytes:
    """PDF в память, без временного файла: на Windows поток рендера держал бы файл открытым,
    и прерванная задача оставляла бы после себя неудаляемую папку. Документы — до 50 МБ."""
    response = await client.get(url, timeout=DOWNLOAD_TIMEOUT)
    response.raise_for_status()
    data = response.content
    if not data.startswith(b"%PDF-"):
        raise ValueError("по ссылке пришёл не PDF")
    return data


async def process_task(client: httpx.AsyncClient, config: Config, task: dict[str, Any]) -> str:
    """Распознать один документ. Возвращает итог для журнала."""
    task_id = task["task_id"]
    name = task.get("file_name") or f"документ {task['document_id']}"
    hello = {"model": config.model}

    try:
        pdf = await download_pdf(client, task["pdf_url"])
        pages = await asyncio.to_thread(page_count, pdf)
    except Exception as cause:
        await _fail(client, config, task_id, f"не удалось открыть PDF: {cause}")
        return f"«{name}»: файл не открылся"

    if pages > int(task.get("max_pages") or pages):
        await _fail(client, config, task_id, f"в документе {pages} стр. — больше лимита сервера")
        return f"«{name}»: слишком много страниц"

    done = set(task.get("pages_done") or [])
    todo = [n for n in range(1, pages + 1) if n not in done]
    logger.info("«%s»: %s стр., распознать %s", name, pages, len(todo))
    semaphore = asyncio.Semaphore(config.concurrency)
    pace = Pace(config.concurrency)

    async def one(number: int) -> None:
        async with semaphore:  # сначала слот, потом рендер — картинки не копятся в памяти
            text, note = await _recognize_with_fallback(client, config, pdf, number, name, pace)
            payload = {"page_number": number, "pages_total": pages, "text": text, **hello}
            if note:
                payload["note"] = note  # диагностика необычного ответа модели — видна в логах сервера
            await server_post(client, config, f"/tasks/{task_id}/pages", payload)

    try:
        async with asyncio.TaskGroup() as group:
            for number in todo:
                group.create_task(one(number))
    except ExceptionGroup as group_error:
        first = group_error.exceptions[0]
        if isinstance(first, (LeaseLost, TokenRejected)):
            raise first from None
        # Частичный текст опаснее отсутствующего — документ целиком уходит в повтор.
        await _fail(client, config, task_id, str(first))
        return f"«{name}»: {first}"

    await server_post(client, config, f"/tasks/{task_id}/complete")
    return f"«{name}»: распознано {pages} стр."


def dpi_steps(dpi: int) -> list[int]:
    """Разрешения для повторов при переполнении контекста: заданное, затем всё мельче.

    Картинка — основная часть запроса к модели. LM Studio с несколькими параллельными
    запросами делит контекст между ними, и плотная страница в 200 DPI может не влезть.
    Ниже 110 DPI мелкий текст договора уже теряется — дальше не опускаемся.
    """
    steps = [dpi] + [d for d in (150, 110) if d < dpi]
    return steps


class Pace:
    """Темп запросов к LM Studio на один документ.

    Параллельные запросы быстрее, только если LM Studio действительно держит несколько слотов.
    Если сервер обрабатывает по одному, остальные запросы стоят в его очереди и истекают по
    таймауту, так и не начав работу. Первый таймаут снижает лимит до одного запроса: новые
    ждут, пока не завершатся все уже отправленные, — иначе повтор снова столкнулся бы с ними.
    """

    def __init__(self, limit: int = 1) -> None:
        self.limit = max(1, limit)
        self.active = 0
        self._changed = asyncio.Condition()

    @property
    def serial(self) -> bool:
        return self.limit == 1

    def slow_down(self) -> None:
        self.limit = 1

    @contextlib.asynccontextmanager
    async def slot(self):
        async with self._changed:
            await self._changed.wait_for(lambda: self.active < self.limit)
            self.active += 1
        try:
            yield
        finally:
            async with self._changed:
                self.active -= 1
                self._changed.notify_all()


def describe(error: BaseException | None) -> str:
    """Причина для сервера: у сетевых исключений httpx текст часто пустой — тип обязателен."""
    if error is None:
        return "неизвестная ошибка"
    text = str(error).strip()
    if isinstance(error, LmStudioError):
        return text
    return f"{type(error).__name__}: {text}" if text else type(error).__name__


async def _recognize_with_fallback(client: httpx.AsyncClient, config: Config, pdf: bytes,
                                   number: int, name: str, pace: Pace) -> tuple[str, str | None]:
    """Распознать страницу: повтор при сбое, меньшее разрешение при переполнении контекста,
    последовательный режим при таймауте. Возвращает (текст, заметка для сервера или None)."""
    last: BaseException | None = None
    got_empty = False
    empty_notes: list[str] = []
    for dpi in dpi_steps(config.dpi):
        png = await asyncio.to_thread(render_page, pdf, number - 1, dpi)
        attempt = 0
        while attempt < PAGE_RETRIES:
            attempt += 1
            started = time.monotonic()
            try:
                async with pace.slot():
                    answer = await recognize_page_detailed(client, config, png)
                if answer.text.strip():
                    if answer.source != "content":
                        # Текст нашёлся в поле рассуждений, а не в ответе — сообщаем серверу.
                        note = f"стр. {number}, {dpi} DPI: {answer.diagnostics}"
                        logger.warning("«%s» %s", name, note)
                        return answer.text, note
                    return answer.text, None
                # Модель иногда молчит на странице с текстом (на реальном договоре — титул с
                # номером, датой и сторонами). Другое разрешение обычно помогает.
                got_empty = True
                empty_notes.append(f"{dpi} DPI: {answer.diagnostics}")
                logger.warning("«%s» стр. %s: пустой ответ модели при %s DPI (%s)",
                               name, number, dpi, answer.diagnostics)
                break
            except LmStudioError as cause:
                last = cause
                logger.warning("«%s» стр. %s, %s DPI, попытка %s: %s", name, number, dpi, attempt, cause)
                if cause.context_overflow:
                    break  # повтор того же размера бесполезен — сразу мельче
            except httpx.TimeoutException as cause:
                last = cause
                spent = int(time.monotonic() - started)
                if not pace.serial:
                    # Запрос мог простоять в очереди LM Studio за соседними — дело не в странице.
                    pace.slow_down()
                    attempt -= 1  # переход в последовательный режим попыткой не считаем
                    logger.warning("«%s» стр. %s: таймаут через %s с — LM Studio не успевает "
                                   "параллельно, дальше страницы идут по одной", name, number, spent)
                    continue
                logger.warning("«%s» стр. %s, попытка %s: таймаут через %s с", name, number, attempt, spent)
            except httpx.HTTPError as cause:
                last = cause
                logger.warning("«%s» стр. %s, попытка %s: %s", name, number, attempt, describe(cause))
        else:
            break  # попытки упали не из-за размера — уменьшение не поможет
    if got_empty and last is None:
        # Пусто при всех разрешениях: пустой лист — или модель молчит на странице с текстом.
        # Различить отсюда нельзя, поэтому страница принимается, а сервер получает диагностику.
        return "", f"стр. {number} пустая при всех разрешениях — " + " | ".join(empty_notes)
    # Причина уходит на сервер: её видно в админке без доступа к компьютеру.
    raise RuntimeError(f"страница {number} не распозналась: {describe(last)}")


async def _fail(client: httpx.AsyncClient, config: Config, task_id: int, reason: str) -> None:
    logger.error("задача %s: %s", task_id, reason)
    try:
        await server_post(client, config, f"/tasks/{task_id}/fail", {"error": reason[:2000]})
    except (httpx.HTTPError, LeaseLost):
        pass  # аренда всё равно истечёт сама


async def run(config: Config, *, once: bool = False) -> int:
    logger.info("агент распознавания %s: сервер %s, модель %s", VERSION, config.server_url, config.model)
    hello = {"model": config.model, "agent_version": VERSION}
    last_problem = ""
    async with httpx.AsyncClient() as client:
        while True:
            took_task = False
            try:
                await ensure_model(client, config)
                if last_problem:
                    logger.info("LM Studio снова на связи")
                    last_problem = ""
                response = await server_post(client, config, "/claim", hello)
                task = response.get("task")
                if task:
                    took_task = True
                    logger.info(await process_task(client, config, task))
                else:
                    await server_post(client, config, "/heartbeat", hello)
            except ModelUnavailable as cause:
                # Модель выключена — задачи не берём, но отмечаемся, чтобы админка видела компьютер.
                if str(cause) != last_problem:
                    logger.warning("%s", cause)
                    last_problem = str(cause)
                try:
                    await server_post(client, config, "/heartbeat", {"agent_version": VERSION})
                except httpx.HTTPError:
                    pass
            except TokenRejected as cause:
                logger.error("%s", cause)
                return 2
            except LeaseLost as cause:
                logger.warning("задачу забрали, пока компьютер не отвечал: %s", cause)
            except httpx.HTTPError as cause:
                logger.warning("сервер недоступен: %s", type(cause).__name__)

            if once:
                return 0
            if not took_task:  # после выполненной задачи сразу за следующей
                await asyncio.sleep(config.poll_interval_seconds)


async def check(config: Config) -> int:
    """Проверка связи: сервер и LM Studio. Очередь не трогает."""
    ok = True
    async with httpx.AsyncClient() as client:
        try:
            info = await server_post(client, config, "/heartbeat", {"agent_version": VERSION})
            print(f"Сервер: OK ({config.server_url}, агент «{info.get('agent')}»)")
        except (httpx.HTTPError, TokenRejected) as cause:
            ok = False
            print(f"Сервер: ОШИБКА — {cause}")
        try:
            await ensure_model(client, config)
            print(f"LM Studio: OK ({config.lmstudio_base_url}, модель {config.model} загружена)")
        except ModelUnavailable as cause:
            ok = False
            print(f"LM Studio: ОШИБКА — {cause}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meridian-ocr-agent",
                                     description="Распознавание сканов Meridian локальной моделью")
    parser.add_argument("--once", action="store_true", help="один заход и выход")
    parser.add_argument("--check", action="store_true", help="проверить связь, очередь не трогать")
    parser.add_argument("--verbose", action="store_true", help="подробный вывод")
    args = parser.parse_args(argv)
    log.setup(verbose=args.verbose)
    # Под pythonw нет консоли: всё, что может уронить агента, обязано дойти до журнала.
    try:
        config = load()
        if args.check:
            return asyncio.run(check(config))
        return asyncio.run(run(config, once=args.once))
    except KeyboardInterrupt:
        logger.info("остановлен")
        return 0
    except SystemExit as cause:
        logger.error("%s", cause)
        return int(cause.code) if isinstance(cause.code, int) else 1
    except Exception:
        logger.exception("агент остановлен непредвиденной ошибкой")
        return 1
    finally:
        logging.shutdown()


if __name__ == "__main__":
    sys.exit(main())
