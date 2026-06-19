"""Deepgram prerecorded multichannel batch adapter + pure parser (Этап 9.5).

POST WAV напрямую (Content-Type: audio/wav), multichannel=true → отдельный transcript на
канал. API key только в Authorization header. Audio/response body и ключ НЕ логируются.
Raw response целиком не хранится — наружу только нормализованный MultiChannelBatchResult.
"""

import hashlib
import json
import math
import struct
import urllib.parse

import httpx

from .multi_channel_batch_stt import (
    ERR_PROVIDER_AUTH,
    ERR_PROVIDER_BAD_RESPONSE,
    ERR_PROVIDER_RATE_LIMIT,
    ERR_PROVIDER_RESPONSE_TOO_LARGE,
    ERR_PROVIDER_TIMEOUT,
    ERR_PROVIDER_UNAVAILABLE,
    MultiChannelBatchChannel,
    MultiChannelBatchResult,
    MultiChannelBatchSegment,
    MultiChannelBatchSttError,
    MultiChannelBatchWord,
)

_GAP_SEC = 1.0
_MAX_SEG_SEC = 20.0
_TERMINAL = ".?!…"


# --- безопасные числа (не доверяем JSON) ---

def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    return None


def _ts(v) -> float | None:
    f = _num(v)
    if f is None or f < 0:
        return None
    return f


def _conf(v) -> float | None:
    f = _num(v)
    if f is None:
        return None
    return max(0.0, min(1.0, f))


def _text(v) -> str:
    return v if isinstance(v, str) else ""


def _seg_id(channel_index: int, start: float, end: float, text: str) -> str:
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"batch:{channel_index}:{int(round(start * 1000))}:{int(round(end * 1000))}:{h}"


def _side_label(side: str | None) -> str | None:
    if side == "self":
        return "МЫ"
    if side == "opponent":
        return "НЕ МЫ"
    return None


def _parse_words(raw_words, channel_index: int) -> list[MultiChannelBatchWord]:
    out: list[MultiChannelBatchWord] = []
    if not isinstance(raw_words, list):
        return out
    for w in raw_words:
        if not isinstance(w, dict):
            continue
        start = _ts(w.get("start"))
        end = _ts(w.get("end"))
        if start is None or end is None or end < start:
            continue
        text = _text(w.get("punctuated_word")) or _text(w.get("word"))
        if not text:
            continue
        out.append(MultiChannelBatchWord(
            text=text, start=start, end=end, channel_index=channel_index,
            confidence=_conf(w.get("confidence")),
            punctuated_word=_text(w.get("punctuated_word")) or None,
        ))
    return out


def _group_words_into_segments(words, *, channel_index, track_id, label, side):
    segments = []
    cur: list[MultiChannelBatchWord] = []

    def flush():
        if not cur:
            return
        start = cur[0].start
        end = cur[-1].end
        text = " ".join(w.text for w in cur).strip()
        confs = [w.confidence for w in cur if w.confidence is not None]
        conf = round(sum(confs) / len(confs), 4) if confs else None
        segments.append(MultiChannelBatchSegment(
            segment_id=_seg_id(channel_index, start, end, text),
            channel_index=channel_index, track_id=track_id, channel_label=label, side=side,
            text=text, start=start, end=end, confidence=conf, words=tuple(cur),
        ))

    for w in words:
        if cur:
            prev = cur[-1]
            gap = w.start - prev.end
            sentence_end = bool(prev.text) and prev.text[-1] in _TERMINAL
            too_long = (w.end - cur[0].start) > _MAX_SEG_SEC
            if gap > _GAP_SEC or sentence_end or too_long:
                flush()
                cur = []
        cur.append(w)
    flush()
    return segments


def parse_deepgram_multichannel_response(
    *,
    data: dict,
    expected_channels: int,
    channel_mapping: list,
    model: str,
    language: str,
    sample_rate: int = 16000,
) -> MultiChannelBatchResult:
    """Чистый парсер ответа Deepgram multichannel → MultiChannelBatchResult.

    JSON не доверяем: bool≠number, NaN/inf игнорируем, ts>=0, end>=start, confidence 0..1,
    неизвестные поля игнорируем. Channel index 0-based. Track mapping ТОЛЬКО из request order.
    """
    results = data.get("results") if isinstance(data, dict) else None
    results = results if isinstance(results, dict) else {}
    channels_data = results.get("channels")
    channels_data = channels_data if isinstance(channels_data, list) else []
    metadata = data.get("metadata") if isinstance(data, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}

    # утверждения по каналам (если provider их вернул)
    utt_by_channel: dict[int, list] = {}
    raw_utts = results.get("utterances")
    if isinstance(raw_utts, list):
        for u in raw_utts:
            if not isinstance(u, dict):
                continue
            ci = u.get("channel")
            if isinstance(ci, bool) or not isinstance(ci, int):
                continue
            utt_by_channel.setdefault(ci, []).append(u)

    warnings: list[str] = []
    provider_channels = len(channels_data)
    if provider_channels < expected_channels:
        warnings.append(f"Провайдер вернул меньше каналов ({provider_channels} < {expected_channels})")
    elif provider_channels > expected_channels:
        warnings.append(f"Провайдер вернул лишние каналы ({provider_channels} > {expected_channels}), игнорируем")

    channels: list[MultiChannelBatchChannel] = []
    all_segments: list[MultiChannelBatchSegment] = []

    for ci in range(expected_channels):
        m = channel_mapping[ci] if ci < len(channel_mapping) else {}
        track_id = str(m.get("track_id", f"ch{ci}"))
        label = str(m.get("channel_label", f"Канал {ci + 1}"))
        side = m.get("side")
        source_kind = str(m.get("source_kind", ""))
        generation = int(m.get("generation", 0) or 0)

        transcript = ""
        words: list[MultiChannelBatchWord] = []
        alt_conf = None
        if ci < len(channels_data) and isinstance(channels_data[ci], dict):
            alts = channels_data[ci].get("alternatives")
            if isinstance(alts, list) and alts and isinstance(alts[0], dict):
                alt = alts[0]
                transcript = _text(alt.get("transcript")).strip()
                alt_conf = _conf(alt.get("confidence"))
                words = _parse_words(alt.get("words"), ci)

        # segments: utterances → grouping → single
        segments: list[MultiChannelBatchSegment] = []
        ch_warn: list[str] = []
        utts = utt_by_channel.get(ci, [])
        if utts:
            for u in utts:
                start = _ts(u.get("start"))
                end = _ts(u.get("end"))
                if start is None or end is None or end < start:
                    continue
                u_text = _text(u.get("transcript")).strip()
                if not u_text:
                    continue
                u_words = _parse_words(u.get("words"), ci)
                segments.append(MultiChannelBatchSegment(
                    segment_id=_seg_id(ci, start, end, u_text),
                    channel_index=ci, track_id=track_id, channel_label=label, side=side,
                    text=u_text, start=start, end=end, confidence=_conf(u.get("confidence")),
                    words=tuple(u_words),
                ))
        elif words:
            segments = _group_words_into_segments(
                words, channel_index=ci, track_id=track_id, label=label, side=side)
        elif transcript:
            segments = [MultiChannelBatchSegment(
                segment_id=_seg_id(ci, 0.0, 0.0, transcript),
                channel_index=ci, track_id=track_id, channel_label=label, side=side,
                text=transcript, start=0.0, end=0.0, confidence=alt_conf, words=(),
            )]

        if ci >= provider_channels:
            ch_warn.append("Канал не распознан провайдером (тишина/нет данных)")

        # average confidence
        if alt_conf is not None:
            avg_conf = alt_conf
        else:
            wc = [w.confidence for w in words if w.confidence is not None]
            avg_conf = round(sum(wc) / len(wc), 4) if wc else None

        channels.append(MultiChannelBatchChannel(
            channel_index=ci, track_id=track_id, channel_label=label, side=side,
            source_kind=source_kind, generation=generation, transcript=transcript,
            words_count=len(words), segments_count=len(segments), average_confidence=avg_conf,
            segments=tuple(segments), warnings=tuple(ch_warn),
        ))
        all_segments.extend(segments)

    chronological = tuple(sorted(
        all_segments, key=lambda s: (s.start, s.end, s.channel_index, s.segment_id)))

    combined_lines = []
    for s in chronological:
        lbl = _side_label(s.side)
        prefix = f"[{lbl} | Канал {s.channel_index + 1}]" if lbl else f"[Канал {s.channel_index + 1}]"
        combined_lines.append(f"{prefix} {s.text}")
    combined_text = "\n".join(combined_lines)

    duration_s = _ts(metadata.get("duration")) or 0.0  # _ts: не доверяем, ts>=0
    provider_meta = {
        "request_id": metadata.get("request_id") if isinstance(metadata.get("request_id"), str) else None,
        "model": model,
        "detected_language": metadata.get("language") if isinstance(metadata.get("language"), str) else language,
        "provider_duration_s": duration_s,
        "channels_returned": provider_channels,
    }

    return MultiChannelBatchResult(
        provider="deepgram", model=model, language=language,
        provider_request_id=provider_meta["request_id"],
        sample_rate=sample_rate, channels_count=expected_channels,
        duration_ms=int(round(duration_s * 1000)),
        channels=tuple(channels), chronological_segments=chronological,
        combined_text=combined_text, warnings=tuple(warnings), provider_meta=provider_meta,
    )


def _sample_rate_from_wav(wav_bytes: bytes) -> int:
    if len(wav_bytes) >= 28 and wav_bytes[:4] == b"RIFF":
        try:
            return struct.unpack("<I", wav_bytes[24:28])[0] or 16000
        except struct.error:
            return 16000
    return 16000


class DeepgramMultiChannelBatchProvider:
    name = "deepgram"

    def __init__(self, *, api_key: str, base_url: str, max_response_bytes: int,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._api_key = api_key
        self._base_url = base_url
        self._max_response_bytes = max_response_bytes
        self._transport = transport  # для тестов (httpx.MockTransport)

    async def transcribe(self, *, wav_bytes: bytes, channel_count: int,
                         channel_mapping: list, language: str, model: str,
                         timeout_seconds: int) -> MultiChannelBatchResult:
        params = {
            "model": model, "language": language,
            "multichannel": "true", "punctuate": "true",
            "smart_format": "true", "utterances": "true",
        }
        url = f"{self._base_url}?{urllib.parse.urlencode(params)}"
        headers = {"Authorization": f"Token {self._api_key}", "Content-Type": "audio/wav"}
        sample_rate = _sample_rate_from_wav(wav_bytes)

        client_kwargs = {"timeout": timeout_seconds}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                async with client.stream("POST", url, content=wav_bytes, headers=headers) as resp:
                    status = resp.status_code
                    if status in (401, 403):
                        raise MultiChannelBatchSttError(
                            ERR_PROVIDER_AUTH, "STT-провайдер не настроен или ключ отклонён",
                            retryable=False, provider_status=status)
                    if status == 429:
                        raise MultiChannelBatchSttError(
                            ERR_PROVIDER_RATE_LIMIT, "Лимит STT-провайдера исчерпан",
                            retryable=True, provider_status=status)
                    if status == 408:
                        raise MultiChannelBatchSttError(
                            ERR_PROVIDER_TIMEOUT, "Провайдер не успел обработать запись",
                            retryable=True, provider_status=status)
                    if status >= 500:
                        raise MultiChannelBatchSttError(
                            ERR_PROVIDER_UNAVAILABLE, "STT-провайдер временно недоступен",
                            retryable=True, provider_status=status)
                    # читаем тело с ограничением размера (не логируем)
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf += chunk
                        if len(buf) > self._max_response_bytes:
                            raise MultiChannelBatchSttError(
                                ERR_PROVIDER_RESPONSE_TOO_LARGE,
                                "Ответ провайдера превышает допустимый размер",
                                retryable=False, provider_status=status)
                    if status >= 400:
                        raise MultiChannelBatchSttError(
                            ERR_PROVIDER_BAD_RESPONSE, "Некорректный ответ провайдера",
                            retryable=False, provider_status=status)
        except httpx.TimeoutException:
            raise MultiChannelBatchSttError(
                ERR_PROVIDER_TIMEOUT, "Провайдер не успел обработать запись", retryable=True)
        except httpx.HTTPError:
            raise MultiChannelBatchSttError(
                ERR_PROVIDER_UNAVAILABLE, "Не удалось связаться с STT-провайдером", retryable=True)

        try:
            payload = json.loads(bytes(buf).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise MultiChannelBatchSttError(
                ERR_PROVIDER_BAD_RESPONSE, "Ответ провайдера не является валидным JSON",
                retryable=False)
        if not isinstance(payload, dict):
            raise MultiChannelBatchSttError(
                ERR_PROVIDER_BAD_RESPONSE, "Неожиданная структура ответа провайдера",
                retryable=False)

        return parse_deepgram_multichannel_response(
            data=payload, expected_channels=channel_count, channel_mapping=channel_mapping,
            model=model, language=language, sample_rate=sample_rate,
        )
