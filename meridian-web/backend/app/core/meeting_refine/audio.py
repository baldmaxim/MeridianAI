"""Аудио для уточнения: энергия каналов из WAV, сведение каналов и сжатие через ffmpeg."""

import asyncio
import logging
import wave
from pathlib import Path

import numpy as np

from ..batch.audio_compressor import AudioCompressor
from .mapping import ENERGY_WINDOW_SEC, window_energy

logger = logging.getLogger("meridian.refine")

_CHUNK_WINDOWS = 6000  # окон за одно чтение: ~10 минут звука 16 кГц


def wav_duration(path: str) -> float | None:
    """Длительность WAV по заголовку; не WAV или битый файл — None."""
    try:
        with wave.open(path, "rb") as w:
            rate = w.getframerate()
            return w.getnframes() / rate if rate else None
    except (wave.Error, EOFError, OSError):
        return None


def load_wav_energy(path: str, window: float = ENERGY_WINDOW_SEC) -> np.ndarray | None:
    """Энергия WAV по окнам, потоково (запись на часы целиком в память не грузим). Не s16 WAV — None."""
    try:
        with wave.open(path, "rb") as w:
            if w.getsampwidth() != 2:
                return None
            channels = w.getnchannels()
            window_frames = max(1, int(w.getframerate() * window))
            parts: list[np.ndarray] = []
            while True:
                raw = w.readframes(window_frames * _CHUNK_WINDOWS)
                if not raw:
                    break
                samples = np.frombuffer(raw, dtype="<i2")
                if channels > 1:
                    samples = samples[: samples.size // channels * channels].reshape(-1, channels).mean(axis=1)
                parts.append(window_energy(samples, window_frames))
    except (wave.Error, EOFError, OSError):
        return None
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float64)


async def _run_ffmpeg(cmd: list[str]) -> bool:
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        logger.error("ffmpeg завершился с ошибкой: %s", stderr.decode(errors="replace")[:300])
        return False
    return True


async def mix_to_mono(paths: list[str], out_path: str, ffmpeg_path: str) -> bool:
    """Свести каналы в один моно-файл 16 кГц: громкость не нормализуем, длина — по самому длинному."""
    cmd = [ffmpeg_path, "-y", "-threads", "0"]
    for p in paths:
        cmd += ["-i", p]
    cmd += [
        "-filter_complex", f"amix=inputs={len(paths)}:duration=longest:normalize=0",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out_path,
    ]
    return await _run_ffmpeg(cmd) and Path(out_path).exists()


async def prepare_audio(paths: list[str], tmpdir: str) -> str | None:
    """Один файл для распознавания: каналы сведены (если их два) и сжаты в opus.

    None — ffmpeg недоступен или сведение не удалось. Сжатие не обязательно: не вышло — отдаём WAV.
    """
    compressor = AudioCompressor()
    if not compressor.is_available:
        return paths[0] if len(paths) == 1 else None
    source = paths[0]
    if len(paths) > 1:
        source = str(Path(tmpdir) / "mixed.wav")
        if not await mix_to_mono(paths, source, compressor.ffmpeg_path):
            return None
    compressed = await compressor.compress_to_opus(source, tmpdir)
    if compressed:
        return compressed[0]
    logger.warning("уточнение: сжатие не удалось, распознаём WAV как есть")
    return source
