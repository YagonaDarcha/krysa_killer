import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chats (
    chat_id       INTEGER PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT '',
    event_active  INTEGER NOT NULL DEFAULT 0,
    event_started REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS players (
    chat_id   INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    name      TEXT NOT NULL,
    points    INTEGER NOT NULL DEFAULT 0,
    deaths    INTEGER NOT NULL DEFAULT 0,
    alive     INTEGER NOT NULL DEFAULT 1,
    spins     INTEGER NOT NULL DEFAULT 0,
    jackpots  INTEGER NOT NULL DEFAULT 0,
    last_spin REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS mutes (
    chat_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    until      REAL NOT NULL,
    restricted INTEGER NOT NULL DEFAULT 0,
    eliminated INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS legends (
    user_id       INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    wins          INTEGER NOT NULL DEFAULT 0,
    killer_phrase TEXT NOT NULL DEFAULT '',
    rat_phrase    TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pending (
    token      TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    chat_id    INTEGER NOT NULL,
    target_id  INTEGER NOT NULL DEFAULT 0,
    answer     INTEGER NOT NULL DEFAULT -1,
    options    TEXT NOT NULL DEFAULT '[]',
    header     TEXT NOT NULL DEFAULT '',
    message_id INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL,
    started       REAL NOT NULL,
    ended         REAL NOT NULL DEFAULT 0,
    planned       INTEGER NOT NULL DEFAULT 0,
    paused        REAL NOT NULL DEFAULT 0,
    pauses        INTEGER NOT NULL DEFAULT 0,
    reason        TEXT NOT NULL DEFAULT '',
    winner_id     INTEGER NOT NULL DEFAULT 0,
    winner_name   TEXT NOT NULL DEFAULT '',
    winner_points INTEGER NOT NULL DEFAULT 0,
    players       INTEGER NOT NULL DEFAULT 0,
    spins         INTEGER NOT NULL DEFAULT 0,
    jackpots      INTEGER NOT NULL DEFAULT 0,
    points_total  INTEGER NOT NULL DEFAULT 0,
    killer_visits INTEGER NOT NULL DEFAULT 0,
    killer_hits   INTEGER NOT NULL DEFAULT 0,
    rat_visits    INTEGER NOT NULL DEFAULT 0,
    rat_stolen    INTEGER NOT NULL DEFAULT 0,
    rat_caught    INTEGER NOT NULL DEFAULT 0,
    nfts          INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS prizes (
    place INTEGER PRIMARY KEY,
    kind  TEXT NOT NULL,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id  INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    name     TEXT NOT NULL,
    points   INTEGER NOT NULL,
    finished REAL NOT NULL
);
"""

_conn: sqlite3.Connection | None = None


def init(path: Path) -> None:
    global _conn
    path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(path, isolation_level=None)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.executescript(SCHEMA)
    _add_column("players", "last_msg", "INTEGER NOT NULL DEFAULT 0")
    _add_column("players", "username", "TEXT NOT NULL DEFAULT ''")
    _add_column("chats", "event_ends", "REAL NOT NULL DEFAULT 0")
    _add_column("chats", "pin_msg", "INTEGER NOT NULL DEFAULT 0")
    _add_column("chats", "paused_at", "REAL NOT NULL DEFAULT 0")
    _add_column("chats", "paused_until", "REAL NOT NULL DEFAULT 0")
    _add_column("chats", "current_event", "INTEGER NOT NULL DEFAULT 0")
    _add_column("chats", "bot_in", "INTEGER NOT NULL DEFAULT 1")
    _add_column("chats", "start_msg", "INTEGER NOT NULL DEFAULT 0")


def _add_column(table: str, column: str, definition: str) -> None:
    """Добавляет колонку в уже существующую базу (миграция без потери данных)."""
    columns = {row["name"] for row in _conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        _conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def run(sql: str, *args) -> sqlite3.Cursor:
    return _conn.execute(sql, args)


def all(sql: str, *args) -> list[sqlite3.Row]:
    return _conn.execute(sql, args).fetchall()


def one(sql: str, *args) -> sqlite3.Row | None:
    return _conn.execute(sql, args).fetchone()
