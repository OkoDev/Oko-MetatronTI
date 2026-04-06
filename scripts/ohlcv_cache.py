"""
DEV-32: SQLite кэш OHLCV данных для бэктеста.

Поведение:
  - При первом запросе: скачать из API → сохранить в кэш
  - При повторном: вернуть из кэша (без API-вызова)
  - Инкрементальное обновление: если есть хвост [X, Y] но нужен [X, end_ms]
    → докачать только [Y+1, end_ms], сохранить, вернуть полный диапазон

Файл кэша: ohlcv_cache.db в корне проекта.
Ключ: (symbol, timeframe, time_ms) — UNIQUE.
"""
import datetime
import logging
import sqlite3
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_DB = Path(__file__).parent.parent / "ohlcv_cache.db"


class OHLCVCache:
    """SQLite-кэш OHLCV свечей для бэктестинга."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = str(db_path or _DEFAULT_DB)
        self._init_db()

    # ── Инициализация ────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ohlcv_cache (
                    symbol    TEXT    NOT NULL,
                    timeframe TEXT    NOT NULL,
                    time      INTEGER NOT NULL,
                    open      REAL    NOT NULL,
                    high      REAL    NOT NULL,
                    low       REAL    NOT NULL,
                    close     REAL    NOT NULL,
                    volume    REAL    NOT NULL,
                    PRIMARY KEY (symbol, timeframe, time)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sym_tf_time "
                "ON ohlcv_cache(symbol, timeframe, time)"
            )

    # ── Чтение ───────────────────────────────────────────────────────────────

    def get_coverage(self, symbol: str, timeframe: str) -> Tuple[Optional[int], Optional[int]]:
        """Возвращает (min_time_ms, max_time_ms) для (symbol, timeframe). (None,None) если пусто."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MIN(time), MAX(time) FROM ohlcv_cache WHERE symbol=? AND timeframe=?",
                (symbol, timeframe),
            ).fetchone()
        if row and row[0] is not None:
            return int(row[0]), int(row[1])
        return None, None

    def read(self, symbol: str, timeframe: str, since_ms: int, until_ms: int) -> Optional[pd.DataFrame]:
        """Читает диапазон [since_ms, until_ms] из кэша.
        Возвращает DataFrame с колонками time,open,high,low,close,volume или None.
        """
        with self._conn() as conn:
            df = pd.read_sql_query(
                "SELECT time, open, high, low, close, volume FROM ohlcv_cache "
                "WHERE symbol=? AND timeframe=? AND time>=? AND time<=? ORDER BY time",
                conn,
                params=(symbol, timeframe, since_ms, until_ms),
            )
        if df.empty:
            return None
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.reset_index(drop=True)

    # ── Запись ───────────────────────────────────────────────────────────────

    def save(self, symbol: str, timeframe: str, df: pd.DataFrame):
        """Сохраняет свечи в кэш (INSERT OR REPLACE по PRIMARY KEY)."""
        if df is None or df.empty:
            return
        rows = [
            (
                symbol, timeframe, int(row["time"]),
                float(row["open"]), float(row["high"]),
                float(row["low"]), float(row["close"]), float(row["volume"]),
            )
            for _, row in df.iterrows()
        ]
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO ohlcv_cache"
                "(symbol, timeframe, time, open, high, low, close, volume) "
                "VALUES (?,?,?,?,?,?,?,?)",
                rows,
            )
        logger.debug("[cache] saved %d bars for %s %s", len(rows), symbol, timeframe)

    # ── Статистика ───────────────────────────────────────────────────────────

    def stats(self) -> list[str]:
        """Статистика кэша: список строк (symbol, timeframe, count, from→to)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT symbol, timeframe, COUNT(*), MIN(time), MAX(time) "
                "FROM ohlcv_cache GROUP BY symbol, timeframe ORDER BY symbol, timeframe"
            ).fetchall()

        result = []
        for r in rows:
            from_dt = _ms_to_date(r[3])
            to_dt   = _ms_to_date(r[4])
            result.append(f"  {r[0]:25s} {r[1]:5s}  {r[2]:7d} bars  {from_dt} → {to_dt}")
        return result

    def clear(self, symbol: Optional[str] = None, timeframe: Optional[str] = None):
        """Очищает кэш (весь, по символу, или по символу+ТФ)."""
        with self._conn() as conn:
            if symbol and timeframe:
                conn.execute(
                    "DELETE FROM ohlcv_cache WHERE symbol=? AND timeframe=?",
                    (symbol, timeframe),
                )
            elif symbol:
                conn.execute("DELETE FROM ohlcv_cache WHERE symbol=?", (symbol,))
            else:
                conn.execute("DELETE FROM ohlcv_cache")
        logger.info("[cache] cleared (symbol=%s timeframe=%s)", symbol, timeframe)


# ── Singleton ────────────────────────────────────────────────────────────────

_cache_instance: Optional[OHLCVCache] = None


def get_cache(db_path: Optional[Path] = None) -> OHLCVCache:
    """Возвращает глобальный singleton кэша (ленивая инициализация)."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = OHLCVCache(db_path)
    return _cache_instance


# ── Утилиты ──────────────────────────────────────────────────────────────────

def _ms_to_date(ts_ms: Optional[int]) -> str:
    if ts_ms is None:
        return "-"
    return datetime.datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")


# ── CLI для просмотра статистики ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    cache = get_cache()

    if len(sys.argv) > 1 and sys.argv[1] == "clear":
        sym = sys.argv[2] if len(sys.argv) > 2 else None
        tf  = sys.argv[3] if len(sys.argv) > 3 else None
        cache.clear(sym, tf)
        print("Кэш очищен.")
    else:
        lines = cache.stats()
        if lines:
            print(f"OHLCV кэш ({cache.db_path}):")
            print("\n".join(lines))
        else:
            print("Кэш пустой.")
