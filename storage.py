"""SQLite хранит только ID известных личных чатов, без текста и геолокации."""

from pathlib import Path
import sqlite3


class ChatStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS chats (
                    chat_id INTEGER PRIMARY KEY,
                    active INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def remember(self, chat_id: int, chat_type: str) -> None:
        if chat_type != "private":
            return
        with self._connect() as db:
            db.execute("""
                INSERT INTO chats(chat_id, active) VALUES (?, 1)
                ON CONFLICT(chat_id) DO UPDATE SET
                    active=1, updated_at=CURRENT_TIMESTAMP
            """, (int(chat_id),))

    def deactivate(self, chat_id: int) -> None:
        with self._connect() as db:
            db.execute("UPDATE chats SET active=0, updated_at=CURRENT_TIMESTAMP WHERE chat_id=?",
                       (int(chat_id),))

    def active_ids(self) -> list[int]:
        with self._connect() as db:
            return [row[0] for row in db.execute("SELECT chat_id FROM chats WHERE active=1 ORDER BY chat_id")]
