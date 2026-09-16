# -*- coding: utf-8 -*-
"""Подозрительные страницы распознанного скана.

Модель распознавания иногда молча теряет кусок страницы: на стр. 73 договора фраза обрывается
на «…все ранее взысканные Застройщиком с», а стр. 74 начинается с новой фразы — верх страницы
пропал. Подсказки по такому месту модель дописывает сама. Проверка не исправляет текст, а
показывает, какие страницы стоит сверить со сканом.
"""

import re
from statistics import median

# Фраза явно не закончена: страница кончается на предлог или союз.
_DANGLING_WORDS = frozenset(
    "с со в во на по к ко о об от до из за для при без под над и или а но что как не".split()
)
_CLAUSE_HEAD = re.compile(r"^\d{1,2}(?:\.\d{1,3}){1,4}\.?\s")
_PAGE_NUMBER_LINE = re.compile(r"^\s*\d{1,4}\s*$")

SHORT_PAGE_SHARE = 0.35


def _content_lines(text: str) -> list[str]:
    lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
    return [ln for ln in lines if not _PAGE_NUMBER_LINE.match(ln)]


def ocr_page_warnings(segments: list[dict], page_count: int | None = None) -> list[dict]:
    """[{page, reason}] — страницы, которые стоит сверить со сканом.

    segments — только страницы с текстом; page_count — сколько страниц в скане. Страница без
    текста (модель вернула пустоту или одну служебную разметку) — самый частый и самый опасный
    случай: поиск молча идёт мимо, а подсказка додумывает оборванную фразу.
    """
    pages = sorted((s for s in segments if (s.get("text") or "").strip() and s.get("page_number")),
                   key=lambda s: s["page_number"])
    present = {s["page_number"] for s in pages}
    warnings = [{"page": n, "reason": "страница не распознана"}
                for n in range(1, (page_count or 0) + 1) if n not in present]

    lengths = [len(s["text"]) for s in pages]
    typical = median(lengths) if lengths else 0
    for i, seg in enumerate(pages):
        page, text = seg["page_number"], seg["text"]
        # первая и последняя страницы (титул, подписи) законно короче
        if 0 < i < len(pages) - 1 and typical and len(text) < typical * SHORT_PAGE_SHARE:
            warnings.append({"page": page, "reason": "текста заметно меньше, чем на соседних страницах"})
        nxt = pages[i + 1] if i + 1 < len(pages) else None
        if nxt is None or nxt["page_number"] != page + 1:
            continue
        tail, head = _content_lines(text), _content_lines(nxt["text"])
        if not tail or not head:
            continue
        # Обрыв на предлоге перед новым пунктом: «…взысканные Застройщиком с» → «20.8. …».
        # Заглавная буква на новой странице ничего не значит: термины договора пишутся с заглавной.
        last_token = tail[-1].split()[-1].lower()
        if last_token in _DANGLING_WORDS and _CLAUSE_HEAD.match(head[0]):
            warnings.append({
                "page": nxt["page_number"],
                "reason": f"фраза на стр. {page} обрывается перед новым пунктом — возможно, потерян текст",
            })
    return sorted(warnings, key=lambda w: w["page"])


def ocr_quality_note(warnings: list[dict], limit: int = 5) -> str | None:
    """Коротко для списка документов: «Сверьте со сканом стр. 74, 80»."""
    if not warnings:
        return None
    pages = sorted({w["page"] for w in warnings})
    shown = ", ".join(str(p) for p in pages[:limit]) + (" …" if len(pages) > limit else "")
    return f"Сверьте со сканом стр. {shown}: распознавание могло потерять текст"
