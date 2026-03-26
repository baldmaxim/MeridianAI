"""Transcription formatting and protocol parsing utilities."""

import re
import json
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionSegment:
    speaker: str
    start: float
    end: float
    text: str


def format_timestamp(seconds: float, include_hours: bool = True) -> str:
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if include_hours or h > 0:
        return f"[{h:02d}:{m:02d}:{s:02d}]"
    return f"[{m:02d}:{s:02d}]"


def group_words_by_speaker(words: List[Dict[str, Any]]) -> List[TranscriptionSegment]:
    if not words:
        return []

    segments = []
    current_speaker: Optional[str] = None
    current_start: float = 0.0
    current_end: float = 0.0
    current_texts: List[str] = []

    for word in words:
        speaker = word.get("speaker_id", word.get("speaker", "Speaker_1"))
        start = word.get("start", 0)
        end = word.get("end", 0)
        text = word.get("text", "").strip()

        if speaker != current_speaker:
            if current_texts and current_speaker:
                segments.append(TranscriptionSegment(
                    speaker=current_speaker,
                    start=current_start,
                    end=current_end,
                    text=" ".join(current_texts),
                ))
            current_speaker = speaker
            current_start = start
            current_texts = []

        if text:
            current_texts.append(text)
        current_end = end

    if current_texts and current_speaker:
        segments.append(TranscriptionSegment(
            speaker=current_speaker,
            start=current_start,
            end=current_end,
            text=" ".join(current_texts),
        ))

    return segments


def _ts(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def format_utterances(transcription_data: Dict[str, Any]) -> str:
    if not transcription_data:
        return ""

    if "words" in transcription_data and transcription_data["words"]:
        segments = group_words_by_speaker(transcription_data["words"])
        return "\n\n".join(
            f"[{_ts(seg.start)}\u2013{_ts(seg.end)}] {seg.speaker}: {seg.text}"
            for seg in segments
        )

    if "text" in transcription_data:
        return f"[00:00\u201300:00] Speaker_1: {transcription_data['text']}"

    return ""


def format_transcription_txt(transcription_data: Dict[str, Any]) -> str:
    if "words" in transcription_data and transcription_data["words"]:
        segments = group_words_by_speaker(transcription_data["words"])
        return "\n\n".join(
            f"{format_timestamp(seg.start)} {seg.speaker}: {seg.text}"
            for seg in segments
        )
    return transcription_data.get("text", "")


def split_protocol_output(text: str) -> Tuple[str, Optional[dict]]:
    pattern = r'```json\s*\n(.*?)```'
    match = re.search(pattern, text, re.DOTALL)

    if not match:
        return text, None

    json_str = match.group(1).strip()
    markdown = text[:match.start()].rstrip() + "\n" + text[match.end():].lstrip()
    markdown = markdown.strip()

    try:
        parsed = json.loads(json_str)
        return markdown, parsed
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse protocol JSON block: {e}")
        return text, None
