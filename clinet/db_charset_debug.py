from __future__ import annotations

import argparse
import os
from typing import Any

import mysql.connector


def _mask(s: str) -> str:
	if not s:
		return ""
	if len(s) <= 4:
		return "****"
	return s[:2] + "****" + s[-2:]


def _print_kv(title: str, rows: list[tuple[Any, ...]]):
	print(f"\n== {title} ==")
	for row in rows:
		print("  ", *row)


def main() -> None:
	parser = argparse.ArgumentParser(description="Debug MySQL charset/collation for Malayalam alerts")
	parser.add_argument("--host", default=os.getenv("MYSQL_HOST", ""))
	parser.add_argument("--port", type=int, default=int(os.getenv("MYSQL_PORT", "14239")))
	parser.add_argument("--user", default=os.getenv("MYSQL_USER", ""))
	parser.add_argument("--password", default=os.getenv("MYSQL_PASSWORD", ""))
	parser.add_argument("--database", default=os.getenv("MYSQL_DATABASE", "defaultdb"))
	parser.add_argument("--table", choices=["ai_alert", "user_alert"], default="ai_alert")
	parser.add_argument("--id", type=int, default=0, help="Optional alert id to inspect")

	args = parser.parse_args()

	if not args.host or not args.user or not args.password:
		raise SystemExit(
			"Missing MYSQL connection info. Set env vars MYSQL_HOST/MYSQL_USER/MYSQL_PASSWORD (recommended)."
		)

	print("Connecting:")
	print(f"  host={args.host}")
	print(f"  port={args.port}")
	print(f"  user={args.user}")
	print(f"  password={_mask(args.password)}")
	print(f"  database={args.database}")

	conn = mysql.connector.connect(
		host=args.host,
		port=args.port,
		user=args.user,
		password=args.password,
		database=args.database,
		use_unicode=True,
		charset="utf8mb4",
	)
	try:
		cur = conn.cursor()

		cur.execute(
			"SELECT @@version, @@character_set_server, @@collation_server, "
			"@@character_set_database, @@collation_database"
		)
		_print_kv("Server", [cur.fetchone()])

		cur.execute(
			"SELECT @@character_set_client, @@collation_connection, "
			"@@character_set_connection, @@character_set_results"
		)
		_print_kv("Session", [cur.fetchone()])

		cur.execute("SHOW TABLE STATUS LIKE %s", (args.table,))
		row = cur.fetchone()
		if row:
			# Name is col 0, Collation is col 14
			_print_kv("Table status (Name, Collation)", [(row[0], row[14])])

		cur.execute(f"SHOW FULL COLUMNS FROM {args.table}")
		cols = cur.fetchall() or []
		# Field, Type, Collation
		simplified = [(c[0], c[1], c[2]) for c in cols]
		_print_kv("Columns (Field, Type, Collation)", simplified)

		# Inspect one message row
		if args.id and args.id > 0:
			cur.execute(
				f"SELECT id, message, HEX(message) AS hex_msg, LENGTH(message) AS bytes_len, CHAR_LENGTH(message) AS chars_len "
				f"FROM {args.table} WHERE id=%s",
				(int(args.id),),
			)
		else:
			cur.execute(
				f"SELECT id, message, HEX(message) AS hex_msg, LENGTH(message) AS bytes_len, CHAR_LENGTH(message) AS chars_len "
				f"FROM {args.table} ORDER BY id DESC LIMIT 1"
			)
		msg_row = cur.fetchone()
		if msg_row:
			alert_id, message, hex_msg, bytes_len, chars_len = msg_row
			print("\n== Sample message ==")
			print(f"  id={alert_id}")
			print(f"  repr={message!r}")
			print(f"  bytes_len={bytes_len} chars_len={chars_len}")
			print(f"  hex={hex_msg}")
		else:
			print("\n== Sample message ==\n  (no rows found)")

	finally:
		conn.close()


if __name__ == "__main__":
	main()