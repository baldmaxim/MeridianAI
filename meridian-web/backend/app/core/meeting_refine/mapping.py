"""Чистые функции уточнения: сопоставление голосов ElevenLabs с метками черновика, сторона по громкости каналов."""

import math
import re
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

# Доля речи голоса ElevenLabs, которую должна покрывать метка черновика, чтобы считать их одним человеком.
MIN_MATCH_SHARE = 0.3
# Окно, по которому считается громкость каналов (сек).
ENERGY_WINDOW_SEC = 0.1

_VOICE_RE = re.compile(r"^Голос (\d+)$")


@dataclass(frozen=True)
class Span:
    """Отрезок речи на временной шкале аудио: кто (голос ElevenLabs или метка черновика) и когда."""

    speaker: str
    start: float
    end: float


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def next_voice_number(labels: list[str]) -> int:
    """Следующий свободный номер «Голос N» среди меток черновика."""
    numbers = [int(m.group(1)) for label in labels if (m := _VOICE_RE.match(label or ""))]
    return max(numbers, default=0) + 1


def map_speakers(
    refined: list[Span], draft: list[Span], *, min_share: float = MIN_MATCH_SHARE,
) -> dict[str, str]:
    """{голос ElevenLabs: метка спикера встречи}.

    Для каждой пары (голос, метка черновика) суммируется пересечение по времени. Пары берутся жадно
    по убыванию пересечения, один к одному; пара принимается, только если покрывает не меньше
    min_share всей речи этого голоса. Не сопоставленные голоса получают новые «Голос K»
    (K — после максимального существующего номера), в порядке первого появления в записи.
    """
    total: dict[str, float] = defaultdict(float)
    first_seen: dict[str, float] = {}
    for s in refined:
        total[s.speaker] += max(0.0, s.end - s.start)
        first_seen[s.speaker] = min(first_seen.get(s.speaker, s.start), s.start)

    draft_sorted = sorted(draft, key=lambda d: d.start)
    starts = [d.start for d in draft_sorted]
    max_len = max((d.end - d.start for d in draft_sorted), default=0.0)

    overlaps: dict[tuple[str, str], float] = defaultdict(float)
    for r in refined:
        lo = bisect_left(starts, r.start - max_len)
        for d in draft_sorted[lo:]:
            if d.start >= r.end:
                break
            ov = _overlap(r.start, r.end, d.start, d.end)
            if ov > 0:
                overlaps[(r.speaker, d.speaker)] += ov

    mapping: dict[str, str] = {}
    used_labels: set[str] = set()
    for (voice, label), ov in sorted(overlaps.items(), key=lambda kv: (-kv[1], kv[0])):
        if voice in mapping or label in used_labels:
            continue
        if ov >= min_share * total[voice]:
            mapping[voice] = label
            used_labels.add(label)

    next_n = next_voice_number([d.speaker for d in draft])
    for voice in sorted((v for v in total if v not in mapping), key=lambda v: (first_seen[v], v)):
        mapping[voice] = f"Голос {next_n}"
        next_n += 1
    return mapping


# ── сторона по громкости каналов ───────────────────────────────────────────


def window_energy(samples: np.ndarray, window_frames: int) -> np.ndarray:
    """Средний квадрат амплитуды по окнам (последнее неполное окно усредняется по своей длине)."""
    if window_frames <= 0 or samples.size == 0:
        return np.zeros(0, dtype=np.float64)
    x = samples.astype(np.float64)
    full = x.size // window_frames
    parts = []
    if full:
        parts.append((x[: full * window_frames].reshape(full, window_frames) ** 2).mean(axis=1))
    tail = x[full * window_frames:]
    if tail.size:
        parts.append(np.array([(tail ** 2).mean()]))
    return np.concatenate(parts)


def dominant_side(
    mic: np.ndarray, system: np.ndarray, start: float, end: float,
    *, window: float = ENERGY_WINDOW_SEC,
) -> str | None:
    """Сторона реплики по громкости каналов на [start, end]: микрофон — «self», звук встречи — «opponent».

    mic/system — энергия по окнам (window_energy). None — тишина в обоих каналах, равенство
    или реплика вне записи.
    """
    i0 = max(0, int(math.floor(start / window)))
    i1 = max(i0 + 1, int(math.ceil(end / window)))
    mic_part, sys_part = mic[i0:i1], system[i0:i1]
    if mic_part.size == 0 and sys_part.size == 0:
        return None
    mic_e = float(mic_part.mean()) if mic_part.size else 0.0
    sys_e = float(sys_part.mean()) if sys_part.size else 0.0
    if mic_e <= 0.0 and sys_e <= 0.0:
        return None
    if mic_e == sys_e:
        return None
    return "self" if mic_e > sys_e else "opponent"
