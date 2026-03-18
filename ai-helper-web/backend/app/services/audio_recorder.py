"""Audio recorder for saving raw PCM to disk during meetings.

Writes raw PCM incrementally. Converts to WAV only when needed
(batch finalization). This avoids WAV header issues with incremental writes.
"""

import io
import logging
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ai_helper.audio_recorder")


class AudioRecorder:
    """Records raw PCM audio to disk for post-meeting batch finalization."""

    def __init__(
        self,
        output_dir: Path,
        session_id: str,
        sample_rate: int = 16000,
        channels: int = 1,
        sample_width: int = 2,
    ):
        self.output_dir = Path(output_dir)
        self.session_id = session_id
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width

        self.file_path: Optional[Path] = None
        self._file = None
        self._bytes_written: int = 0
        self._is_recording: bool = False

    def start(self) -> None:
        """Open PCM file for writing."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.output_dir / f"{self.session_id}.pcm"
        self._file = open(self.file_path, "wb")
        self._bytes_written = 0
        self._is_recording = True
        logger.info(f"[AudioRecorder] Recording to {self.file_path}")

    def write(self, pcm_data: bytes) -> None:
        """Append raw PCM frames. Called from streaming service audio loop."""
        if self._file and self._is_recording:
            try:
                self._file.write(pcm_data)
                self._bytes_written += len(pcm_data)
            except Exception as e:
                logger.warning(f"[AudioRecorder] Write error: {e}")

    def stop(self) -> Optional[Path]:
        """Stop recording, close file. Returns path if audio was recorded."""
        self._is_recording = False
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None

        if self._bytes_written > 0:
            logger.info(
                f"[AudioRecorder] Stopped. {self.duration_seconds:.1f}s "
                f"({self._bytes_written} bytes)"
            )
            return self.file_path
        return None

    @property
    def duration_seconds(self) -> float:
        return self._bytes_written / (self.sample_rate * self.sample_width * self.channels)

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def to_wav_bytes(self) -> Optional[bytes]:
        """Convert recorded PCM to WAV bytes for batch API.

        Reads the PCM file from disk and wraps it with a WAV header.
        Call after stop().
        """
        if not self.file_path or not self.file_path.exists():
            return None

        pcm_data = self.file_path.read_bytes()
        if not pcm_data:
            return None

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.sample_width)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm_data)

        buf.seek(0)
        return buf.read()

    def cleanup(self) -> None:
        """Delete recorded file from disk."""
        self.stop()
        if self.file_path and self.file_path.exists():
            try:
                self.file_path.unlink()
                logger.info(f"[AudioRecorder] Deleted {self.file_path}")
            except Exception as e:
                logger.warning(f"[AudioRecorder] Cleanup error: {e}")
