"""Deprecated module.

`clinet` was refactored to be fully standalone (no imports from the main repo).
Use `clinet/mysql_client.py` for MySQL access.
"""

from .mysql_client import AlertRow, MusicRow, MySQLRadioDB  # re-export
