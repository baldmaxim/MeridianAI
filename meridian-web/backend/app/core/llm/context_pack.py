"""Context Pack (Этап 6): единая pure-модель сборки prompt-контекста для LLM.

Все источники контекста (документы, RAG, база знаний, прошлые встречи, реплики,
контекст встречи) представляются единообразными блоками с типом, заголовком, лимитом,
статусом и признаком обрезки. Бюджеты применяются на двух уровнях: per-block и per-pack.

ВАЖНО: модуль чисто-логический — без FastAPI/SQLAlchemy/SessionManager. Сборка строк
из БД/провайдеров живёт в services/context_pack.py. Покрыт unit-тестами.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal, Any

ContextPackMode = Literal["auto", "manual", "strengthen", "preview"]

ContextBlockKind = Literal[
    "meeting_context",
    "recent_dialog",
    "full_transcript",
    "document",
    "rag",
    "letters",
    "knowledge",
    "previous_meeting",
    "manual",
    "system",
]

_TRUNCATE_MARKER = "\n[часть сведений опущена]"


def approx_token_count(text: str) -> int:
    """Грубая оценка токенов: ~4 символа на токен."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def truncate_text(text: str, max_chars: int, marker: str = _TRUNCATE_MARKER) -> tuple[str, bool]:
    """Обрезать text до max_chars. Возвращает (text, truncated)."""
    if not text:
        return text or "", False
    if len(text) <= max_chars:
        return text, False
    if max_chars <= len(marker):
        return text[:max_chars], True
    return text[: max_chars - len(marker)].rstrip() + marker, True


@dataclass
class ContextBlock:
    kind: ContextBlockKind
    title: str
    content: str = ""
    priority: int = 100
    enabled: bool = True
    reason: str | None = None
    source_count: int = 0
    max_chars: int | None = None
    truncated: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextPack:
    mode: ContextPackMode
    query_text: str = ""
    blocks: list[ContextBlock] = field(default_factory=list)
    total_chars: int = 0
    max_chars: int | None = None
    truncated: bool = False

    def _find(self, kind: ContextBlockKind) -> ContextBlock | None:
        for b in self.blocks:
            if b.kind == kind:
                return b
        return None

    def text_for(self, kind: ContextBlockKind) -> str:
        """Контент включённого непустого блока данного типа (или '')."""
        b = self._find(kind)
        if b and b.enabled and b.content:
            return b.content
        return ""

    def combined_documents_text(self) -> str:
        """document + rag в один слот (для текущих prompt-функций), каждый со своим заголовком."""
        parts: list[str] = []
        for kind in ("document", "rag"):
            b = self._find(kind)
            if b and b.enabled and b.content:
                parts.append(b.content)
        return "\n\n".join(parts)

    def enabled_blocks(self) -> list[ContextBlock]:
        return [b for b in self.blocks if b.enabled and b.content]

    def to_preview(self, preview_chars_per_block: int = 1200) -> dict:
        blocks_out: list[dict] = []
        for b in self.blocks:
            content = b.content or ""
            preview = content[:preview_chars_per_block]
            if len(content) > preview_chars_per_block:
                preview = preview.rstrip() + "…"
            blocks_out.append({
                "kind": b.kind,
                "title": b.title,
                "enabled": b.enabled,
                "reason": b.reason,
                "chars": len(content),
                "estimated_tokens": approx_token_count(content),
                "source_count": b.source_count,
                "max_chars": b.max_chars,
                "truncated": b.truncated,
                "content_preview": preview if b.enabled else "",
                "meta": b.meta,
            })
        return {
            "mode": self.mode,
            "query_text": self.query_text,
            "total_chars": self.total_chars,
            "estimated_tokens": max(1, self.total_chars // 4) if self.total_chars else 0,
            "max_chars": self.max_chars,
            "truncated": self.truncated,
            "blocks": blocks_out,
        }


def apply_block_budget(block: ContextBlock) -> ContextBlock:
    """Обрезать контент блока по его max_chars (новый объект, без мутации исходного)."""
    if block.max_chars is None or not block.content:
        return block
    content, was = truncate_text(block.content, block.max_chars)
    if not was:
        return block
    return replace(block, content=content, truncated=True)


def apply_pack_budget(pack: ContextPack) -> ContextPack:
    """Сначала per-block бюджет, затем общий: высокий приоритет (меньший priority) сохраняется,
    низкоприоритетные блоки обрезаются/выключаются. enabled=False не входит в total_chars."""
    pack.blocks = [apply_block_budget(b) for b in pack.blocks]

    if pack.max_chars is None:
        pack.total_chars = sum(len(b.content) for b in pack.blocks if b.enabled and b.content)
        pack.truncated = any(b.truncated for b in pack.blocks)
        return pack

    order = sorted(
        [b for b in pack.blocks if b.enabled and b.content],
        key=lambda b: b.priority,
    )
    used = 0
    pack_truncated = False
    for b in order:
        remaining = pack.max_chars - used
        if remaining <= 0:
            b.enabled = False
            b.reason = b.reason or "Опущено из-за лимита контекста"
            pack_truncated = True
            continue
        if len(b.content) > remaining:
            content, _ = truncate_text(b.content, remaining)
            b.content = content
            b.truncated = True
            pack_truncated = True
        used += len(b.content)

    pack.total_chars = sum(len(b.content) for b in pack.blocks if b.enabled and b.content)
    pack.truncated = pack_truncated or any(b.truncated for b in pack.blocks)
    return pack
