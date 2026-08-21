"""SQLite access. Plain sqlite3, no ORM -- the schema is four columns deep.

The database file lives on a mounted volume in production; losing it means
losing real bookings, so every write goes through a transaction here rather
than being scattered across the routers.
"""

import os
import sqlite3
from contextlib import contextmanager

from . import config

_SCHEMA = os.path.join(os.path.dirname(__file__), "schema.sql")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init() -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_SCHEMA, encoding="utf-8") as fh:
        schema = fh.read()
    conn = _connect()
    try:
        conn.executescript(schema)
    finally:
        conn.close()


@contextmanager
def cursor():
    """Read-only / autocommit access."""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction():
    """Explicit write transaction: commits on success, rolls back on error."""
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()
