"""Unified prompt context assembly for 3 modes: reactive, tactical, strategic."""

import re
from typing import Callable, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from ..context.analyzer import ContextAnalyzer
    from ..context.document_loader import DocumentLoader
    from ..context.meeting_memory import MeetingMemory


class PromptContextBuilder:
    """Assembles context layers with different depth per prompt mode.

    reactive  — auto-hint: live window + relevant doc chunks (fast, minimal)
    tactical  — manual suggestion: live window + facts + docs + meeting meta
    strategic — strengthen: full memory context + docs + meeting meta
    """

    # Диаризация v1 — две стороны: «Мы» / «Не мы». ally/third_party — legacy fallback.
    _ROLE_LABELS = {
        "self": "МЫ", "opponent": "НЕ МЫ",
        "ally": "МЫ", "third_party": "НЕ МЫ",
    }
    _SPEAKER_RE = re.compile(r"^\[[\d:]+\]\s+(.+?):\s", re.MULTILINE)

    def __init__(
        self,
        meeting_memory: "MeetingMemory",
        document_loader: "DocumentLoader",
        context_analyzer: "ContextAnalyzer",
        committed_context_fn: Callable[[int], str],
        speaker_roles_fn: Callable[[], Dict[str, str]] | None = None,
        authoritative_context_fn: Callable[[bool], "str | None"] | None = None,
    ):
        self._memory = meeting_memory
        self._docs = document_loader
        self._analyzer = context_analyzer
        self._committed_fn = committed_context_fn  # _get_committed_context(minutes)
        self._roles_fn = speaker_roles_fn  # returns {display_name: side}
        # Этап 9.8: authoritative_context_fn(recent: bool) -> текст | None.
        # Не None (вкл. "") → встреча в multi-channel epoch: текст уже со сторонами,
        # имеет приоритет над live-памятью. None → single (поведение без изменений).
        self._authoritative_fn = authoritative_context_fn

    # ------------------------------------------------------------------
    # Public: 3 modes
    # ------------------------------------------------------------------

    def build_reactive(self, trigger_text: str) -> dict:
        """For auto-hints. Returns keys: recent_dialog, document_context."""
        recent = self._get_dialog()
        doc = self._get_doc_context_for_hint(trigger_text)
        return {"recent_dialog": recent, "document_context": doc}

    def build_tactical(
        self,
        topic: str = "",
        notes: str = "",
        negotiation_type: str = "",
        meeting_role: str = "",
        opponent_weaknesses: str = "",
    ) -> dict:
        """For manual suggestion. Returns keys matching build_tactical_hints_prompt."""
        recent = self._get_dialog_with_facts()
        doc = self._get_doc_context(recent)
        return {
            "recent_dialog": recent,
            "document_context": doc,
            "topic": topic,
            "notes": notes,
            "negotiation_type": negotiation_type,
            "meeting_role": meeting_role,
            "opponent_weaknesses": opponent_weaknesses,
        }

    def build_strategic(
        self,
        topic: str = "",
        notes: str = "",
        negotiation_type: str = "",
        meeting_role: str = "",
        opponent_weaknesses: str = "",
    ) -> dict:
        """For strengthen position. Returns keys matching build_strengthen_position_prompt."""
        transcript = self._get_full_transcript()
        doc = self._get_doc_context(transcript)
        return {
            "full_transcript": transcript,
            "document_context": doc,
            "topic": topic,
            "notes": notes,
            "negotiation_type": negotiation_type,
            "meeting_role": meeting_role,
            "opponent_weaknesses": opponent_weaknesses,
        }

    # ------------------------------------------------------------------
    # Internal: dialog layer
    # ------------------------------------------------------------------

    def _get_authoritative(self, recent: bool) -> "str | None":
        """Этап 9.8: авторитетный multi-channel транскрипт (или None для single)."""
        if self._authoritative_fn is None:
            return None
        try:
            text = self._authoritative_fn(recent)
        except Exception:
            return None
        # текст уже со сторонами «МЫ/НЕ МЫ»; не прогоняем через _annotate_roles
        return text if text else None

    def _get_dialog(self) -> str:
        """Authoritative (multi epoch) → live window → committed fallback → analyzer."""
        auth = self._get_authoritative(recent=True)
        if auth is not None:
            return auth
        text = self._memory.get_live_window()
        if not text:
            text = self._committed_fn(5)
        if not text:
            text = self._analyzer.get_context_by_time(5)
        return self._annotate_roles(text)

    def _get_dialog_with_facts(self) -> str:
        """Dialog + pinned facts prepended (for tactical mode)."""
        dialog = self._get_dialog()
        facts = self._memory.get_pinned_facts_text()
        if facts and dialog:
            return f"КЛЮЧЕВЫЕ ФАКТЫ:\n{facts}\n\nПОСЛЕДНИЕ РЕПЛИКИ:\n{dialog}"
        return dialog

    def _get_full_transcript(self) -> str:
        """Authoritative (multi epoch) → full memory → committed fallback → analyzer."""
        auth = self._get_authoritative(recent=False)
        if auth is not None:
            return auth
        text = self._memory.build_combined_context()
        if not text:
            text = self._committed_fn(5)
        if not text:
            text = self._analyzer.get_context_by_time(5)
        return self._annotate_roles(text)

    # ------------------------------------------------------------------
    # Internal: document layer
    # ------------------------------------------------------------------

    def _get_doc_context_for_hint(self, query: str) -> str:
        """Retrieve relevant chunks; fallback to get_context_for_prompt."""
        doc = self._docs.retrieve_relevant(query)
        if doc:
            return doc
        if self._docs.has_context():
            return self._docs.get_context_for_prompt()
        return ""

    def _get_doc_context(self, query: str) -> str:
        """Retrieve relevant chunks; fallback to get_document_context."""
        doc = self._docs.retrieve_relevant(query)
        if doc:
            return doc
        return self._docs.get_document_context()

    # ------------------------------------------------------------------
    # Internal: speaker role annotation
    # ------------------------------------------------------------------

    def _annotate_roles(self, text: str) -> str:
        """Inject [МЫ]/[ОППОНЕНТ] tags into formatted dialog lines."""
        if not self._roles_fn or not text:
            return text
        roles = self._roles_fn()
        if not roles:
            return text

        def _replace(m: re.Match) -> str:
            speaker = m.group(1)
            tag = self._ROLE_LABELS.get(roles.get(speaker, ""), "")
            if tag:
                return m.group(0).replace(f"{speaker}:", f"{speaker} [{tag}]:")
            return m.group(0)

        return self._SPEAKER_RE.sub(_replace, text)
