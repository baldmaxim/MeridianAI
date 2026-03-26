"""Audio compression service using ffmpeg (async)."""

import os
import re
import asyncio
import shutil
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class AudioCompressor:
    _cached_ffmpeg_path: Optional[str] = None
    _cache_checked: bool = False

    def __init__(self, ffmpeg_path: Optional[str] = None):
        if ffmpeg_path:
            self.ffmpeg_path = ffmpeg_path
        elif AudioCompressor._cache_checked:
            self.ffmpeg_path = AudioCompressor._cached_ffmpeg_path
        else:
            self.ffmpeg_path = self._find_ffmpeg()
            AudioCompressor._cached_ffmpeg_path = self.ffmpeg_path
            AudioCompressor._cache_checked = True

    def _find_ffmpeg(self) -> Optional[str]:
        ffmpeg_env = os.getenv("FFMPEG_PATH")
        if ffmpeg_env and os.path.exists(ffmpeg_env):
            return ffmpeg_env

        ffmpeg_in_path = shutil.which("ffmpeg")
        if ffmpeg_in_path:
            return ffmpeg_in_path

        paths = [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\ffmpeg\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
            os.path.expanduser(r"~\ffmpeg\bin\ffmpeg.exe"),
            os.path.expanduser(r"~\AppData\Local\ffmpeg\bin\ffmpeg.exe"),
            r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
            os.path.expanduser(r"~\scoop\apps\ffmpeg\current\bin\ffmpeg.exe"),
        ]
        for path in paths:
            if os.path.exists(path):
                logger.info(f"ffmpeg found: {path}")
                return path

        logger.warning("ffmpeg not found")
        return None

    @property
    def is_available(self) -> bool:
        return self.ffmpeg_path is not None

    async def compress_to_opus(
        self,
        input_path: str,
        output_dir: str,
        bitrate: str = "20k",
    ) -> Optional[Tuple[str, int, int]]:
        """Compress audio to Opus/OGG.

        Returns (compressed_path, original_size, compressed_size) or None on failure.
        """
        if not self.ffmpeg_path:
            return None

        try:
            input_file = Path(input_path)
            output_path = Path(output_dir) / f"{input_file.stem}_compressed.ogg"
            original_size = os.path.getsize(input_path)

            cmd = [
                self.ffmpeg_path,
                "-y",
                "-threads", "0",
                "-i", str(input_path),
                "-ac", "1",
                "-ar", "16000",
                "-c:a", "libopus",
                "-b:a", bitrate,
                "-vbr", "on",
                "-compression_level", "5",
                "-application", "voip",
                str(output_path),
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()

            if process.returncode == 0 and output_path.exists():
                compressed_size = os.path.getsize(str(output_path))
                logger.info(
                    f"Compressed: {input_path} -> {output_path} "
                    f"({original_size} -> {compressed_size})"
                )
                return str(output_path), original_size, compressed_size

            logger.error(f"Compression failed: {stderr.decode()[:500]}")
            return None

        except Exception as e:
            logger.error(f"Compression error: {e}")
            return None
