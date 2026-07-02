"""Signal Engine (Этап 1): классификация переговорной ситуации без keyword-matching.

Тесты не требуют реального LLM API — используется fake llm_client с
async get_suggestion_async. БД не нужна (фикстуру db не запрашиваем).
"""

import asyncio
import json

from app.core.context.signal_engine import (
    NegotiationSignal,
    SignalEngine,
    passes_thresholds,
)
from app.core.llm.suggestion_prompts import build_auto_cards_prompt_from_signal


class _FakeLLM:
    """Fake LLM: возвращает заранее заданный ответ на get_suggestion_async."""

    def __init__(self, response):
        self._r = response
        self.model = "fake"

    async def get_suggestion_async(self, prompt, max_tokens=None):
        return self._r


class _SlowLLM:
    """Fake LLM: засыпает перед ответом (для теста timeout)."""

    def __init__(self, delay, response="{}"):
        self._delay = delay
        self._r = response
        self.model = "slow"

    async def get_suggestion_async(self, prompt, max_tokens=None):
        await asyncio.sleep(self._delay)
        return self._r


class _RaisingLLM:
    """Fake LLM: бросает исключение (для теста error_kind=exception)."""

    model = "raising"

    async def get_suggestion_async(self, prompt, max_tokens=None):
        raise RuntimeError("boom")


class _PromptCapturingLLM:
    """Fake LLM: сохраняет полученный prompt (для проверки содержимого)."""

    def __init__(self, response="{}"):
        self._r = response
        self.model = "capture"
        self.last_prompt = None

    async def get_suggestion_async(self, prompt, max_tokens=None):
        self.last_prompt = prompt
        return self._r


_VALID = {
    "should_prompt": True,
    "situation_type": "concession_requested",
    "phase": "bargaining",
    "speaker_side": "counterparty",
    "intent": "просит скидку 10% без встречных условий",
    "risk_level": "medium",
    "urgency": 0.7,
    "confidence": 0.8,
    "actionability": 0.75,
    "novelty_key": "concession_requested:counterparty:discount_without_exchange",
    "recommended_card_types": ["counter", "trade_concession"],
    "reasoning_summary": "Оппонент давит на уступку — уместен обмен.",
}


# --- classify (async, fake LLM) ---

async def test_signal_engine_parses_valid_json():
    # JSON в markdown-обёртке + лишний текст вокруг
    raw = "Вот результат:\n```json\n" + json.dumps(_VALID, ensure_ascii=False) + "\n```\nготово"
    result = await SignalEngine().classify(
        llm_client=_FakeLLM(raw), role_name="Подрядчик",
        recent_dialog="[00:01] НЕ МЫ: дайте скидку", current_text="дайте скидку 10%",
    )
    assert result.used_fallback is False
    assert result.error is None
    assert result.error_kind == "none"
    sig = result.signal
    assert sig.should_prompt is True
    assert sig.situation_type == "concession_requested"
    assert sig.speaker_side == "counterparty"
    assert sig.confidence == 0.8
    assert sig.recommended_card_types == ["counter", "trade_concession"]
    assert sig.novelty_key.startswith("concession_requested:")


async def test_signal_engine_returns_none_on_invalid_json():
    result = await SignalEngine().classify(
        llm_client=_FakeLLM("Извините, не могу ничего сказать по этому поводу."),
        role_name="Подрядчик", recent_dialog="", current_text="привет",
    )
    assert result.used_fallback is True
    assert result.error == "invalid_json"
    assert result.error_kind == "invalid_json"
    assert result.signal.should_prompt is False
    assert result.signal.situation_type == "none"


async def test_signal_engine_no_client_returns_fallback():
    result = await SignalEngine().classify(
        llm_client=None, role_name="Подрядчик", recent_dialog="", current_text="x",
    )
    assert result.used_fallback is True
    assert result.error == "no_llm_client"
    assert result.error_kind == "llm_unavailable"
    assert result.signal.should_prompt is False
    assert result.signal.situation_type == "none"


async def test_signal_engine_empty_string_is_invalid_json():
    # пустой/whitespace ответ БЕЗ исключения = проблема качества ответа → invalid_json (НЕ exception)
    result = await SignalEngine().classify(
        llm_client=_FakeLLM("   "), role_name="Подрядчик",
        recent_dialog="", current_text="x",
    )
    assert result.used_fallback is True
    assert result.error == "empty_llm_response"
    assert result.error_kind == "invalid_json"
    assert result.signal.should_prompt is False


async def test_signal_engine_none_response_is_invalid_json():
    result = await SignalEngine().classify(
        llm_client=_FakeLLM(None), role_name="Подрядчик",
        recent_dialog="", current_text="x",
    )
    assert result.used_fallback is True
    assert result.error == "empty_llm_response"
    assert result.error_kind == "invalid_json"
    assert result.signal.should_prompt is False


async def test_classify_includes_speaker_context_in_prompt():
    llm = _PromptCapturingLLM()
    await SignalEngine().classify(
        llm_client=llm, role_name="Подрядчик", recent_dialog="[00:01] МЫ: привет",
        current_text="дайте скидку",
        speaker_context="Speaker SM_0: side=our_side, functional_role=project_manager, confidence=0.92, source=manual_correction",
    )
    assert "Роли и стороны участников" in llm.last_prompt
    assert "Speaker SM_0: side=our_side" in llm.last_prompt
    # запрет путать device_role и сторону присутствует
    assert "device_role" in llm.last_prompt
    assert "НЕ угадывай сторону" in llm.last_prompt


async def test_classify_prompt_unknown_roles_note_when_no_speaker_context():
    llm = _PromptCapturingLLM()
    await SignalEngine().classify(
        llm_client=llm, role_name="Подрядчик", recent_dialog="", current_text="x",
    )
    assert "Роли участников неизвестны" in llm.last_prompt


async def test_signal_engine_validation_error_kind():
    # JSON извлекается, но situation_type вне Literal → ValidationError
    bad = json.dumps({"should_prompt": True, "situation_type": "totally_wrong"})
    result = await SignalEngine().classify(
        llm_client=_FakeLLM(bad), role_name="Подрядчик",
        recent_dialog="", current_text="x",
    )
    assert result.used_fallback is True
    assert result.error == "validation_error"
    assert result.error_kind == "validation_error"
    assert result.signal.situation_type == "none"


async def test_signal_engine_timeout_kind():
    result = await SignalEngine().classify(
        llm_client=_SlowLLM(0.3), role_name="Подрядчик",
        recent_dialog="", current_text="x", timeout_seconds=0.01,
    )
    assert result.used_fallback is True
    assert result.error_kind == "timeout"
    assert result.signal.should_prompt is False


async def test_signal_engine_exception_kind():
    result = await SignalEngine().classify(
        llm_client=_RaisingLLM(), role_name="Подрядчик",
        recent_dialog="", current_text="x",
    )
    assert result.used_fallback is True
    assert result.error_kind == "exception"
    assert result.signal.should_prompt is False


# --- модель: clamp / фильтрация (sync) ---

def test_signal_engine_clamps_scores():
    sig = NegotiationSignal(
        should_prompt=True,
        situation_type="price_pressure",
        urgency=5, confidence=-1, actionability=2,
        recommended_card_types=["counter", "bogus", "risk", 123],
        novelty_key="price_pressure:counterparty:x",
    )
    assert sig.urgency == 1.0
    assert sig.confidence == 0.0
    assert sig.actionability == 1.0
    assert sig.recommended_card_types == ["counter", "risk"]


def test_signal_novelty_key_none_when_silent():
    sig = NegotiationSignal(should_prompt=False, novelty_key="something")
    assert sig.novelty_key == "none"


# --- prompt builder: без keyword/триггера (sync) ---

def test_auto_cards_prompt_from_signal_does_not_contain_keyword_trigger():
    sig = NegotiationSignal(**_VALID)
    prompt = build_auto_cards_prompt_from_signal(
        "Подрядчик", sig, recent_dialog="[00:01] НЕ МЫ: дайте скидку",
        document_context="",
    )
    assert "keyword" not in prompt.lower()
    assert "Триггер" not in prompt
    assert "Контекстный переговорный сигнал" in prompt
    assert "concession_requested" in prompt
    assert "Оппонент давит на уступку" in prompt


def test_auto_cards_prompt_from_signal_accepts_dict():
    # должен работать и со словарём, не только с pydantic-объектом
    prompt = build_auto_cards_prompt_from_signal(
        "Подрядчик", dict(_VALID), recent_dialog="", document_context="",
    )
    assert "concession_requested" in prompt
    assert "keyword" not in prompt.lower()


def test_auto_cards_prompt_from_signal_speaker_block_and_safety():
    sig = NegotiationSignal(**_VALID)
    prompt = build_auto_cards_prompt_from_signal(
        "Подрядчик", sig, recent_dialog="", document_context="",
        speaker_context="Speaker SM_0: side=our_side, functional_role=engineer, confidence=0.9, source=manual_correction",
    )
    assert "Роли и стороны участников" in prompt
    assert "Speaker SM_0: side=our_side" in prompt
    # safety: подсказка нашей стороне, unknown → clarify/fixation
    assert "адресована нашей стороне" in prompt
    assert "speaker_side=unknown" in prompt
    # no legacy keyword wording
    assert "keyword" not in prompt.lower()
    assert "Триггер" not in prompt


def test_auto_cards_prompt_from_signal_unknown_roles_note():
    sig = NegotiationSignal(**_VALID)
    prompt = build_auto_cards_prompt_from_signal("Подрядчик", sig, recent_dialog="", document_context="")
    assert "Роли участников неизвестны" in prompt


def test_auto_cards_prompt_from_signal_audio_channel_zone_rule():
    sig = NegotiationSignal(**_VALID)
    prompt = build_auto_cards_prompt_from_signal(
        "Подрядчик", sig, recent_dialog="", document_context="",
        speaker_context="Speaker SM_5: side=our_side, source=audio_channel",
    )
    # правило про зону записи присутствует
    assert "audio_channel" in prompt
    assert "зона записи" in prompt
    # Этап 6: правило про низкую уверенность audio_channel
    assert "confidence < 0.75" in prompt
    # Этап 7: правило про низкую уверенность/unknown сторону
    assert "низкую уверенность по стороне или unknown" in prompt
    # без legacy keyword/Триггер
    assert "keyword" not in prompt.lower()
    assert "Триггер" not in prompt


# --- пороги (sync) ---

def test_signal_threshold_blocks_weak_signal():
    weak = NegotiationSignal(
        should_prompt=True, situation_type="price_pressure",
        confidence=0.4, actionability=0.4, urgency=0.3,
        novelty_key="price_pressure:counterparty:x",
    )
    assert passes_thresholds(weak, min_confidence=0.55,
                             min_actionability=0.55, min_urgency=0.45) is False

    strong = NegotiationSignal(
        should_prompt=True, situation_type="price_pressure",
        confidence=0.8, actionability=0.7, urgency=0.6,
        novelty_key="price_pressure:counterparty:x",
    )
    assert passes_thresholds(strong, min_confidence=0.55,
                             min_actionability=0.55, min_urgency=0.45) is True
