"""DEV-177: тесты EMA-агрегации adaptive weights.

6 сценариев:
1. Смена направления (hl=20): 50× +1R → 50× -1R. full ≈ 0, EMA << -0.4.
2. Инерция full-history: 500× +0.5R → 50× -1R. full ≈ +0.36, EMA уходит в минус.
3. Формат выхода совместим с by_signal_type().
4. data_era filter: pre_157 сделки игнорируются при data_era='post_fix'.
5. Пустая БД: возвращает пустой список, не падает.
6. Порог _MIN_TRADES=20: при 10 сделках update_signal_weights не меняет вес.
"""
from __future__ import annotations

import gc
import json
import os
import sqlite3
import tempfile
import time
import unittest

from core.trading.performance_engine import PerformanceEngine


def _make_tmp_db() -> str:
    fd, path = tempfile.mkstemp(prefix="swema_", suffix=".db")
    os.close(fd)
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE simulated_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_type TEXT,
                status TEXT,
                R_multiple REAL,
                profit_pct REAL,
                features_json TEXT,
                closed_at TEXT
            )
        """)
        conn.commit()
    return path


def _try_remove(path: str) -> None:
    """Windows иногда держит файл SQLite открытым — отложенный remove с retry."""
    gc.collect()
    for _ in range(5):
        try:
            os.remove(path)
            return
        except (PermissionError, OSError):
            time.sleep(0.1)
    # Пропускаем — tempfile cleanup подберёт позже


def _insert(db: str, trades):
    """trades = list[(signal_type, status, R, pnl, data_era, closed_at)]."""
    with sqlite3.connect(db) as conn:
        cur = conn.cursor()
        for st, status, r, pnl, era, closed_at in trades:
            fj = json.dumps({"data_era": era}) if era else None
            cur.execute(
                """INSERT INTO simulated_trades
                   (signal_type, status, R_multiple, profit_pct, features_json, closed_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (st, status, r, pnl, fj, closed_at),
            )
        conn.commit()


class EMAAdaptiveWeightsTests(unittest.TestCase):

    def test_1_direction_change_ema_reacts_faster(self):
        """hl=20, 50× +1R → 50× -1R: full≈0, EMA < -0.4 (реактивна)."""
        db = _make_tmp_db()
        try:
            trades = []
            for i in range(50):
                trades.append(("pivot_reversal", "TP", 1.0, 2.0, "post_fix",
                               f"2026-04-15 {i // 60:02d}:{i % 60:02d}:00"))
            for i in range(50):
                trades.append(("pivot_reversal", "SL", -1.0, -2.0, "post_fix",
                               f"2026-04-18 {i // 60:02d}:{i % 60:02d}:00"))
            _insert(db, trades)

            pe = PerformanceEngine(db)
            full = pe.by_signal_type()
            ema = pe.by_signal_type_ema(half_life=20.0, data_era="post_fix")

            self.assertAlmostEqual(full[0]["avg_r"], 0.0, delta=0.1)
            self.assertLess(ema[0]["avg_r"], -0.4,
                            f"EMA(hl=20) should be << 0, got {ema[0]['avg_r']}")
        finally:
            _try_remove(db)

    def test_2_inertia_full_history_vs_ema(self):
        """500× +0.5R + 50× -1R, hl=50. full≈+0.36, EMA уходит в минус."""
        db = _make_tmp_db()
        try:
            trades = []
            for i in range(500):
                day = (i // 50) + 1  # 10 дней: 01..10
                trades.append(("wt_signal", "TP", 0.5, 1.0, "post_fix",
                               f"2026-03-{day:02d} "
                               f"{(i % 50) // 60:02d}:{i % 60:02d}:00"))
            for i in range(50):
                trades.append(("wt_signal", "SL", -1.0, -2.0, "post_fix",
                               f"2026-04-18 {i // 60:02d}:{i % 60:02d}:00"))
            _insert(db, trades)

            pe = PerformanceEngine(db)
            full = pe.by_signal_type()
            ema = pe.by_signal_type_ema(half_life=50.0, data_era="post_fix")

            full_r = full[0]["avg_r"]
            ema_r = ema[0]["avg_r"]
            self.assertGreater(full_r, 0.3,
                               f"full-history должен быть >0.3, получили {full_r}")
            self.assertLess(ema_r, 0.0,
                            f"EMA должна быть отрицательной, получили {ema_r}")
            self.assertLess(ema_r, full_r - 0.4,
                            f"EMA={ema_r} недостаточно ниже full={full_r}")
        finally:
            _try_remove(db)

    def test_3_format_compatible_with_by_signal_type(self):
        """Ключи выхода EMA совпадают с by_signal_type()."""
        db = _make_tmp_db()
        try:
            _insert(db, [
                ("pivot_reversal", "TP", 1.0, 2.0, "post_fix", "2026-04-15 10:00:00"),
                ("pivot_reversal", "SL", -1.0, -2.0, "post_fix", "2026-04-16 10:00:00"),
            ])
            pe = PerformanceEngine(db)
            full_keys = set(pe.by_signal_type()[0].keys())
            ema_keys = set(pe.by_signal_type_ema(half_life=50.0,
                                                  data_era="post_fix")[0].keys())
            expected = {"signal_type", "total", "tp_count", "tsl_count", "sl_count",
                        "wins", "losses", "win_rate", "avg_r", "avg_profit_pct"}
            self.assertTrue(expected.issubset(full_keys), full_keys)
            self.assertTrue(expected.issubset(ema_keys), ema_keys)
        finally:
            _try_remove(db)

    def test_4_data_era_filter_ignores_pre_fix(self):
        """pre_157 сделки фильтруются при data_era='post_fix'."""
        db = _make_tmp_db()
        try:
            trades = []
            for i in range(30):
                trades.append(("pivot_reversal", "SL", -5.0, -10.0, "pre_157",
                               f"2026-03-20 {i:02d}:00:00"))
            for i in range(30):
                trades.append(("pivot_reversal", "TP", 1.0, 2.0, "post_fix",
                               f"2026-04-15 {i:02d}:00:00"))
            _insert(db, trades)

            pe = PerformanceEngine(db)
            ema_filtered = pe.by_signal_type_ema(half_life=50.0, data_era="post_fix")
            ema_all = pe.by_signal_type_ema(half_life=50.0, data_era=None)

            self.assertEqual(ema_filtered[0]["total"], 30)
            self.assertGreater(ema_filtered[0]["avg_r"], 0.5)
            self.assertEqual(ema_all[0]["total"], 60)
            self.assertLess(ema_all[0]["avg_r"], ema_filtered[0]["avg_r"])
        finally:
            _try_remove(db)

    def test_5_empty_db_returns_empty_list(self):
        db = _make_tmp_db()
        try:
            pe = PerformanceEngine(db)
            self.assertEqual(pe.by_signal_type_ema(half_life=50.0,
                                                    data_era="post_fix"), [])
            self.assertEqual(pe.by_signal_type_ema(half_life=50.0,
                                                    data_era=None), [])
        finally:
            _try_remove(db)

    def test_6_below_min_trades_weight_unchanged(self):
        """10 сделок (<20) → update_signal_weights не меняет вес."""
        from core.trading_intelligence import TradingIntelligence
        from core.signal_models import SignalType

        db = _make_tmp_db()
        try:
            trades = [
                ("pivot_reversal", "TP", 1.0, 2.0, "post_fix",
                 f"2026-04-15 {i:02d}:00:00")
                for i in range(10)
            ]
            _insert(db, trades)

            ti = object.__new__(TradingIntelligence)
            ti._db_path = db
            ti.signal_weights = {SignalType.PIVOT_REVERSAL: 0.20}
            ti._base_signal_weights = {SignalType.PIVOT_REVERSAL: 0.20}
            ti.update_signal_weights()
            self.assertAlmostEqual(ti.signal_weights[SignalType.PIVOT_REVERSAL],
                                   0.20, places=3)
        finally:
            _try_remove(db)


if __name__ == "__main__":
    import sys
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(EMAAdaptiveWeightsTests)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
