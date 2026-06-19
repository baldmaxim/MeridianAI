"""Тесты RAG-клиента писем PayHub: чистая логика (RRF, диверсификация, формат блока).

Без сети/БД — проверяем fusion.rrf_merge, fusion.diversify и context.build_rag_context.
"""

from app.core.rag_letters.context import RagHit, build_rag_context
from app.core.rag_letters.fusion import RRF_K, diversify, rrf_merge


def _hit(chunk_id, letter_id, **kw):
    base = dict(
        subject="Тема", reg_number=None, number=None, customer_number=None,
        direction="incoming", letter_date="2026-01-01", project_id=1,
        page_from=1, page_to=2, text="текст", score=0.0,
    )
    base.update(kw)
    return RagHit(chunk_id=chunk_id, letter_id=letter_id, **base)


# ── rrf_merge ─────────────────────────────────────────────────────────────────

def test_rrf_merge_single_list_ranks():
    fused = rrf_merge([["a", "b", "c"]])
    assert fused["a"] == 1 / (RRF_K + 1)
    assert fused["b"] == 1 / (RRF_K + 2)
    assert fused["c"] == 1 / (RRF_K + 3)
    # порядок убывания по позиции
    assert fused["a"] > fused["b"] > fused["c"]


def test_rrf_merge_sums_across_lists():
    # 'b' в обоих списках → вклады суммируются и 'b' становится топом
    fused = rrf_merge([["a", "b"], ["b", "c"]])
    assert fused["b"] == 1 / (RRF_K + 2) + 1 / (RRF_K + 1)
    assert fused["a"] == 1 / (RRF_K + 1)
    assert fused["c"] == 1 / (RRF_K + 2)
    top = max(fused, key=fused.get)
    assert top == "b"


def test_rrf_merge_custom_k():
    fused = rrf_merge([["x"]], k_const=10)
    assert fused["x"] == 1 / (10 + 1)


def test_rrf_merge_empty():
    assert rrf_merge([]) == {}
    assert rrf_merge([[], []]) == {}


# ── diversify ─────────────────────────────────────────────────────────────────

def test_diversify_caps_two_per_letter():
    hits = [
        _hit("c1", "L1"), _hit("c2", "L1"), _hit("c3", "L1"),  # 3-й из L1 отсекается
        _hit("c4", "L2"), _hit("c5", "L2"),
    ]
    out = diversify(hits, per_letter=2)
    ids = [h.chunk_id for h in out]
    assert ids == ["c1", "c2", "c4", "c5"]


def test_diversify_preserves_order():
    hits = [_hit("c1", "L1"), _hit("c2", "L2"), _hit("c3", "L1")]
    out = diversify(hits, per_letter=2)
    assert [h.chunk_id for h in out] == ["c1", "c2", "c3"]


def test_diversify_none_letter_id_not_grouped():
    hits = [_hit("c1", None), _hit("c2", None), _hit("c3", None)]
    out = diversify(hits, per_letter=2)
    assert len(out) == 3  # None считаются уникальными — не отсекаются


# ── build_rag_context ─────────────────────────────────────────────────────────

def test_build_rag_context_empty():
    assert build_rag_context([]) == ""


def test_build_rag_context_format():
    hits = [
        _hit("c1", "L1", direction="incoming", letter_date="2026-02-10",
             reg_number="Вх-15", subject="Поставка", page_from=3, page_to=4, text="Тело письма"),
        _hit("c2", "L2", direction="outgoing", letter_date="2026-02-11",
             reg_number=None, number="Исх-7", subject="Ответ", page_from=1, page_to=1, text="Второе"),
    ]
    out = build_rag_context(hits)
    assert "[Письмо 1] входящее от 2026-02-10" in out
    assert "№ Вх-15 · тема: Поставка · стр. 3-4" in out
    assert "Тело письма" in out
    assert "[Письмо 2] исходящее от 2026-02-11" in out
    assert "№ Исх-7 · тема: Ответ · стр. 1-1" in out
    assert out.count("---") == 2  # разделитель после каждого письма


def test_build_rag_context_number_fallback():
    # reg_number отсутствует → number → customer_number
    h = _hit("c1", "L1", reg_number=None, number=None, customer_number="Зак-99")
    assert "№ Зак-99" in build_rag_context([h])
    h2 = _hit("c2", "L2", reg_number=None, number=None, customer_number=None)
    assert "№ —" in build_rag_context([h2])


def test_build_rag_context_no_pages():
    h = _hit("c1", "L1", page_from=None, page_to=None)
    out = build_rag_context([h])
    assert "стр." not in out
