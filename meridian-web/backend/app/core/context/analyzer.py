"""Conversation context analysis.

Works with both legacy TranscriptSegment (Deepgram/Gemini)
and new CommittedSegment (ElevenLabs).
"""

from collections import deque
from typing import List, Dict, Optional, Union
from datetime import datetime, timedelta
from ..transcription.models import TranscriptSegment, CommittedSegment


class ContextAnalyzer:
    """Analyzes conversation history and context."""

    def __init__(self, history_window: int = 50, context_window: int = 3,
                 trigger_keywords: Optional[List[str]] = None):
        self.history_window = history_window
        self.context_window = context_window
        self.trigger_keywords = trigger_keywords or [
            "цена", "срок", "гарантия", "штраф",
            "договор", "обсуждаем", "ваше мнение",
            "смета", "аванс", "материалы"
        ]
        self.conversation_history = deque(maxlen=history_window)
        self.full_history: List[TranscriptSegment] = []

    def add_segment(self, segment: TranscriptSegment):
        """Add transcript segment to history (legacy: Deepgram/Gemini)."""
        self.conversation_history.append(segment)
        self.full_history.append(segment)

    def replace_history(self, segments: List[TranscriptSegment]):
        """Replace all history (used by batch finalization)."""
        self.conversation_history.clear()
        self.full_history.clear()
        for seg in segments:
            self.conversation_history.append(seg)
            self.full_history.append(seg)

    def get_recent_context(self, window: Optional[int] = None) -> str:
        """Get recent conversation context."""
        window = window or self.context_window
        recent = list(self.conversation_history)[-window:]

        lines = []
        for seg in recent:
            time_str = seg.timestamp.strftime('%H:%M:%S')
            lines.append(f"[{time_str}] {seg.speaker}: {seg.text}")

        return "\n".join(lines)

    def get_context_by_time(self, minutes: int = 5) -> str:
        """Get conversation context from the last N minutes."""
        if not self.conversation_history:
            return ""

        now = datetime.now()
        cutoff_time = now - timedelta(minutes=minutes)

        recent_segments = [
            seg for seg in self.conversation_history
            if seg.timestamp >= cutoff_time
        ]

        lines = []
        for seg in recent_segments:
            time_str = seg.timestamp.strftime('%H:%M:%S')
            lines.append(f"[{time_str}] {seg.speaker}: {seg.text}")

        return "\n".join(lines)

    def detect_trigger_keywords(self, text: str) -> List[str]:
        """Detect trigger keywords in text."""
        text_lower = text.lower()
        found = [
            kw for kw in self.trigger_keywords
            if kw in text_lower
        ]
        return found

    def get_conversation_summary(self) -> Dict:
        """Get conversation statistics."""
        history = list(self.conversation_history)

        if not history:
            return {
                "message_count": 0,
                "speakers": [],
                "duration": 0
            }

        speakers = list(set(seg.speaker for seg in history))
        start_time = history[0].timestamp
        end_time = history[-1].timestamp
        duration = (end_time - start_time).total_seconds()

        return {
            "message_count": len(history),
            "speakers": speakers,
            "duration": duration,
            "latest_topics": self._extract_topics(history[-3:])
        }

    def _extract_topics(self, segments: List[TranscriptSegment]) -> List[str]:
        """Extract topics from segments."""
        topics = []
        for seg in segments:
            for keyword in self.trigger_keywords:
                if keyword in seg.text.lower():
                    topics.append(keyword)
        return list(set(topics))
