"""Turn assembler — merges consecutive same-speaker segments into utterance turns."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple
from uuid import uuid4


MAX_GAP_SEC = 2.0


@dataclass
class UtteranceTurn:
    """One speaker's contiguous utterance, assembled from one or more segments."""

    turn_id: str = field(default_factory=lambda: uuid4().hex[:12])
    speaker: str = ""
    text: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    wall_clock: datetime = field(default_factory=datetime.now)
    segment_count: int = 1

    def to_wire(self) -> dict:
        return {
            "turn_id": self.turn_id,
            "speaker": self.speaker,
            "text": self.text,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "timestamp": self.wall_clock.strftime("%H:%M:%S"),
            "segment_count": self.segment_count,
        }


class TurnAssembler:
    """Incrementally merges segments into utterance turns.

    Rule: if next segment has the same speaker and the gap
    (segment.start_time - current_turn.end_time) < MAX_GAP_SEC,
    extend the current turn. Otherwise start a new turn.
    """

    def __init__(self, max_gap: float = MAX_GAP_SEC):
        self._max_gap = max_gap
        self._turns: List[UtteranceTurn] = []
        self._open: Optional[UtteranceTurn] = None

    def push(
        self,
        speaker: str,
        text: str,
        start_time: float,
        end_time: float,
        wall_clock: datetime,
    ) -> Tuple[UtteranceTurn, bool]:
        """Feed a new final segment. Returns (turn, is_new_turn)."""
        if (
            self._open is not None
            and self._open.speaker == speaker
            and (start_time - self._open.end_time) < self._max_gap
        ):
            # Extend current turn
            self._open.text = f"{self._open.text} {text}".strip()
            self._open.end_time = end_time
            self._open.segment_count += 1
            return self._open, False

        # Close previous open turn (already in _turns) and start new
        turn = UtteranceTurn(
            speaker=speaker,
            text=text,
            start_time=start_time,
            end_time=end_time,
            wall_clock=wall_clock,
        )
        self._turns.append(turn)
        self._open = turn
        return turn, True

    def rebuild(
        self,
        items: List[Tuple[str, str, float, float, datetime]],
    ) -> List[UtteranceTurn]:
        """Rebuild turns from scratch (e.g. after batch finalization).

        Each item is (speaker, text, start_time, end_time, wall_clock).
        """
        self.reset()
        for speaker, text, start_time, end_time, wall_clock in items:
            self.push(speaker, text, start_time, end_time, wall_clock)
        return list(self._turns)

    @property
    def turns(self) -> List[UtteranceTurn]:
        return self._turns

    def reset(self):
        self._turns.clear()
        self._open = None
