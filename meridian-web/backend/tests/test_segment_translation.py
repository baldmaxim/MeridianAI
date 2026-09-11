# -*- coding: utf-8 -*-
"""Перевод иноязычных реплик транскрипта на русский.

Коллеги из Турции переключаются на свой язык по ходу встречи. Оригинал остаётся,
перевод хранится отдельно и подмешивается к репликам по индексу.
"""

import pytest

from app.core.batch.segment_translator import SegmentTranslator, needs_translation
from app.core.batch.utils import (
    TranscriptionSegment, build_translation_json, parse_translation_map,
)


@pytest.mark.parametrize("text", [
    "Fiyat çok yüksek",
    "Evet, tamam",
    "We agree on the advance payment",
])
def test_foreign_speech_needs_translation(text):
    assert needs_translation(text) is True


@pytest.mark.parametrize("text", [
    "Цена слишком высокая",
    "Согласны на аванс 30%",
    "Смета на 15 000 TL",   # латиница в единицах не делает реплику иноязычной
])
def test_russian_speech_left_alone(text):
    assert needs_translation(text) is False


@pytest.mark.parametrize("text", [
    "Вот technoflex.",
    "Ну, Claude и ChatGPT, да.",
    "А, Signal.",
    "Larus это IBIM, да?",
])
def test_russian_with_latin_brand_not_translated(text):
    """Реальные реплики с прода: в стройке сплошь латинские названия.

    По доле кириллицы такие короткие фразы выглядят иноязычными — раньше они уезжали
    в перевод и возвращались лишней строкой под оригиналом.
    """
    assert needs_translation(text) is False


def test_long_foreign_text_with_russian_word_still_translated():
    """Длинная иноязычная реплика с одним русским словом — всё ещё иноязычная."""
    text = ("Bizim teklifimiz avans olmadan mümkün değil, çünkü malzeme fiyatları "
            "her ay artıyor ve tedarikçi график sıkıştırıyor")
    assert needs_translation(text) is True


@pytest.mark.parametrize("text", ["", "   ", "2 500 000", "15:30"])
def test_textless_segments_not_translated(text):
    """Цифры и пустые реплики переводить нечего — иначе жжём токены впустую."""
    assert needs_translation(text) is False


def _segments():
    return [
        TranscriptionSegment("Speaker_1", 1.234, 2.0, "Fiyat çok yüksek"),
        TranscriptionSegment("Speaker_2", 3.0, 4.0, "Хорошо, обсудим"),
    ]


def test_translation_roundtrip_keeps_index():
    raw = build_translation_json({0: "Цена слишком высокая"}, _segments())
    assert parse_translation_map(raw) == {0: "Цена слишком высокая"}


def test_index_out_of_range_dropped():
    """Индекс вне списка реплик не должен попасть в хранилище."""
    assert parse_translation_map(build_translation_json({99: "x"}, _segments())) == {}


@pytest.mark.parametrize("raw", [None, "", "не json", '{"items": "не список"}', "[]"])
def test_broken_storage_degrades_to_empty(raw):
    """Битые данные не должны ронять выдачу транскрипта — просто нет перевода."""
    assert parse_translation_map(raw) == {}


def test_model_answer_parsed_and_filtered():
    """Модель иногда оборачивает JSON в ```json; чужие индексы отбрасываем."""
    fenced = '```json\n{"0": "Цена высокая", "9": "чужая реплика"}\n```'
    assert SegmentTranslator._parse(fenced, {0: "Fiyat yüksek", 3: "Evet"}) == {0: "Цена высокая"}


def test_echoed_original_dropped():
    """Модель вернула реплику без изменений → она была русской, второй строки не надо."""
    originals = {0: "Вот technoflex.", 1: "Fiyat yüksek"}
    answer = '{"0": "Вот technoflex.", "1": "Цена высокая"}'
    assert SegmentTranslator._parse(answer, originals) == {1: "Цена высокая"}


def test_model_garbage_answer_yields_nothing():
    assert SegmentTranslator._parse("извините, не могу", {0: "Evet"}) == {}
    assert SegmentTranslator._parse(None, {0: "Evet"}) == {}


@pytest.mark.asyncio
async def test_all_russian_transcript_skips_llm_call():
    """Одноязычная встреча не должна ходить в LLM вообще."""
    translator = SegmentTranslator(api_key="unused")

    def _boom(*a, **kw):  # noqa: ANN001 - сетевой вызов запрещён в этом сценарии
        raise AssertionError("LLM не должна вызываться для русского транскрипта")

    translator._translate_chunk = _boom
    assert await translator.translate(["Цена высокая", "Согласны"]) == {}
