import argparse
import os
import re
import subprocess
import threading
import time

from .mysql_client import MySQLConfig, MySQLRadioDB
from .state import load_state, save_state
from .ytdlp_player import StreamPlayer


class FMClient:
    def __init__(
        self,
        mysql_host,
        mysql_port,
        mysql_user,
        mysql_password,
        mysql_database,
        mysql_timeout=10,
        mysql_pool_size: int = 3,
        state_path="client_state.json",
        poll_interval=3,
        default_duration=180,
        music_id: int = 1,
        music_watch_interval: float = 1.0,
        status_watch_interval: float = 2.0,
        alert_check_interval: float = 1.5,
        enable_tts: bool = True,
        enable_duration_detect: bool = True,
    ):
        self.cfg = MySQLConfig(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database,
            connection_timeout=mysql_timeout,
        )

        self.db = MySQLRadioDB(self.cfg, pool_size=int(mysql_pool_size))
        self.player = StreamPlayer()

        self.state_path = state_path
        self.state = load_state(state_path)

        self.poll_interval = poll_interval
        self.default_duration = default_duration

        # If your DB always overwrites a single row (e.g. id=1) with the current track,
        # enable this mode by setting music_id=1 (default).
        self.music_id = int(music_id)
        self.music_watch_interval = float(music_watch_interval)

        self.status_watch_interval = float(status_watch_interval)
        self.alert_check_interval = float(alert_check_interval)
        if self.alert_check_interval < 0.2:
            self.alert_check_interval = 0.2

        self.enable_tts = bool(enable_tts)
        self.enable_duration_detect = bool(enable_duration_detect)

        self._music_lock = threading.Lock()
        self._desired_music = None
        self._music_change_event = threading.Event()
        self._music_watch_stop = threading.Event()
        self._music_watch_thread = None

        # Server status gating
        self._status_cache_value = None
        self._status_cache_at = 0.0
        self._status_cache_ttl = 1.0
        self._last_status_mode_print_at = 0.0
        self._last_status_mode_value = None

        self._status_lock = threading.Lock()
        self._status_value = None
        self._status_change_event = threading.Event()
        self._status_watch_stop = threading.Event()
        self._status_watch_thread = None

        self.debug_tts = os.getenv("DEBUG_TTS", "0").strip() in {"1", "true", "True", "yes", "YES"}

        # Music volume (Windows/ffplay only). Used to duck music under AI alerts.
        self.music_volume_normal = 100
        self.music_volume_ducked = 10

        # TTS loudness (played via ffplay with an audio filter gain).
        self.tts_gain_user = 1.0
        self.tts_gain_ai = 4.0

        self._validate_state()

    # ---------------------------
    # Music watcher (DB -> player sync)
    # ---------------------------
    def _set_desired_music(self, music) -> None:
        with self._music_lock:
            self._desired_music = music
            self._music_change_event.set()

    def _get_desired_music(self):
        with self._music_lock:
            return self._desired_music

    def _consume_music_change(self):
        if not self._music_change_event.is_set():
            return None
        with self._music_lock:
            self._music_change_event.clear()
            return self._desired_music

    @staticmethod
    def _same_music(a, b) -> bool:
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        return (str(a.link or "").strip() == str(b.link or "").strip()) and (int(a.id) == int(b.id))

    def start_music_watcher(self) -> None:
        if self.music_id <= 0:
            return
        if self._music_watch_thread and self._music_watch_thread.is_alive():
            return

        self._music_watch_stop.clear()

        def _watch():
            last_link = None
            while not self._music_watch_stop.is_set():
                try:
                    row = self.db.get_music_by_id(self.music_id)
                    link = (row.link if row else "")
                    link = str(link or "").strip()

                    # On first successful read, seed desired music.
                    if row and link and last_link is None:
                        last_link = link
                        self._set_desired_music(row)
                    # On changes, signal the playback loop.
                    elif row and link and link != (last_link or ""):
                        last_link = link
                        self._set_desired_music(row)
                except Exception:
                    # Best-effort watcher: DB hiccups shouldn't crash playback.
                    pass

                time.sleep(max(0.2, float(self.music_watch_interval)))

        self._music_watch_thread = threading.Thread(target=_watch, name="music-db-watcher", daemon=True)
        self._music_watch_thread.start()

    def stop_music_watcher(self) -> None:
        self._music_watch_stop.set()
        t = self._music_watch_thread
        if t and t.is_alive():
            try:
                t.join(timeout=2.0)
            except Exception:
                pass

    # ---------------------------
    # Internal helpers
    # ---------------------------
    def _validate_state(self):
        try:
            max_music_id = self.db.get_music_max_id()
            if int(self.state.last_music_id) > int(max_music_id):
                print(
                    f"⚠️ Local state last_music_id={self.state.last_music_id} "
                    f"is ahead of DB max id={max_music_id}. Resetting."
                )
                self.state.last_music_id = 0
                self.state.last_music_link = ""
                save_state(self.state_path, self.state)
        except Exception:
            pass

    @staticmethod
    def _split_message(msg: str) -> list[str]:
        raw = str(msg or "")
        parts = [p.strip() for p in re.split(r"\|+|\n+", raw) if p.strip()]
        if parts:
            return parts
        single = raw.strip()
        return [single] if single else []

    # ---------------------------
    # TTS
    # ---------------------------
    @staticmethod
    def _play_audio_file_ffplay(file_path: str, *, volume: int = 100, gain: float = 1.0) -> None:
        vol = int(volume)
        if vol < 0:
            vol = 0
        if vol > 100:
            vol = 100

        cmd = [
            "ffplay",
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "error",
            "-volume",
            str(vol),
        ]
        if gain and float(gain) != 1.0:
            cmd.extend(["-af", f"volume={float(gain)}"])
        cmd.append(str(file_path))

        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            details = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"ffplay failed to play audio: {details}" if details else "ffplay failed to play audio")

    @staticmethod
    def _has_speakable_text(msg: str) -> bool:
        # Mirror `tts.generate_voice_from_text` cleaning logic enough to decide if this is empty.
        s = " ".join(str(msg or "").strip().split())
        if not s:
            return False
        # Remove common invisible/control markers.
        s = re.sub(r"[\u200b-\u200f\u202a-\u202e]", "", s)
        return bool(s.strip())

    @staticmethod
    def _should_ack_failed_tts(error: Exception) -> bool:
        msg = str(error or "").lower()
        return (
            "no text to send" in msg
            or "no speakable text" in msg
            or "text is empty" in msg
        )

    def speak_message(self, msg: str, *, gain: float = 1.0) -> int:
        if not self.enable_tts:
            return 0
        if not self.is_audio_allowed():
            self._print_status_mode_once()
            return 0
        if self.debug_tts:
            raw = str(msg or "")
            print(f"🧪 TTS raw len={len(raw)} repr={raw!r}")
        spoken = 0
        for part in self._split_message(msg):
            if not self._has_speakable_text(part):
                continue

            if self.debug_tts:
                p = str(part)
                try:
                    from .tts import detect_language

                    lang_dbg = detect_language(p)
                except Exception:
                    lang_dbg = "?"
                print(f"🧪 TTS part len={len(p)} lang={lang_dbg} repr={p!r}")

            try:
                from .tts import detect_language, generate_voice_from_text

                lang = detect_language(part)
                audio = generate_voice_from_text(part, lang=lang)
            except Exception as e:
                # Skip parts that are not speakable / fail TTS generation.
                print(f"❌ TTS generation failed for a message part: {e}")
                continue

            print(
                f"🔊 Speaking ({audio.get('lang')}) via {audio.get('engine')} "
                f"voice={audio.get('voice')} rate={audio.get('rate')}"
            )

            try:
                self._play_audio_file_ffplay(audio["file"], volume=100, gain=float(gain))
            except FileNotFoundError:
                # Fallback if ffplay isn't installed.
                from playsound import playsound

                playsound(audio["file"])
            finally:
                # Clean up temp mp3 to avoid filling small SD cards.
                try:
                    os.remove(audio["file"])
                except Exception:
                    pass
            spoken += 1

        return spoken

    # ---------------------------
    # Server status gating
    # ---------------------------
    def get_server_status(self) -> str:
        with self._status_lock:
            if self._status_value is not None:
                return str(self._status_value or "")

        now = time.time()
        if (now - float(self._status_cache_at)) < float(self._status_cache_ttl):
            return str(self._status_cache_value or "")

        status = ""
        try:
            status = self.db.get_server_status() or ""
        except Exception:
            status = ""

        self._status_cache_value = status
        self._status_cache_at = now
        return str(status or "")

    def is_audio_allowed(self) -> bool:
        status = (self.get_server_status() or "").strip().lower()
        return status in {"net", "both"}

    def _print_status_mode_once(self) -> None:
        status = (self.get_server_status() or "").strip().lower()
        now = time.time()
        # Print only when status changes or every ~15 seconds.
        if status != self._last_status_mode_value or (now - float(self._last_status_mode_print_at)) > 15.0:
            self._last_status_mode_value = status
            self._last_status_mode_print_at = now
            shown = status if status else "<unknown>"
            print(f"📻 radio is currently {shown!r}")

    def start_status_watcher(self, *, interval: float = 0.5) -> None:
        if self._status_watch_thread and self._status_watch_thread.is_alive():
            return

        self._status_watch_stop.clear()

        def _watch():
            last = None
            last_print = 0.0
            while not self._status_watch_stop.is_set():
                try:
                    current = self.db.get_server_status() or ""
                    current = str(current or "").strip().lower()
                except Exception:
                    current = ""

                if last is None:
                    last = current
                    with self._status_lock:
                        self._status_value = current
                    print(f"📡 Server status: {current!r}")
                    last_print = time.time()
                elif current != last:
                    old = last
                    last = current
                    with self._status_lock:
                        self._status_value = current
                    self._status_change_event.set()
                    print(f"🔄 Server status changed: {old!r} -> {current!r}")

                    last_print = time.time()

                    # Immediate action on disable.
                    if current not in {"net", "both"}:
                        try:
                            self.player.stop()
                        except Exception:
                            pass
                        self._print_status_mode_once()

                # Periodic status line (helps when status never changes)
                now = time.time()
                if (now - float(last_print)) > 30.0:
                    print(f"📡 Server status: {last!r}")
                    last_print = now

                time.sleep(max(0.2, float(interval)))

        self._status_watch_thread = threading.Thread(target=_watch, name="status-db-watcher", daemon=True)
        self._status_watch_thread.start()

    def stop_status_watcher(self) -> None:
        self._status_watch_stop.set()
        t = self._status_watch_thread
        if t and t.is_alive():
            try:
                t.join(timeout=2.0)
            except Exception:
                pass

    # ---------------------------
    # Alert handling
    # ---------------------------
    def handle_user_alerts(self):
        user_alert = self.db.get_next_user_alert_after(self.state.last_user_alert_id)
        if user_alert and user_alert.id > 0:
            print(f"📥 User alert (id={user_alert.id})")
            try:
                self.speak_message(user_alert.message, gain=self.tts_gain_user)
            except Exception as e:
                print(f"❌ Failed to speak user alert: {e}")
            else:
                removed = self.db.ack_user_alert(user_alert.id)
                if not removed:
                    print(f"⚠️  Could not remove user alert from DB (id={user_alert.id})")
                self.state.last_user_alert_id = max(
                    self.state.last_user_alert_id, user_alert.id
                )
                save_state(self.state_path, self.state)
                return True
        return False

    def handle_ai_alerts(self):
        ai_alert = self.db.get_next_ai_alert_after(self.state.last_ai_alert_id)
        if ai_alert and ai_alert.id > 0:
            print(f"🚨 AI alert (id={ai_alert.id}, severity={ai_alert.severity})")
            try:
                spoken = self.speak_message(ai_alert.message, gain=self.tts_gain_ai)
                if spoken <= 0:
                    raise ValueError("AI alert has no speakable text")
            except Exception as e:
                print(f"❌ Failed to speak AI alert: {e}")
                # If the alert has no usable text, acknowledge it anyway to avoid retry loops.
                if (not self._has_speakable_text(ai_alert.message)) or self._should_ack_failed_tts(e):
                    removed = self.db.ack_ai_alert(ai_alert.id)
                    if not removed:
                        print(f"⚠️  Could not remove AI alert from DB (id={ai_alert.id})")
                    self.state.last_ai_alert_id = ai_alert.id
                    save_state(self.state_path, self.state)
            else:
                removed = self.db.ack_ai_alert(ai_alert.id)
                if not removed:
                    print(f"⚠️  Could not remove AI alert from DB (id={ai_alert.id})")
                self.state.last_ai_alert_id = ai_alert.id
                save_state(self.state_path, self.state)
                return True
        return False

    # ---------------------------
    # Music handling
    # ---------------------------
    def get_next_music(self):
        music = self.db.get_next_music_after(self.state.last_music_id)
        if not music:
            try:
                latest = self.db.get_latest_music()
                if (
                    latest
                    and latest.id == self.state.last_music_id
                    and latest.link != (self.state.last_music_link or "")
                ):
                    return latest
            except Exception:
                pass
        return music

    def play_music(self, music):
        def _resolve_duration(m):
            d = m.duration_seconds
            # Duration detection via yt-dlp is expensive; avoid it in fixed-row mode
            # and allow disabling it entirely for low-power devices.
            if d is None and self.enable_duration_detect and self.music_id <= 0:
                try:
                    from .ytdlp_player import get_media_duration_seconds

                    d = get_media_duration_seconds(m.link)
                except Exception:
                    d = None
            if d is None and self.music_id <= 0:
                d = int(self.default_duration)
            return d

        duration = _resolve_duration(music)

        print(f"🎶 Playing music (id={music.id}) {music.name}")
        print(f"🔗 {music.link}")
        print(f"⏳ Duration: {duration}s" if duration is not None else "⏳ Duration: (continuous)")

        self.player.start(music.link, volume=self.music_volume_normal)

        started_at = time.time()
        planned = int(duration) if duration is not None else None

        last_alert_check = 0.0

        while True:
            if not self.is_audio_allowed():
                self._print_status_mode_once()
                try:
                    self.player.stop()
                except Exception:
                    pass
                # Do not advance last_music_id when we were forced to stop.
                return

            # If DB music changed, switch immediately.
            desired = self._consume_music_change()
            if desired and (not self._same_music(desired, music)) and desired.link:
                print(f"🔁 DB music changed (id={desired.id}) switching")
                music = desired
                duration = _resolve_duration(music)
                print(f"🎶 Playing music (id={music.id}) {music.name}")
                print(f"🔗 {music.link}")
                print(f"⏳ Duration: {duration}s" if duration is not None else "⏳ Duration: (continuous)")
                self.player.start(music.link, volume=self.music_volume_normal)
                started_at = time.time()
                planned = int(duration) if duration is not None else None

            elapsed = time.time() - started_at
            if planned is not None and elapsed >= planned:
                self.player.stop()
                break

            now = time.time()
            if (now - float(last_alert_check)) >= float(self.alert_check_interval):
                last_alert_check = now

                # Interrupt for user alerts
                user_alert = self.db.get_next_user_alert_after(self.state.last_user_alert_id)
                if user_alert and user_alert.id > 0:
                    print(f"📥 User alert (id={user_alert.id})")
                    self.player.stop()

                    try:
                        self.speak_message(user_alert.message, gain=self.tts_gain_user)
                    except Exception as e:
                        print(f"❌ Failed to speak user alert: {e}")
                    else:
                        removed = self.db.ack_user_alert(user_alert.id)
                        if not removed:
                            print(f"⚠️  Could not remove user alert from DB (id={user_alert.id})")
                        self.state.last_user_alert_id = max(
                            self.state.last_user_alert_id, user_alert.id
                        )
                        save_state(self.state_path, self.state)

                    # Restart music
                    self.player.start(music.link, volume=self.music_volume_normal)
                    started_at = time.time()
                    continue

                # Duck music for AI alerts (do not pause)
                ai_alert = self.db.get_next_ai_alert_after(self.state.last_ai_alert_id)
                if ai_alert and ai_alert.id > 0:
                    print(f"🚨 AI alert (id={ai_alert.id}, severity={ai_alert.severity})")

                    # Reduce volume (best-effort: restart player with same resolved URL)
                    try:
                        self.player.restart_with_volume(self.music_volume_ducked)
                    except Exception:
                        # Fallback: restart normally (may re-resolve)
                        self.player.start(music.link, volume=self.music_volume_ducked)

                    try:
                        spoken = self.speak_message(ai_alert.message, gain=self.tts_gain_ai)
                        if spoken <= 0:
                            raise ValueError("AI alert has no speakable text")
                    except Exception as e:
                        print(f"❌ Failed to speak AI alert: {e}")
                        if (not self._has_speakable_text(ai_alert.message)) or self._should_ack_failed_tts(e):
                            removed = self.db.ack_ai_alert(ai_alert.id)
                            if not removed:
                                print(f"⚠️  Could not remove AI alert from DB (id={ai_alert.id})")
                            self.state.last_ai_alert_id = ai_alert.id
                            save_state(self.state_path, self.state)
                    else:
                        removed = self.db.ack_ai_alert(ai_alert.id)
                        if not removed:
                            print(f"⚠️  Could not remove AI alert from DB (id={ai_alert.id})")
                        self.state.last_ai_alert_id = ai_alert.id
                        save_state(self.state_path, self.state)
                    finally:
                        # Restore normal music volume (best-effort)
                        try:
                            self.player.restart_with_volume(self.music_volume_normal)
                        except Exception:
                            self.player.start(music.link, volume=self.music_volume_normal)

            time.sleep(0.25)

        self.state.last_music_id = music.id
        self.state.last_music_link = music.link
        save_state(self.state_path, self.state)

    # ---------------------------
    # Main loop
    # ---------------------------
    def run(self):
        print("🛰️ Client connected (polling MySQL)")
        try:
            self.start_music_watcher()
            self.start_status_watcher(interval=float(self.status_watch_interval))
            while True:
                if not self.is_audio_allowed():
                    self._print_status_mode_once()
                    try:
                        self.player.stop()
                    except Exception:
                        pass
                    time.sleep(int(self.poll_interval))
                    continue

                self.handle_user_alerts()
                self.handle_ai_alerts()

                # Prefer fixed-row mode (id=1) when enabled; fallback to sequential mode.
                music = None
                if self.music_id > 0:
                    music = self._get_desired_music() or self.db.get_music_by_id(self.music_id)
                if not music:
                    music = self.get_next_music()
                if music and music.id > 0 and music.link:
                    try:
                        self.play_music(music)
                    except Exception as e:
                        print(f"❌ Playback error: {e}")

                time.sleep(int(self.poll_interval))
        except KeyboardInterrupt:
            print("\n🛑 Client stopped")
            try:
                self.player.stop()
            except Exception:
                pass
            try:
                self.stop_music_watcher()
            except Exception:
                pass
            try:
                self.stop_status_watcher()
            except Exception:
                pass
