import sqlite3
from datetime import datetime
from config import DB_PATH


def _conn():
    return sqlite3.connect(str(DB_PATH))


def init_db():
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id  INTEGER PRIMARY KEY,
                username     TEXT,
                created_at   TEXT DEFAULT (datetime('now'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id        INTEGER NOT NULL,
                receipt_number     TEXT NOT NULL,
                account            TEXT NOT NULL DEFAULT 'primary',
                last_status        TEXT,
                last_updated_at    TEXT,
                last_events_hash   TEXT,
                last_checked       TEXT,
                UNIQUE(telegram_id, receipt_number),
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            )
        """)
        # Migrate existing tables that lack the account column
        try:
            con.execute("ALTER TABLE cases ADD COLUMN account TEXT NOT NULL DEFAULT 'primary'")
        except Exception:
            pass
        con.commit()


def upsert_user(telegram_id: int, username: str):
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO users (telegram_id, username) VALUES (?, ?)",
            (telegram_id, username or ""),
        )
        con.commit()


def add_case(telegram_id: int, receipt_number: str, account: str = "primary") -> bool:
    """Returns True if added, False if already exists."""
    try:
        with _conn() as con:
            con.execute(
                "INSERT INTO cases (telegram_id, receipt_number, account) VALUES (?, ?, ?)",
                (telegram_id, receipt_number.upper(), account),
            )
            con.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def remove_case(telegram_id: int, receipt_number: str) -> bool:
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM cases WHERE telegram_id = ? AND receipt_number = ?",
            (telegram_id, receipt_number.upper()),
        )
        con.commit()
        return cur.rowcount > 0


def get_user_cases(telegram_id: int) -> list:
    with _conn() as con:
        con.row_factory = sqlite3.Row
        cur = con.execute("SELECT * FROM cases WHERE telegram_id = ?", (telegram_id,))
        return [dict(r) for r in cur.fetchall()]


def get_all_cases() -> list:
    with _conn() as con:
        con.row_factory = sqlite3.Row
        cur = con.execute("SELECT * FROM cases")
        return [dict(r) for r in cur.fetchall()]


def update_case_status(receipt_number: str, status: str, updated_at: str, events_hash: str):
    with _conn() as con:
        con.execute(
            """UPDATE cases
               SET last_status = ?, last_updated_at = ?, last_events_hash = ?, last_checked = ?
               WHERE receipt_number = ?""",
            (status, updated_at, events_hash, datetime.utcnow().isoformat(), receipt_number),
        )
        con.commit()
