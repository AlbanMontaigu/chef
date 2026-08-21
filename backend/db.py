"""SQLite access. Plain sqlite3, no ORM -- the schema is four columns deep.

The database file lives on a mounted volume in production; losing it means
losing real bookings, so every write goes through a transaction here rather
than being scattered across the routers.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager

from . import config

log = logging.getLogger("chef.db")

_SCHEMA = os.path.join(os.path.dirname(__file__), "schema.sql")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


# Colonnes ajoutées à des tables qui existaient déjà en production.
# `CREATE TABLE IF NOT EXISTS` ne touche pas une table présente : sans ceci,
# une base déployée garderait le schéma du jour de sa création et le code
# neuf planterait dessus. Chaque entrée reste dans schema.sql, qui demeure la
# description du schéma ; cette liste ne sert qu'au rattrapage.
_ADDED_COLUMNS = (
    ("slots", "demo", "INTEGER NOT NULL DEFAULT 0"),
    ("bookings", "formula_id", "INTEGER REFERENCES formulas(id) ON DELETE SET NULL"),
    ("bookings", "demo", "INTEGER NOT NULL DEFAULT 0"),
    ("bookings", "city", "TEXT NOT NULL DEFAULT ''"),
    ("bookings", "diets", "TEXT NOT NULL DEFAULT '[]'"),
    ("bookings", "travel_seconds", "INTEGER"),
    ("bookings", "travel_meters", "INTEGER"),
    ("bookings", "travel_error", "TEXT NOT NULL DEFAULT ''"),
    ("bookings", "travel_label", "TEXT NOT NULL DEFAULT ''"),
    ("bookings", "travel_approx", "INTEGER NOT NULL DEFAULT 0"),
    ("bookings", "travel_at", "TEXT"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, ddl in _ADDED_COLUMNS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # table absente : schema.sql vient de la créer avec la colonne
        if column not in existing:
            log.info("migration: %s.%s ajoutée", table, column)
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            if (table, column) == ("bookings", "demo"):
                # Sur une base antérieure, toute réservation posée sur un
                # créneau de démonstration vient forcément du semis : c'est le
                # seul à en créer. Les marquer maintenant évite qu'elles
                # passent pour réelles et bloquent le semis à jamais.
                conn.execute(
                    "UPDATE bookings SET demo = 1 WHERE slot_id IN "
                    "(SELECT id FROM slots WHERE demo = 1)")


def init() -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_SCHEMA, encoding="utf-8") as fh:
        schema = fh.read()
    conn = _connect()
    try:
        conn.executescript(schema)
        _migrate(conn)
    finally:
        conn.close()


def meta_get(key: str, default: str = "") -> str:
    with cursor() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Écrit dans la transaction du appelant : le marqueur et ce qu'il décrit
    doivent être posés ensemble ou pas du tout."""
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


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
