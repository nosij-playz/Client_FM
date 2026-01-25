import json
import os
from dataclasses import dataclass


@dataclass
class ClientState:
    last_music_id: int = 0
    last_music_link: str = ""
    last_ai_alert_id: int = 0
    last_user_alert_id: int = 0


def load_state(path: str) -> ClientState:
    if not os.path.exists(path):
        return ClientState()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        return ClientState(
            last_music_id=int(data.get("last_music_id", 0) or 0),
            last_music_link=str(data.get("last_music_link", "") or ""),
            last_ai_alert_id=int(data.get("last_ai_alert_id", 0) or 0),
            last_user_alert_id=int(data.get("last_user_alert_id", 0) or 0),
        )
    except Exception:
        return ClientState()


def save_state(path: str, state: ClientState) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "last_music_id": int(state.last_music_id),
                "last_music_link": str(state.last_music_link or ""),
                "last_ai_alert_id": int(state.last_ai_alert_id),
                "last_user_alert_id": int(state.last_user_alert_id),
            },
            f,
            indent=2,
        )
