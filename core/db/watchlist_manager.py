import sqlite3
import logging
from typing import List

logger = logging.getLogger(__name__)


class WatchlistManager:
    """Управление watchlist пользователей (избранные торговые пары)."""

    def __init__(self, db_path: str = "subscriptions.db"):
        self.db_path = db_path
        self._create_table()

    def _create_table(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS watchlist (
                        user_id  INTEGER NOT NULL,
                        symbol   TEXT    NOT NULL,
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (user_id, symbol)
                    )
                """)
        except Exception:
            logger.exception("WatchlistManager._create_table")

    def add(self, user_id: int, symbol: str) -> bool:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO watchlist (user_id, symbol) VALUES (?,?)",
                    (user_id, symbol),
                )
            return True
        except Exception:
            logger.exception("watchlist.add user=%s sym=%s", user_id, symbol)
            return False

    def remove(self, user_id: int, symbol: str) -> bool:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "DELETE FROM watchlist WHERE user_id=? AND symbol=?",
                    (user_id, symbol),
                )
            return True
        except Exception:
            logger.exception("watchlist.remove user=%s sym=%s", user_id, symbol)
            return False

    def get(self, user_id: int) -> List[str]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.execute(
                    "SELECT symbol FROM watchlist WHERE user_id=? ORDER BY added_at DESC",
                    (user_id,),
                )
                return [r[0] for r in cur.fetchall()]
        except Exception:
            logger.exception("watchlist.get user=%s", user_id)
            return []

    def count(self, user_id: int) -> int:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.execute(
                    "SELECT COUNT(*) FROM watchlist WHERE user_id=?",
                    (user_id,),
                )
                return cur.fetchone()[0]
        except Exception:
            return 0
