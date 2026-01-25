from __future__ import annotations

import os
import re
import tempfile
import time
from typing import Dict

from gtts import gTTS


def detect_language(text: str) -> str:
    # Malayalam Unicode block: U+0D00–U+0D7F
    for ch in text:
        if "\u0d00" <= ch <= "\u0d7f":
            return "ml"
    return "en"


def generate_voice_from_text(text: str, *, lang: str) -> Dict[str, str]:
    cleaned = " ".join(str(text).strip().split())
    # Strip a few common zero-width / direction markers that can confuse tokenizers.
    cleaned = re.sub(r"[\u200b-\u200f\u202a-\u202e]", "", cleaned)
    if not cleaned:
        raise ValueError("text is empty")

    # Use a unique file name to avoid collisions when multiple parts are spoken quickly.
    fd, out_path = tempfile.mkstemp(prefix="alert_", suffix=".mp3")
    try:
        os.close(fd)
    except Exception:
        pass

    # Malayalam sometimes works more reliably with an India TLD.
    tld = "co.in" if lang == "ml" else "com"
    tts = gTTS(text=cleaned, lang=lang, tld=tld, slow=False)
    tts.save(out_path)

    return {"file": os.path.abspath(out_path), "lang": lang, "text": cleaned, "engine": "gTTS"}
