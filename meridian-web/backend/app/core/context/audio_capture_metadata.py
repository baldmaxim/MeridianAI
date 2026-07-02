"""Safe audio capture route metadata (Этап 15).

Описывает ТЕХНИЧЕСКУЮ зону записи (какое устройство/маршрут захвата, сколько каналов, sample rate),
а НЕ сторону переговоров и НЕ личность. route/source_kind никогда не задают speaker_side —
сторона приходит только через speaker_identity_hints поверх stable link.

Безопасность: raw device label / device id НЕ хранятся — только sha256-хэши (если переданы или
если переданы сырыми, хэшируются и сырьё отбрасывается). Никакого user-agent дампа — только
короткое sanitized имя браузера. Диагностический/телеметрический слой, не источник attribution.
"""

import hashlib
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

_ROUTES = {
    "browser_default", "laptop_mic", "usb_room_mic", "usb_recorder",
    "speakerphone_usb", "external_audio_interface", "phone_secondary", "unknown",
}
_PIPELINES = {
    "mono_stream", "stereo_requested_mono_stream", "multichannel_stream", "unknown",
}
_SOURCE_KINDS = {
    "room_mic", "usb_recorder", "speakerphone", "secondary_device", "unknown",
}

# route → безопасный source_kind по умолчанию (НЕ сторона!). Только техническая категория записи.
_ROUTE_TO_SOURCE_KIND = {
    "usb_room_mic": "room_mic",
    "usb_recorder": "usb_recorder",
    "external_audio_interface": "usb_recorder",
    "speakerphone_usb": "speakerphone",
    "phone_secondary": "secondary_device",
    # laptop_mic / browser_default / unknown → "unknown" (ноутбучный/дефолтный микрофон
    # НЕ считаем room_mic и тем более стороной)
}

_MAX_BROWSER_LEN = 80
_CHANNEL_MIN, _CHANNEL_MAX = 1, 32
_RATE_MIN, _RATE_MAX = 4000, 768000


class AudioCaptureMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    route: str = "unknown"
    capture_pipeline: str = "unknown"
    requested_channel_count: Optional[int] = None
    actual_channel_count: Optional[int] = None
    requested_sample_rate: Optional[int] = None
    actual_sample_rate: Optional[int] = None
    echo_cancellation: Optional[bool] = None
    noise_suppression: Optional[bool] = None
    auto_gain_control: Optional[bool] = None
    device_label_hash: Optional[str] = None
    device_id_hash: Optional[str] = None
    browser: Optional[str] = None
    source_kind: str = "unknown"
    source_is_isolated: bool = False
    created_at_ms: Optional[int] = None
    # Этап 16: включён ли опциональный multichannel shadow-стрим (диагностика, не сторона/не STT)
    multichannel_shadow_enabled: Optional[bool] = None


def normalize_audio_capture_route(value: Any) -> str:
    """Привести route к известному значению; иначе 'unknown'."""
    if isinstance(value, str) and value in _ROUTES:
        return value
    return "unknown"


def normalize_capture_pipeline(value: Any) -> str:
    """Привести capture_pipeline к известному значению; иначе 'unknown'."""
    if isinstance(value, str) and value in _PIPELINES:
        return value
    return "unknown"


def normalize_source_kind(value: Any) -> str:
    """Привести source_kind к известной технической категории записи; иначе 'unknown'."""
    if isinstance(value, str) and value in _SOURCE_KINDS:
        return value
    return "unknown"


def hash_audio_token(value: Any) -> Optional[str]:
    """sha256[:16] от строкового представления токена (device label/id). None для пустого."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def sanitize_browser_name(value: Any) -> Optional[str]:
    """Короткое безопасное имя браузера (без полного user-agent). None для пустого."""
    if value is None:
        return None
    s = " ".join(str(value).split())  # схлопнуть пробелы/переводы строк
    if not s:
        return None
    return s[:_MAX_BROWSER_LEN]


def _get(payload: Any, *keys: str, default: Any = None) -> Any:
    """Достать первый непустой из ключей (dict.get или getattr — поддержка dict и объекта)."""
    for k in keys:
        if isinstance(payload, dict):
            if payload.get(k) is not None:
                return payload[k]
        else:
            v = getattr(payload, k, None)
            if v is not None:
                return v
    return default


def _opt_int_clamped(value: Any, lo: int, hi: int) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return None


def _opt_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
    return None


def parse_audio_capture_metadata(payload: Any) -> AudioCaptureMetadata:
    """Распарсить безопасный AudioCaptureMetadata из payload (dict или объекта).

    Сырые deviceLabel/deviceId хэшируются и НЕ сохраняются. Невалидные значения → дефолты/unknown.
    Никогда не бросает на «грязном» payload — возвращает безопасный объект.
    """
    if payload is None or not (isinstance(payload, dict) or hasattr(payload, "__dict__")):
        return AudioCaptureMetadata()

    route = normalize_audio_capture_route(_get(payload, "route"))

    # device hashes: брать готовый hash, иначе хэшировать сырьё и отбросить raw
    label_hash = _get(payload, "device_label_hash", "deviceLabelHash", "labelHash")
    if not label_hash:
        label_hash = hash_audio_token(_get(payload, "device_label", "deviceLabel", "label"))
    else:
        label_hash = str(label_hash)[:64]
    id_hash = _get(payload, "device_id_hash", "deviceIdHash")
    if not id_hash:
        id_hash = hash_audio_token(_get(payload, "device_id", "deviceId"))
    else:
        id_hash = str(id_hash)[:64]

    explicit_kind = _get(payload, "source_kind", "sourceKind")
    source_kind = (normalize_source_kind(explicit_kind) if explicit_kind is not None
                   else _ROUTE_TO_SOURCE_KIND.get(route, "unknown"))

    return AudioCaptureMetadata(
        route=route,
        capture_pipeline=normalize_capture_pipeline(_get(payload, "capture_pipeline", "capturePipeline")),
        requested_channel_count=_opt_int_clamped(
            _get(payload, "requested_channel_count", "requestedChannelCount"), _CHANNEL_MIN, _CHANNEL_MAX),
        actual_channel_count=_opt_int_clamped(
            _get(payload, "actual_channel_count", "actualChannelCount"), _CHANNEL_MIN, _CHANNEL_MAX),
        requested_sample_rate=_opt_int_clamped(
            _get(payload, "requested_sample_rate", "requestedSampleRate"), _RATE_MIN, _RATE_MAX),
        actual_sample_rate=_opt_int_clamped(
            _get(payload, "actual_sample_rate", "actualSampleRate"), _RATE_MIN, _RATE_MAX),
        echo_cancellation=_opt_bool(_get(payload, "echo_cancellation", "echoCancellation")),
        noise_suppression=_opt_bool(_get(payload, "noise_suppression", "noiseSuppression")),
        auto_gain_control=_opt_bool(_get(payload, "auto_gain_control", "autoGainControl")),
        device_label_hash=label_hash,
        device_id_hash=id_hash,
        browser=sanitize_browser_name(_get(payload, "browser")),
        source_kind=source_kind,
        source_is_isolated=bool(_opt_bool(_get(payload, "source_is_isolated", "sourceIsIsolated")) or False),
        created_at_ms=_opt_int_clamped(_get(payload, "created_at_ms", "createdAtMs"), 0, 4102444800000),
        multichannel_shadow_enabled=_opt_bool(
            _get(payload, "multichannel_shadow_enabled", "multichannelShadowEnabled")),
    )
