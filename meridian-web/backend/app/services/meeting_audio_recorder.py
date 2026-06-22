"""Задача 3: серверная запись живого аудио встречи (активный источник) на диск.

PCM16/16k/mono пишется потоково в temp .pcm на диске (НЕ в RAM — закрывает старую
проблему «500MB в RAM»). На финализации сессии файл оборачивается в WAV (без перекодирования)
и ставится job meeting_audio_archive, который сжимает в opus и грузит в S3.

Кап по размеру защищает диск VPS. Запись активного источника уже отфильтрована в
MeetingRoom.handle_audio_frame, поэтому сюда попадает ровно тот PCM, что идёт в STT.
"""

import logging
import os
import shutil
import struct
import uuid
import wave  # noqa: F401  (валидация наличия модуля; запись делаем вручную для стриминга)
from pathlib import Path

from ..config import get_settings

logger = logging.getLogger("meridian.audio_recorder")

# PCM16 mono 16k = 32000 байт/сек. Кап ~4 часа записи.
_MAX_BYTES = 4 * 60 * 60 * 32000  # ~460 МБ
_SAMPLE_RATE = 16000
_CHANNELS = 1


class SessionAudioRecorder:
    """Потоковая запись PCM активного источника в temp-файл (per room-instance)."""

    def __init__(self, meeting_id: int):
        self.meeting_id = meeting_id
        self._path: str | None = None
        self._fh = None
        self._bytes = 0
        self._capped = False

    def _ensure_open(self) -> None:
        if self._fh is not None:
            return
        base = Path(get_settings().upload_dir) / "meeting_audio_tmp"
        base.mkdir(parents=True, exist_ok=True)
        # uuid → разные room-инстансы одной встречи не перетирают файл друг друга
        self._path = str(base / f"meeting_{self.meeting_id}_{uuid.uuid4().hex[:8]}.pcm")
        self._fh = open(self._path, "ab")

    def append(self, data: bytes) -> None:
        """Дозаписать PCM. Никогда не должно ломать аудио-поток (всё в try)."""
        if self._capped or not data:
            return
        try:
            if self._bytes + len(data) > _MAX_BYTES:
                self._capped = True
                logger.warning("[room %s] audio archive cap reached (%d bytes) — stop appending",
                               self.meeting_id, self._bytes)
                return
            self._ensure_open()
            self._fh.write(data)
            self._bytes += len(data)
        except Exception as e:
            logger.error("[room %s] audio append failed: %s", self.meeting_id, e)

    @property
    def has_audio(self) -> bool:
        return self._bytes > 0

    def close_to_pcm(self) -> str | None:
        """Закрыть файл; вернуть путь .pcm (или None, если ничего не записано)."""
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
        return self._path if self._bytes > 0 else None


def pcm_to_wav(pcm_path: str, sample_rate: int = _SAMPLE_RATE, channels: int = _CHANNELS) -> str:
    """Обернуть raw PCM16 в WAV-контейнер потоково (без загрузки файла в RAM).

    Возвращает путь .wav, удаляет исходный .pcm. Блокирующая I/O — вызывать через to_thread.
    """
    data_size = os.path.getsize(pcm_path)
    wav_path = (pcm_path[:-4] if pcm_path.endswith(".pcm") else pcm_path) + ".wav"
    byte_rate = sample_rate * channels * 2
    block_align = channels * 2
    with open(wav_path, "wb") as out, open(pcm_path, "rb") as src:
        out.write(b"RIFF")
        out.write(struct.pack("<I", 36 + data_size))
        out.write(b"WAVEfmt ")
        out.write(struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, 16))
        out.write(b"data")
        out.write(struct.pack("<I", data_size))
        shutil.copyfileobj(src, out, length=1024 * 1024)
    try:
        os.remove(pcm_path)
    except OSError:
        pass
    return wav_path
