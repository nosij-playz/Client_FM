from __future__ import annotations

import json
import os
import platform
import subprocess
import shutil
import sys
import tempfile
import time
from typing import Optional


class StreamPlayer:
    """Standalone player: resolves URL using yt-dlp then plays via ffplay/mpg123."""

    def __init__(self):
        self.system = platform.system().lower()
        self.player_process: Optional[subprocess.Popen] = None

        # Cache resolved stream URLs (yt-dlp -g is expensive on low-power devices).
        # Format: {original_url: (resolved_stream_url, monotonic_timestamp)}
        self._resolved_cache: dict[str, tuple[str, float]] = {}
        self._resolved_cache_ttl = float(os.getenv("YTDLP_RESOLVE_CACHE_TTL", "600") or 600)

        self._current_source_url: Optional[str] = None
        self._current_stream_url: Optional[str] = None
        self._current_volume: int = 100

    def _kill_process_tree(self, process: Optional[subprocess.Popen]):
        if not process or process.poll() is not None:
            return

        try:
            if self.system == "windows":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                try:
                    os.killpg(os.getpgid(process.pid), 15)
                except Exception:
                    process.terminate()
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass

    def stop(self):
        self._kill_process_tree(self.player_process)
        self.player_process = None
        self._current_source_url = None
        self._current_stream_url = None

    @staticmethod
    def _python_for_ytdlp() -> str:
        # Use current interpreter; on the standalone device this venv should include yt-dlp.
        return sys.executable

    def _resolve_audio_url(self, url: str) -> str:
        py = self._python_for_ytdlp()
        cmd = [py, "-m", "yt_dlp", "-g", "-f", "bestaudio", "--no-playlist", url]
        resolved = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if resolved.returncode != 0:
            details = (resolved.stderr or resolved.stdout or "").strip()
            msg = "yt-dlp failed to resolve audio URL"
            if details:
                msg += f"\n\nDetails:\n{details}"
            raise RuntimeError(msg)

        lines = (resolved.stdout or "").strip().splitlines()
        if not lines:
            raise RuntimeError("yt-dlp returned no stream URL")
        return lines[-1].strip()

    def _get_stream_url(self, url: str) -> str:
        key = str(url or "").strip()
        if not key:
            raise ValueError("url is empty")

        now = time.monotonic()
        cached = self._resolved_cache.get(key)
        if cached is not None:
            resolved, at = cached
            if (now - float(at)) <= float(self._resolved_cache_ttl) and resolved:
                return resolved

        resolved = self._resolve_audio_url(key)
        self._resolved_cache[key] = (resolved, now)
        return resolved

    def is_playing(self) -> bool:
        return bool(self.player_process and self.player_process.poll() is None)

    def start(self, url: str, *, volume: int = 100) -> None:
        """Start playback and return immediately (non-blocking).

        On Windows, uses ffplay's `-volume` (0-100).
        """
        self.stop()

        self._current_source_url = str(url or "").strip()
        stream_url = self._get_stream_url(self._current_source_url)
        self._current_stream_url = stream_url

        vol = int(volume)
        if vol < 0:
            vol = 0
        if vol > 100:
            vol = 100
        self._current_volume = vol

        # Prefer ffplay when available (better format support than mpg123 on Linux).
        ffplay = shutil.which("ffplay")
        mpg123 = shutil.which("mpg123")

        if self.system == "windows" or ffplay:
            vol = int(volume)
            if vol < 0:
                vol = 0
            if vol > 100:
                vol = 100
            player_cmd = [
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "error",
                "-volume",
                str(vol),
                stream_url,
            ]
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if self.system == "windows" else 0
            preexec_fn = None if self.system == "windows" else os.setsid
        else:
            if not mpg123:
                raise RuntimeError(
                    "No audio player found. Install ffmpeg (ffplay) or mpg123, or ensure one is in PATH."
                )
            player_cmd = ["mpg123", stream_url]
            creationflags = 0
            preexec_fn = os.setsid

        self.player_process = subprocess.Popen(
            player_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            preexec_fn=preexec_fn,
        )

    def restart_with_volume(self, volume: int) -> None:
        """Best-effort volume update without re-resolving via yt-dlp.

        If playback is active and we have a cached stream URL, restart the player
        process using the same resolved URL.
        """
        if not self._current_stream_url:
            # Nothing to restart; caller should use start().
            return

        # Avoid restart if no change.
        vol = int(volume)
        if vol < 0:
            vol = 0
        if vol > 100:
            vol = 100
        if vol == int(self._current_volume):
            return

        source_url = self._current_source_url
        stream_url = self._current_stream_url
        self.stop()
        # Restore state fields (stop() clears them)
        self._current_source_url = source_url
        self._current_stream_url = stream_url
        self._current_volume = vol

        ffplay = shutil.which("ffplay")
        mpg123 = shutil.which("mpg123")
        if self.system == "windows" or ffplay:
            player_cmd = [
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "error",
                "-volume",
                str(vol),
                stream_url,
            ]
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if self.system == "windows" else 0
            preexec_fn = None if self.system == "windows" else os.setsid
        else:
            if not mpg123:
                raise RuntimeError(
                    "No audio player found. Install ffmpeg (ffplay) or mpg123, or ensure one is in PATH."
                )
            player_cmd = ["mpg123", stream_url]
            creationflags = 0
            preexec_fn = os.setsid

        self.player_process = subprocess.Popen(
            player_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            preexec_fn=preexec_fn,
        )

    def play(self, url: str, *, duration: Optional[int] = None):
        self.start(url)

        if duration is not None:
            time.sleep(int(duration))
            self.stop()
            return

        self.player_process.wait()
        self.player_process = None


def get_media_duration_seconds(url: str, *, timeout: int = 45) -> Optional[int]:
    """Return media duration in seconds using yt-dlp JSON, or None if unknown/live."""

    if not url:
        return None

    cmd = [sys.executable, "-m", "yt_dlp", "-J", "--no-playlist", url]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return None

    if proc.returncode != 0 or not proc.stdout:
        return None

    try:
        info = json.loads(proc.stdout)
    except Exception:
        return None

    if info.get("is_live") is True:
        return None

    duration = info.get("duration")
    if duration is None:
        return None

    try:
        val = int(duration)
        return val if val > 0 else None
    except Exception:
        return None
