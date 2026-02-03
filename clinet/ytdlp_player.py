from __future__ import annotations

import json
import os
import subprocess
import time
import platform
import signal
import sys
from typing import Optional


# Always use python -m yt_dlp (never call yt-dlp directly)
YT_DLP = [sys.executable, "-m", "yt_dlp"]


class StreamPlayer:
    """Optimized Linux-only stream player using yt-dlp + ffplay."""

    def __init__(self):
        self.player_process: Optional[subprocess.Popen] = None
        self._cache: dict[str, str] = {}

    # -------------------- Process Handling --------------------

    def _kill_process_tree(self, process: Optional[subprocess.Popen]):
        if not process or process.poll() is not None:
            return

        try:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
                time.sleep(0.2)
                process.terminate()
            else:
                os.killpg(os.getpgid(process.pid), 15)
                time.sleep(0.2)
                os.killpg(os.getpgid(process.pid), 9)
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass

    def stop(self):
        self._kill_process_tree(self.player_process)
        self.player_process = None

    # -------------------- yt-dlp Resolution --------------------

    def _resolve_audio_url(self, url: str) -> str:
        if url in self._cache:
            return self._cache[url]

        cmd = YT_DLP + [
            "-g",
            "-f",
            "bestaudio",
            "--no-playlist",
            url,
        ]

        resolved = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )

        if resolved.returncode != 0:
            details = (resolved.stderr or resolved.stdout or "").strip()
            raise RuntimeError(f"yt-dlp failed:\n{details}")

        lines = (resolved.stdout or "").strip().splitlines()
        if not lines:
            raise RuntimeError("yt-dlp returned no stream URL")

        stream = lines[-1].strip()
        self._cache[url] = stream
        return stream

    # -------------------- Player Control --------------------

    def is_playing(self) -> bool:
        return bool(self.player_process and self.player_process.poll() is None)

    def start(self, url: str, *, volume: int = 100, position: float = 0.0) -> None:
        self.stop()

        stream_url = self._resolve_audio_url(url)
        vol = max(0, min(100, int(volume)))

        player_cmd = [
            "ffplay",
            "-vn",
            "-nodisp",
            "-autoexit",
            "-loglevel", "error",
            "-volume", str(vol),
        ]
        if position > 0:
            player_cmd.extend(["-ss", str(float(position))])
        player_cmd.append(stream_url)

        if os.name == "nt":
            self.player_process = subprocess.Popen(
                player_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            self.player_process = subprocess.Popen(
                player_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
            )

    def play(self, url: str, *, duration: Optional[int] = None):
        self.start(url)

        if duration is not None:
            time.sleep(int(duration))
            self.stop()
            return

        self.player_process.wait()
        self.player_process = None


# -------------------- Duration Utility --------------------

def get_media_duration_seconds(url: str, *, timeout: int = 45) -> Optional[int]:
    if not url:
        return None

    cmd = YT_DLP + [
        "-J",
        "--no-playlist",
        url,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
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
