"""MySQL client player.

Polls MySQL tables:
- `music`: plays YouTube link for `duration_seconds`
- `ai_alert`: speaks the message (no DB delete; expires server-side)
- `user_alert`: speaks the message and deletes row (queue semantics)
"""
