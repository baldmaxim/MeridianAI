"""Unit-тесты pure-логики Context Pack (Этап 6) — без БД и LLM."""

from app.core.llm.context_pack import (
    ContextPack, ContextBlock, approx_token_count, truncate_text,
    apply_block_budget, apply_pack_budget,
)


def test_truncate_keeps_short_text():
    text, was = truncate_text("короткий текст", 100)
    assert text == "короткий текст"
    assert was is False


def test_truncate_long_text_adds_marker():
    text, was = truncate_text("a" * 500, 100)
    assert was is True
    assert len(text) <= 100
    assert "[часть сведений опущена]" in text


def test_truncate_tiny_budget_hard_cut():
    text, was = truncate_text("a" * 50, 5)
    assert was is True
    assert text == "aaaaa"


def test_approx_token_count():
    assert approx_token_count("") == 0
    assert approx_token_count("abcd") == 1
    assert approx_token_count("a" * 400) == 100


def test_apply_block_budget_sets_truncated():
    b = ContextBlock(kind="document", title="Документы", content="x" * 1000, max_chars=100)
    out = apply_block_budget(b)
    assert out.truncated is True
    assert len(out.content) <= 100
    assert b.truncated is False  # исходный блок не мутирован


def test_combined_documents_order():
    pack = ContextPack(
        mode="manual",
        blocks=[
            ContextBlock(kind="rag", title="RAG", content="RAG-блок"),
            ContextBlock(kind="document", title="Док", content="Документ-блок"),
        ],
    )
    combined = pack.combined_documents_text()
    assert combined.index("Документ-блок") < combined.index("RAG-блок")


def test_apply_pack_budget_keeps_high_priority():
    pack = ContextPack(
        mode="auto",
        max_chars=120,
        blocks=[
            ContextBlock(kind="meeting_context", title="Встреча", content="M" * 100, priority=10),
            ContextBlock(kind="previous_meeting", title="Прошлые", content="P" * 100, priority=70),
        ],
    )
    apply_pack_budget(pack)
    mc = next(b for b in pack.blocks if b.kind == "meeting_context")
    pm = next(b for b in pack.blocks if b.kind == "previous_meeting")
    assert mc.enabled is True
    assert len(mc.content) == 100  # высокий приоритет сохранён целиком
    # низкоприоритетный блок обрезан или выключен
    assert (not pm.enabled) or (pm.truncated and len(pm.content) < 100)
    assert pack.truncated is True


def test_to_preview_hides_full_content():
    long_content = "слово " * 1000
    pack = ContextPack(
        mode="manual", total_chars=len(long_content),
        blocks=[ContextBlock(kind="document", title="Док", content=long_content, source_count=3)],
    )
    preview = pack.to_preview(preview_chars_per_block=100)
    block = preview["blocks"][0]
    assert block["chars"] == len(long_content)
    assert len(block["content_preview"]) <= 101  # обрезано + «…»
    assert block["source_count"] == 3
    assert preview["estimated_tokens"] >= 1
