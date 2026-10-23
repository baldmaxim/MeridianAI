# -*- coding: utf-8 -*-
"""Правка распознанного текста по словарю терминов.

GigaAM пишет «машины места» вместо «машино-места». Код ищет кандидатов, LLM только
подтверждает/отклоняет, код проверяет ответ и применяет правку, сохраняя исходник.
"""

import copy
import json

import pytest

from app.core.batch import term_corrector
from app.core.batch.term_corrector import TermCorrector, apply_corrections, validate_fix
from app.core.batch.term_lexicon import (
    Lexicon, load_base_lexicon_entries, parse_lexicon_text, phon, plain,
)
from app.core.batch.term_matcher import Candidate, find_candidates, levenshtein


def _lexicon() -> Lexicon:
    return Lexicon.from_entries([
        ("машино-место", [], "base"),
        ("кладовка", [], "base"),
        ("ЛСР", [], "base"),
    ])


def _words(text: str, speaker: str = "Speaker_0", t0: float = 0.0):
    return [
        {"text": w, "start": t0 + i, "end": t0 + i + 0.5, "speaker_id": speaker}
        for i, w in enumerate(text.split())
    ]


def _cand(text="машины места", form="машино-место", **kw) -> Candidate:
    base = dict(id=0, seg=0, w0=0, w1=2, text=text, term="машино-место", form=form, score=0.9)
    base.update(kw)
    return Candidate(**base)


# --- plain / phon / словарь ---

def test_plain_and_phon():
    assert plain("Машино-место, Ёж!") == "машиноместоеж"
    assert plain("КС-2") == "кс2"
    # о→а, ы→и, в→ф, д→т; ь/ъ выпадают; повторы схлопываются
    assert phon("кладовка") == "клатафка"
    assert phon("Ссора") == "сара"
    assert phon("объём") == "апим"
    assert phon("машины места") == "машинимиста"
    assert phon("машино-место") == "машинамиста"
    assert phon("КС-2 abc") == "кс2abc"
    assert phon("abc 12") == "abc12"


def test_lexicon_fuzzy_flags_and_dedup():
    lex = Lexicon.from_entries([
        ("кладовка", ["Кладовка", "кладовая"], "base"),   # дубль по plain отсекается
        ("ЛСР", [], "base"),                              # аббревиатура
        ("КС-2", [], "base"),
        ("аванс", [], "base"),                            # 5 букв — нечёткий
        ("ТЗ", [], "base"),
    ])
    by_form = {f.form: f for f in lex.forms}
    assert len(lex.forms) == 6
    assert by_form["кладовка"].fuzzy and by_form["кладовая"].fuzzy
    assert not by_form["ЛСР"].fuzzy and not by_form["КС-2"].fuzzy and not by_form["ТЗ"].fuzzy
    assert by_form["аванс"].fuzzy
    assert lex.terms() == ["кладовка", "ЛСР", "КС-2", "аванс", "ТЗ"]


def test_lexicon_version_stable_and_changes():
    a = Lexicon.from_entries([("кладовка", [], "base"), ("аванс", [], "base")])
    b = Lexicon.from_entries([("аванс", [], "base"), ("кладовка", [], "base")])
    c = Lexicon.from_entries([("аванс", [], "base")])
    assert a.version == b.version != c.version


def test_parse_lexicon_text():
    entries = parse_lexicon_text(
        "# коммент\n\nкладовка\nдопсоглашение = дополнительное соглашение; доп. соглашение\n"
        "аванс  # хвост\n"
    )
    assert entries == [
        ("кладовка", [], "base"),
        ("допсоглашение", ["дополнительное соглашение", "доп. соглашение"], "base"),
        ("аванс", [], "base"),
    ]


def test_base_lexicon_loads():
    lex = Lexicon.from_entries(load_base_lexicon_entries())
    assert "машино-место" in lex.terms() and "КС-2" in lex.terms()


def test_levenshtein():
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("", "abc") == 3
    assert levenshtein("abc", "abc", 0) == 0
    assert levenshtein("abcdef", "uvwxyz", 2) == 3     # отсечка → max_dist + 1
    assert levenshtein("abc", "abcdefgh", 2) == 3


# --- кандидаты ---

@pytest.mark.parametrize("text,expected", [
    ("Нужны машины места для всех.", "машины места"),
    ("В подвале кладов не хватает", "кладов"),
])
def test_candidates_found(text, expected):
    cands = find_candidates(_words(text), _lexicon())
    assert [c.text for c in cands] == [expected]
    assert [c.id for c in cands] == [0]


@pytest.mark.parametrize("text", [
    "Нужны машино-места для всех",
    "Много кладовок в подвале",
    "Кладовками займёмся позже",
    "Принято в ЛСР",
    "Это в машино-места для всех",   # лишнее слово слева не делает правильную форму кандидатом
])
def test_no_candidate_for_correct_or_unrelated(text):
    assert find_candidates(_words(text), _lexicon()) == []


def test_candidate_text_drops_trailing_punct_and_keeps_span():
    words = _words("Это машины места.")
    cand = find_candidates(words, _lexicon())[0]
    assert (cand.w0, cand.w1, cand.text) == (1, 3, "машины места")
    assert cand.term == "машино-место" and cand.form == "машино-место" and cand.score >= 0.8


def test_window_does_not_cross_speaker_change():
    words = _words("Нужны машины", "Speaker_0") + _words("места всем", "Speaker_1", 10)
    assert find_candidates(words, _lexicon()) == []


def test_windows_with_digits_skipped():
    assert find_candidates(_words("машины 5 места"), _lexicon()) == []


def test_overlapping_windows_keep_best():
    cands = find_candidates(_words("машины места"), _lexicon())
    assert len(cands) == 1 and (cands[0].w0, cands[0].w1) == (0, 2)


def test_find_candidates_empty_inputs():
    assert find_candidates([], _lexicon()) == []
    assert find_candidates(_words("машины места"), Lexicon.from_entries([])) == []


# --- validate_fix ---

@pytest.mark.parametrize("to,ok", [
    ("машино-места", True),
    ("Машино-места", True),
    ("машинка", False),
    ("машино-места 2", False),
    ("", False),
    ("   ", False),
    ("машины места", False),            # то же, что и исходник
    ("машино-места и ещё слова", False),
    ("машино-местами-всякими", False),   # слишком длинный
])
def test_validate_fix(to, ok):
    assert validate_fix(_cand(), to) is ok


def test_validate_fix_rejects_non_string():
    assert validate_fix(_cand(), None) is False
    assert validate_fix(_cand(), 5) is False


# --- применение ---

def _tr():
    words = [
        {"text": "Нужны", "start": 0.0, "end": 0.4, "speaker_id": "Speaker_0"},
        {"text": "Машины", "start": 0.5, "end": 0.9, "speaker_id": "Speaker_0"},
        {"text": "места,", "start": 1.0, "end": 1.4, "speaker_id": "Speaker_0"},
        {"text": "и", "start": 1.5, "end": 1.6, "speaker_id": "Speaker_0"},
        {"text": "кладов.", "start": 1.7, "end": 2.0, "speaker_id": "Speaker_1"},
    ]
    return {"text": " ".join(w["text"] for w in words), "words": words}


def test_apply_corrections_punct_case_orig_and_times():
    out = apply_corrections(_tr(), [
        {"w0": 1, "w1": 3, "from": "Машины места", "to": "машино-места", "term": "машино-место"},
        {"w0": 4, "w1": 5, "from": "кладов", "to": "кладовок", "term": "кладовка"},
    ])
    assert [w["text"] for w in out["words"]] == ["Нужны", "Машино-места,", "и", "кладовок."]
    merged = out["words"][1]
    assert merged["orig"] == "Машины места,"
    assert (merged["start"], merged["end"], merged["speaker_id"]) == (0.5, 1.4, "Speaker_0")
    assert out["words"][3]["orig"] == "кладов."
    assert out["text"] == "Нужны Машино-места, и кладовок."


def test_apply_corrections_does_not_mutate_input():
    tr = _tr()
    snapshot = copy.deepcopy(tr)
    apply_corrections(tr, [{"w0": 1, "w1": 3, "from": "x", "to": "машино-места", "term": "t"}])
    assert tr == snapshot


def test_apply_corrections_skips_overlaps_and_bad_bounds():
    out = apply_corrections(_tr(), [
        {"w0": 1, "w1": 3, "from": "a", "to": "машино-места", "term": "t"},
        {"w0": 2, "w1": 4, "from": "b", "to": "перекрытие", "term": "t"},
        {"w0": 4, "w1": 9, "from": "c", "to": "за границей", "term": "t"},
        {"w0": 3, "w1": 3, "from": "d", "to": "пусто", "term": "t"},
    ])
    # применяем с конца: (2,4) занято первым, пересекающая его (1,3) пропущена
    assert [w["text"] for w in out["words"]] == ["Нужны", "Машины", "перекрытие", "кладов."]


def test_apply_corrections_no_items_is_copy():
    tr = _tr()
    out = apply_corrections(tr, [])
    assert out == tr and out is not tr and out["words"] is not tr["words"]


# --- TermCorrector ---

class _Resp:
    def __init__(self, status_code=200, content=""):
        self.status_code = status_code
        self.text = content
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _llm_answer(monkeypatch, content, calls):
    def fake_post(url, **kw):
        calls.append(kw["json"])
        return _Resp(200, content)
    monkeypatch.setattr(term_corrector.requests, "post", fake_post)


@pytest.mark.asyncio
async def test_corrector_accepts_valid_and_drops_unknown_or_invalid(monkeypatch):
    words = _words("Нужны машины места, а кладов мало")
    lex = _lexicon()
    cands = find_candidates(words, lex)
    assert [c.text for c in cands] == ["машины места", "кладов"]
    answer = json.dumps({"fixes": [
        {"id": 0, "to": "машино-места"},
        {"id": 77, "to": "кладовок"},      # неизвестный id
        {"id": 1, "to": "кладовщик 5"},    # не прошёл validate_fix
    ]})
    calls: list = []
    _llm_answer(monkeypatch, "```json\n" + answer + "\n```", calls)

    result = await TermCorrector("k").correct({"text": "", "words": words}, lex)

    assert result == {"v": 1, "lexicon": lex.version, "items": [
        {"w0": 1, "w1": 3, "from": "машины места", "to": "машино-места", "term": "машино-место"},
    ]}
    assert len(calls) == 1 and calls[0]["temperature"] == 0 and calls[0]["max_tokens"] == 4096
    assert "[[машины места]]" in calls[0]["messages"][1]["content"]


@pytest.mark.asyncio
async def test_corrector_without_candidates_skips_llm(monkeypatch):
    calls: list = []
    _llm_answer(monkeypatch, "{}", calls)
    lex = _lexicon()
    result = await TermCorrector("k").correct({"words": _words("Всё хорошо, кладовок хватает")}, lex)
    assert result == {"v": 1, "lexicon": lex.version, "items": []}
    assert calls == []


@pytest.mark.asyncio
async def test_corrector_returns_none_when_all_requests_fail(monkeypatch):
    monkeypatch.setattr(term_corrector.time, "sleep", lambda s: None)
    monkeypatch.setattr(term_corrector.requests, "post", lambda *a, **kw: _Resp(503, "busy"))
    result = await TermCorrector("k").correct({"words": _words("Нужны машины места")}, _lexicon())
    assert result is None


@pytest.mark.asyncio
async def test_corrector_invalid_json_counts_as_failure(monkeypatch):
    calls: list = []
    _llm_answer(monkeypatch, "извините, не могу", calls)
    assert await TermCorrector("k").correct({"words": _words("Нужны машины места")}, _lexicon()) is None


@pytest.mark.asyncio
async def test_corrector_partial_failure_returns_what_was_received(monkeypatch):
    monkeypatch.setattr(term_corrector, "CHUNK_SIZE", 1)
    monkeypatch.setattr(term_corrector.time, "sleep", lambda s: None)
    words = _words("Нужны машины места, а кладов мало")
    state = {"n": 0}

    def fake_post(url, **kw):
        state["n"] += 1
        if "[[машины места]]" in kw["json"]["messages"][1]["content"]:
            return _Resp(200, json.dumps({"fixes": [{"id": 0, "to": "машино-места"}]}))
        return _Resp(500, "boom")

    monkeypatch.setattr(term_corrector.requests, "post", fake_post)
    result = await TermCorrector("k").correct({"words": words}, _lexicon())
    assert result is not None
    assert [it["to"] for it in result["items"]] == ["машино-места"]


def test_exact_other_term_is_not_candidate():
    # «чистовая отделка» сама словарная — не должна стать «черновой отделкой».
    lex = Lexicon.from_entries([("черновая отделка", [], "base"), ("чистовая отделка", [], "base")])
    assert find_candidates(_words("Чистовая отделка подразумевает замену"), lex) == []
    found = find_candidates(_words("тут чирновая отделка"), lex)
    assert [c.term for c in found] == ["черновая отделка"]


def test_short_words_are_not_glued():
    lex = Lexicon.from_entries([("дренаж", [], "base"), ("воронка", [], "base"), ("аквастоп", [], "base")])
    assert find_candidates(_words("сдаём три на квартиры"), lex) == []
    assert find_candidates(_words("Вот он пришёл"), lex) == []
    assert [c.text for c in find_candidates(_words("аква стоит но"), lex)] == ["аква стоит"]
