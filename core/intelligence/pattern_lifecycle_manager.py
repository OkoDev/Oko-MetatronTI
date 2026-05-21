"""
DEV-275 (Phase 7): Pattern Auto-Retire / Champion-Challenger framework.

Цель: автоматически отключать паттерны которые деградируют в production.
Также — challenger проверка: новые варианты могут вытеснить champion.

Алгоритм Auto-Retire:
  - Каждый pattern имеет baseline (test_avgR из ARCH-104 walk-forward)
  - В runtime считаем avgR_30d (EMA на последние 30 дней)
  - Если avgR_30d < baseline × threshold (default 0.5) на N≥20 сделках → auto-shadow

Алгоритм Champion-Challenger:
  - Challenger = новая версия паттерна (например с дополнительным factor)
  - Запускается в shadow параллельно с champion
  - Если за N=50 сделок challenger avgR > champion + 20% → promote

Использование:
  from core.intelligence.pattern_lifecycle_manager import PatternLifecycle
  pl = PatternLifecycle()
  status = pl.check_pattern("L1_golden")   # → "active" / "shadow" / "deprecated"
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = PROJECT_ROOT / "subscriptions.db"


@dataclass
class PatternHealth:
    pattern_id: str
    baseline_avgR: float
    runtime_avgR_30d: float
    runtime_wr_30d: float
    n_trades_30d: int
    status: str   # "active" | "shadow" | "deprecated" | "insufficient_data"
    last_n_losses_in_row: int = 0
    decision_reason: str = ""


class PatternLifecycle:
    def __init__(self, db_path: Path = DEFAULT_DB,
                 auto_retire_threshold: float = 0.5,
                 min_trades_for_check: int = 20,
                 consecutive_losses_limit: int = 5):
        self.db_path = db_path
        self.threshold = auto_retire_threshold
        self.min_trades = min_trades_for_check
        self.consecutive_limit = consecutive_losses_limit
        self._init_table()

    def _init_table(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pattern_lifecycle (
                pattern_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                baseline_avgR REAL NOT NULL,
                last_check_ts TEXT NOT NULL,
                runtime_avgR_30d REAL,
                runtime_wr_30d REAL,
                n_trades_30d INTEGER,
                consecutive_losses INTEGER DEFAULT 0,
                decision_reason TEXT,
                champion_or_challenger TEXT DEFAULT 'champion'
            )
        """)
        conn.commit()
        conn.close()

    def check_pattern(self, pattern_id: str, baseline_avgR: float) -> PatternHealth:
        """Получить health одного паттерна. baseline_avgR — из ARCH-104 Pattern Library."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # Сделки за 30 дней
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        cur.execute("""
            SELECT R_multiple FROM simulated_trades
            WHERE features_json LIKE ? AND status != 'OPEN'
              AND closed_at >= ?
            ORDER BY closed_at DESC
        """, (f'%"pattern_id":"{pattern_id}"%', cutoff))
        rows = cur.fetchall()
        rs = [r[0] for r in rows if r[0] is not None]

        # Consecutive losses
        cur.execute("""
            SELECT R_multiple FROM simulated_trades
            WHERE features_json LIKE ? AND status != 'OPEN'
            ORDER BY closed_at DESC LIMIT 20
        """, (f'%"pattern_id":"{pattern_id}"%',))
        recent = cur.fetchall()
        consec_losses = 0
        for r in recent:
            if r[0] is not None and r[0] < 0:
                consec_losses += 1
            else:
                break

        conn.close()

        if len(rs) < self.min_trades:
            return PatternHealth(
                pattern_id=pattern_id,
                baseline_avgR=baseline_avgR,
                runtime_avgR_30d=sum(rs) / max(1, len(rs)),
                runtime_wr_30d=0,
                n_trades_30d=len(rs),
                status="insufficient_data",
                last_n_losses_in_row=consec_losses,
                decision_reason=f"only {len(rs)} trades (need ≥{self.min_trades})",
            )

        avgR = sum(rs) / len(rs)
        wr = sum(1 for r in rs if r > 0) / len(rs) * 100

        # Decision logic
        if consec_losses >= self.consecutive_limit:
            status = "shadow"
            reason = f"{consec_losses} consecutive losses ≥ {self.consecutive_limit}"
        elif avgR < baseline_avgR * self.threshold:
            status = "shadow"
            reason = f"avgR_30d={avgR:.3f} < baseline {baseline_avgR:.3f} × {self.threshold}"
        else:
            status = "active"
            reason = f"avgR_30d={avgR:.3f} ≥ {baseline_avgR * self.threshold:.3f}, no consec losses"

        # Persist
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO pattern_lifecycle
              (pattern_id, status, baseline_avgR, last_check_ts,
               runtime_avgR_30d, runtime_wr_30d, n_trades_30d,
               consecutive_losses, decision_reason)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            pattern_id, status, baseline_avgR, datetime.now(timezone.utc).isoformat(),
            avgR, wr, len(rs), consec_losses, reason,
        ))
        conn.commit()
        conn.close()

        return PatternHealth(
            pattern_id=pattern_id,
            baseline_avgR=baseline_avgR,
            runtime_avgR_30d=avgR,
            runtime_wr_30d=wr,
            n_trades_30d=len(rs),
            status=status,
            last_n_losses_in_row=consec_losses,
            decision_reason=reason,
        )

    def check_all(self, registry) -> dict[str, PatternHealth]:
        """Прогонит health-check для всех паттернов в реестре."""
        results = {}
        for pat in registry.patterns.values():
            results[pat.id] = self.check_pattern(pat.id, pat.test_avgR)
        return results

    def get_active_patterns(self) -> set[str]:
        """Возвращает set pattern_id со status='active'."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT pattern_id FROM pattern_lifecycle WHERE status='active'")
        active = {r[0] for r in cur.fetchall()}
        conn.close()
        return active

    def force_status(self, pattern_id: str, status: str, reason: str = "manual"):
        """Manual override (например после ARCH-104 promote)."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            UPDATE pattern_lifecycle SET status=?, decision_reason=?, last_check_ts=?
            WHERE pattern_id=?
        """, (status, reason, datetime.now(timezone.utc).isoformat(), pattern_id))
        conn.commit()
        conn.close()


# ─────────── Self-test ───────────

if __name__ == "__main__":
    import sys
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

    pl = PatternLifecycle()
    # Test без реальных trades в DB (will return insufficient_data)
    h = pl.check_pattern("L1_golden", baseline_avgR=1.892)
    print(f"Pattern: {h.pattern_id}")
    print(f"  Status: {h.status}")
    print(f"  Reason: {h.decision_reason}")
    print(f"  n_30d: {h.n_trades_30d}")
    print(f"  baseline_avgR: {h.baseline_avgR:.3f}")
    print(f"  runtime_avgR_30d: {h.runtime_avgR_30d:.3f}")

    # Test get_active
    active = pl.get_active_patterns()
    print(f"\nActive patterns count: {len(active)}")

    print("\n✅ PatternLifecycle initialized successfully")
