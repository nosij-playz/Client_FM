from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import mysql.connector
from mysql.connector import Error as MySQLError


@dataclass(frozen=True)
class MySQLConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    connection_timeout: int = 10


@dataclass(frozen=True)
class MusicRow:
    id: int
    name: str
    link: str
    duration_seconds: Optional[int]


@dataclass(frozen=True)
class AlertRow:
    id: int
    message: str
    severity: str


class MySQLRadioDB:
    def __init__(self, config: MySQLConfig):
        self.config = config

    def _conn(self):
        return mysql.connector.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            connection_timeout=self.config.connection_timeout,
            use_unicode=True,
            charset="utf8mb4",
        )

    def get_next_music_after(self, last_id: int) -> Optional[MusicRow]:
        conn = self._conn()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "SELECT id, name, link, duration_seconds "
                "FROM music "
                "WHERE id > %s "
                "ORDER BY id ASC "
                "LIMIT 1",
                (int(last_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            dur = row.get("duration_seconds")
            return MusicRow(
                id=int(row.get("id") or 0),
                name=str(row.get("name") or ""),
                link=str(row.get("link") or ""),
                duration_seconds=(int(dur) if dur is not None and str(dur).strip() != "" else None),
            )
        finally:
            conn.close()

    def get_music_by_id(self, music_id: int) -> Optional[MusicRow]:
        conn = self._conn()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "SELECT id, name, link, duration_seconds "
                "FROM music "
                "WHERE id = %s "
                "LIMIT 1",
                (int(music_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            dur = row.get("duration_seconds")
            return MusicRow(
                id=int(row.get("id") or 0),
                name=str(row.get("name") or ""),
                link=str(row.get("link") or ""),
                duration_seconds=(int(dur) if dur is not None and str(dur).strip() != "" else None),
            )
        finally:
            conn.close()

    def get_music_max_id(self) -> int:
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(MAX(id), 0) FROM music")
            row = cur.fetchone()
            return int(row[0] if row and row[0] is not None else 0)
        finally:
            conn.close()

    def get_latest_music(self) -> Optional[MusicRow]:
        conn = self._conn()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "SELECT id, name, link, duration_seconds "
                "FROM music "
                "ORDER BY id DESC "
                "LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                return None
            dur = row.get("duration_seconds")
            return MusicRow(
                id=int(row.get("id") or 0),
                name=str(row.get("name") or ""),
                link=str(row.get("link") or ""),
                duration_seconds=(int(dur) if dur is not None and str(dur).strip() != "" else None),
            )
        finally:
            conn.close()

    def get_next_ai_alert_after(self, last_id: int) -> Optional[AlertRow]:
        conn = self._conn()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "SELECT id, message, severity "
                "FROM ai_alert "
                "WHERE id > %s AND message IS NOT NULL AND TRIM(message) != '' "
                "ORDER BY id ASC "
                "LIMIT 1",
                (int(last_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            return AlertRow(
                id=int(row.get("id") or 0),
                message=str(row.get("message") or ""),
                severity=str(row.get("severity") or ""),
            )
        finally:
            conn.close()

    def delete_ai_alert(self, alert_id: int) -> bool:
        """Delete an AI alert by id.

        Returns True if a row was deleted.
        """
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM ai_alert WHERE id=%s", (int(alert_id),))
            conn.commit()
            return bool(cur.rowcount and cur.rowcount > 0)
        finally:
            conn.close()

    def ack_ai_alert(self, alert_id: int) -> bool:
        """Best-effort remove an AI alert after it is played.

        Tries DELETE first. If no row was deleted (or DELETE fails due to
        permissions), falls back to clearing the message.
        """
        try:
            if self.delete_ai_alert(alert_id):
                return True
        except MySQLError:
            pass

        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE ai_alert SET message='' WHERE id=%s", (int(alert_id),))
            conn.commit()
            return bool(cur.rowcount and cur.rowcount > 0)
        finally:
            conn.close()

    def pop_next_user_alert(self) -> Optional[AlertRow]:
        """Fetch and delete the next user alert.

        Prefer using `get_next_user_alert()` + `delete_user_alert()` so the
        message is only deleted after it is successfully spoken/played.
        """
        alert = self.get_next_user_alert()
        if not alert:
            return None
        self.delete_user_alert(alert.id)
        return alert

    def get_next_user_alert(self) -> Optional[AlertRow]:
        """Fetch the next user alert without deleting it."""
        return self.get_next_user_alert_after(0)

    def get_next_user_alert_after(self, last_id: int) -> Optional[AlertRow]:
        """Fetch the next user alert after last_id without deleting it."""
        conn = self._conn()
        try:
            cur = conn.cursor(dictionary=True)
            try:
                cur.execute(
                    "SELECT id, message "
                    "FROM user_alert "
                    "WHERE id > %s AND message IS NOT NULL AND TRIM(message) != '' "
                    "AND (last_updated IS NULL OR last_updated >= (UTC_TIMESTAMP() - INTERVAL 1 HOUR)) "
                    "ORDER BY id ASC "
                    "LIMIT 1",
                    (int(last_id),),
                )
            except MySQLError:
                # Some schemas don't have last_updated; retry without it.
                cur.execute(
                    "SELECT id, message "
                    "FROM user_alert "
                    "WHERE id > %s AND message IS NOT NULL AND TRIM(message) != '' "
                    "ORDER BY id ASC "
                    "LIMIT 1",
                    (int(last_id),),
                )
            row = cur.fetchone()
            if not row:
                return None

            return AlertRow(
                id=int(row.get("id") or 0),
                message=str(row.get("message") or ""),
                severity="",
            )
        finally:
            conn.close()

    def get_server_status(self) -> Optional[str]:
        """Return current server status string from `status_server` table.

        Expected values: 'net', 'both', or anything else (treated as disabled).
        Best-effort: returns None if the table/column doesn't exist or on errors.
        """
        conn = self._conn()
        try:
            cur = conn.cursor(dictionary=True)
            # Common patterns: either a single-row table or latest-row semantics.
            try:
                cur.execute(
                    "SELECT status FROM status_server ORDER BY id DESC LIMIT 1"
                )
            except MySQLError:
                cur.execute(
                    "SELECT status FROM status_server LIMIT 1"
                )
            row = cur.fetchone()
            if not row:
                return None
            val = row.get("status")
            return str(val).strip().lower() if val is not None else None
        except MySQLError:
            return None
        finally:
            conn.close()

    def delete_user_alert(self, alert_id: int) -> bool:
        """Delete a user alert by id.

        Returns True if a row was deleted.
        """
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM user_alert WHERE id=%s", (int(alert_id),))
            conn.commit()
            return bool(cur.rowcount and cur.rowcount > 0)
        finally:
            conn.close()

    def ack_user_alert(self, alert_id: int) -> bool:
        """Best-effort remove a user alert after it is played.

        Tries DELETE first. If no row was deleted (or DELETE fails due to
        permissions), falls back to clearing the message.
        """
        try:
            if self.delete_user_alert(alert_id):
                return True
        except MySQLError:
            pass

        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE user_alert SET message='' WHERE id=%s", (int(alert_id),))
            conn.commit()
            return bool(cur.rowcount and cur.rowcount > 0)
        finally:
            conn.close()
