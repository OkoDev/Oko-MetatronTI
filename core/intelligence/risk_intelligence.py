"""
Risk Intelligence v1 (Сфера 3 Куба Метатрона).

Формульный clamp-based контур для динамического управления:
  - risk_pct_multiplier (0.3-2.0x base) от EMA avg_R + Sharpe + warnings + BTC regime
  - leverage от SL distance + funding awareness
  - allow_entry (boolean) от open_count cap + correlation + funding

Источник концепции: DISCUSSION.md 19.04.2026, линии 3436-3519.
Применение: D-009 (Decisions Log ARCH-104) — v1 запускается с Phase 1 в shadow.

ВАЖНО: пока shadow only — НЕ применяется в production. Только логирует решения.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# Defaults — будут перенесены в config/risk_policies.yaml в Phase 6 DEV-263
DEFAULTS = {
    "base_risk_pct": 1.0,           # % депозита на сделку
    "risk_pct_min_clamp": 0.3,      # минимум multiplier
    "risk_pct_max_clamp": 2.0,      # максимум multiplier
    "max_open_per_regime": {
        "TREND_UP": 8,
        "TREND_DOWN": 8,
        "RANGE": 4,
        "HIGH_VOL": 2,
    },
    "max_funding_pct": 0.03,        # % за 8h — при превышении allow_entry=False
    "max_correlation": 0.7,         # с уже открытыми в том же направлении
    "exchange_min_leverage": 1,
    "exchange_max_leverage": 20,
    "leverage_safety_buffer": 2.0,  # liquidation должен быть ≥2× за SL
}


@dataclass
class RiskInputs:
    """Все входные сигналы для Risk Intelligence v1."""
    pattern_id: str
    direction: str                   # "LONG" / "SHORT"
    signal_strength: float           # 0-100
    sl_distance_pct: float           # % от entry до SL
    ema_avg_r_30d: float = 0.0       # EMA avgR за 30 дней по этому signal_type
    sharpe_30d: float = 0.0          # Sharpe за 30 дней
    n_trades_30d: int = 0            # выборка для надёжности EMA
    regime: str = "UNKNOWN"          # TREND_UP/DOWN/RANGE/HIGH_VOL
    btc_regime: str = "UNKNOWN"      # bull/bear/range/high_vol
    funding_pct_8h: float = 0.0      # текущий funding rate
    open_positions_count: int = 0    # сколько открытых
    open_positions_same_dir_corr: float = 0.0  # max correlation с уже открытыми того же направления
    warnings_24h: int = 0            # CircuitBreaker warnings за 24h
    pattern_stability_score: float = 1.0  # 1.0 = passed walk-forward, 0.5 = unstable


@dataclass
class RiskDecision:
    """Решение Risk Intelligence v1."""
    allow_entry: bool
    risk_pct: float                  # final % депозита (после multiplier × base)
    risk_pct_multiplier: float       # 0.3-2.0
    leverage: int                    # рекомендуемый плечо
    abort_reasons: list[str] = field(default_factory=list)
    factors: dict = field(default_factory=dict)  # детализация множителей
    reasoning: str = ""
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RiskIntelligenceV1:
    """Формульный контур Risk Intelligence (Сфера 3)."""

    def __init__(self, config: Optional[dict] = None):
        self.cfg = {**DEFAULTS, **(config or {})}

    # ───────── Multipliers ─────────

    def _pattern_quality_factor(self, stability_score: float) -> float:
        """Stability: 1.0 = full multiplier, 0.5 = halved."""
        return max(0.5, min(1.5, 0.5 + stability_score))

    def _ema_r_factor(self, ema_r: float, n_trades: int) -> float:
        """EMA avgR > 0 → multiplier > 1.

        n<100 → confidence=0.5 (на малой выборке EMA шумит).
        Clamp [0.5, 1.5].
        """
        if n_trades < 30:
            return 0.7   # очень малая выборка — снижаем сразу
        confidence = min(1.0, n_trades / 100.0)
        raw = 1.0 + ema_r * 0.4 * confidence
        return max(0.5, min(1.5, raw))

    def _sharpe_factor(self, sharpe: float) -> float:
        """Sharpe > 1.0 → bonus, < 0.5 → penalty.
        Linear: f = 0.7 + sharpe × 0.15, clamp [0.5, 1.5].
        """
        return max(0.5, min(1.5, 0.7 + sharpe * 0.15))

    def _warnings_factor(self, warnings: int) -> float:
        """Каждый warning снижает risk.
        0 → 1.0, 1 → 0.7, 2 → 0.4, 3+ → 0.2.
        """
        return {0: 1.0, 1: 0.7, 2: 0.4}.get(warnings, 0.2)

    def _btc_regime_factor(self, btc_regime: str, direction: str) -> float:
        """LONG в bull = 1.2, LONG в bear = 0.5. Зеркально для SHORT."""
        if direction == "LONG":
            return {"bull": 1.2, "range": 1.0, "bear": 0.5, "high_vol": 0.7}.get(btc_regime, 1.0)
        if direction == "SHORT":
            return {"bear": 1.2, "range": 1.0, "bull": 0.5, "high_vol": 0.7}.get(btc_regime, 1.0)
        return 1.0

    # ───────── Main calc ─────────

    def evaluate(self, inputs: RiskInputs) -> RiskDecision:
        """Основная функция — выдаёт RiskDecision на основе формул."""
        cfg = self.cfg
        abort_reasons: list[str] = []
        factors: dict = {}

        # ─── Gate 1: open_positions cap ───
        max_open = cfg["max_open_per_regime"].get(inputs.regime, 5)
        if inputs.open_positions_count >= max_open:
            abort_reasons.append(f"open_cap: {inputs.open_positions_count}>={max_open} for {inputs.regime}")

        # ─── Gate 2: correlation ───
        if inputs.open_positions_same_dir_corr > cfg["max_correlation"]:
            abort_reasons.append(f"correlation: {inputs.open_positions_same_dir_corr:.2f}>{cfg['max_correlation']}")

        # ─── Gate 3: extreme funding ───
        # LONG при сильном positive funding (longs платят shorts) = опасно
        # SHORT при сильном negative funding = опасно
        if inputs.direction == "LONG" and inputs.funding_pct_8h > cfg["max_funding_pct"]:
            abort_reasons.append(f"funding_long: {inputs.funding_pct_8h:.3f}>{cfg['max_funding_pct']}")
        if inputs.direction == "SHORT" and inputs.funding_pct_8h < -cfg["max_funding_pct"]:
            abort_reasons.append(f"funding_short: {inputs.funding_pct_8h:.3f}<{-cfg['max_funding_pct']}")

        # ─── Compute multipliers ───
        pat_q = self._pattern_quality_factor(inputs.pattern_stability_score)
        ema_f = self._ema_r_factor(inputs.ema_avg_r_30d, inputs.n_trades_30d)
        sharpe_f = self._sharpe_factor(inputs.sharpe_30d)
        warn_f = self._warnings_factor(inputs.warnings_24h)
        btc_f = self._btc_regime_factor(inputs.btc_regime, inputs.direction)

        raw_multiplier = pat_q * ema_f * sharpe_f * warn_f * btc_f
        multiplier = max(cfg["risk_pct_min_clamp"], min(cfg["risk_pct_max_clamp"], raw_multiplier))

        factors = {
            "pattern_quality": round(pat_q, 3),
            "ema_r": round(ema_f, 3),
            "sharpe": round(sharpe_f, 3),
            "warnings": round(warn_f, 3),
            "btc_regime": round(btc_f, 3),
            "raw_product": round(raw_multiplier, 3),
            "clamped": round(multiplier, 3),
        }

        risk_pct = cfg["base_risk_pct"] * multiplier

        # ─── Leverage from SL distance ───
        # position_notional = deposit × risk_pct / sl_distance_pct
        # leverage_min_safe = notional / deposit × safety_buffer
        # Упрощённо: leverage = clamp(risk_pct / sl_distance_pct × safety_buffer, min, max)
        if inputs.sl_distance_pct > 0:
            target_notional_pct = risk_pct / (inputs.sl_distance_pct / 100.0)
            leverage_raw = target_notional_pct * cfg["leverage_safety_buffer"] / 100.0
            leverage = max(cfg["exchange_min_leverage"], min(cfg["exchange_max_leverage"], math.ceil(leverage_raw)))
        else:
            leverage = cfg["exchange_min_leverage"]
            abort_reasons.append("invalid_sl_distance")

        allow = len(abort_reasons) == 0

        reasoning_parts = [
            f"pat_q={pat_q:.2f}",
            f"ema_r={ema_f:.2f}(n={inputs.n_trades_30d})",
            f"sharpe={sharpe_f:.2f}",
            f"warn={warn_f:.2f}({inputs.warnings_24h})",
            f"btc={btc_f:.2f}({inputs.btc_regime})",
            f"→mult={multiplier:.2f}→risk_pct={risk_pct:.2f}%, lev={leverage}x",
        ]
        if abort_reasons:
            reasoning_parts.append(f"ABORT: {', '.join(abort_reasons)}")
        reasoning = " | ".join(reasoning_parts)

        return RiskDecision(
            allow_entry=allow,
            risk_pct=round(risk_pct, 3),
            risk_pct_multiplier=round(multiplier, 3),
            leverage=leverage,
            abort_reasons=abort_reasons,
            factors=factors,
            reasoning=reasoning,
        )


# ─────────── Shadow logging ───────────

def log_decision(decision: RiskDecision, signal_meta: dict, db_path: str = "subscriptions.db"):
    """Логирует решение Risk Intelligence v1 в БД для последующего анализа.

    D-028 (2026-05-20): VST = уже production-like execution, shadow mode не нужен.
    Решения логируются ПАРАЛЛЕЛЬНО с VST/LIVE trades для post-hoc decision quality analysis.
    """
    import sqlite3
    import json

    # Создаём таблицу если её нет
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS risk_decisions_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            pattern_id TEXT,
            symbol TEXT,
            direction TEXT,
            allow_entry INTEGER,
            risk_pct REAL,
            risk_pct_multiplier REAL,
            leverage INTEGER,
            abort_reasons TEXT,
            factors_json TEXT,
            reasoning TEXT,
            signal_meta_json TEXT
        )
    """)
    cur.execute("""
        INSERT INTO risk_decisions_log (
            ts, pattern_id, symbol, direction,
            allow_entry, risk_pct, risk_pct_multiplier, leverage,
            abort_reasons, factors_json, reasoning, signal_meta_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        decision.ts.isoformat(),
        signal_meta.get("pattern_id", ""),
        signal_meta.get("symbol", ""),
        signal_meta.get("direction", ""),
        1 if decision.allow_entry else 0,
        decision.risk_pct,
        decision.risk_pct_multiplier,
        decision.leverage,
        json.dumps(decision.abort_reasons),
        json.dumps(decision.factors),
        decision.reasoning,
        json.dumps(signal_meta),
    ))
    conn.commit()
    conn.close()


# ─────────── Demo / self-test ───────────

if __name__ == "__main__":
    import json

    ri = RiskIntelligenceV1()

    # Test case 1: golden pattern, BTC bull, low warnings → high multiplier
    test1 = RiskInputs(
        pattern_id="L1_golden",
        direction="LONG",
        signal_strength=85,
        sl_distance_pct=2.0,
        ema_avg_r_30d=+0.8,
        sharpe_30d=1.5,
        n_trades_30d=80,
        regime="TREND_UP",
        btc_regime="bull",
        funding_pct_8h=0.01,
        open_positions_count=2,
        open_positions_same_dir_corr=0.3,
        warnings_24h=0,
        pattern_stability_score=1.0,
    )
    d1 = ri.evaluate(test1)
    print("=== Test 1: Golden + Bull BTC ===")
    print(f"  allow={d1.allow_entry}")
    print(f"  risk_pct={d1.risk_pct}% (mult={d1.risk_pct_multiplier})")
    print(f"  leverage={d1.leverage}x")
    print(f"  factors={json.dumps(d1.factors, indent=2)}")
    print(f"  reasoning: {d1.reasoning}")

    # Test case 2: same pattern, BTC bear → low multiplier
    test2 = RiskInputs(
        pattern_id="L1_golden",
        direction="LONG",
        signal_strength=85,
        sl_distance_pct=2.0,
        ema_avg_r_30d=-0.5,
        sharpe_30d=0.2,
        n_trades_30d=80,
        regime="HIGH_VOL",
        btc_regime="bear",
        funding_pct_8h=0.05,         # > 0.03 → abort
        open_positions_count=1,
        open_positions_same_dir_corr=0.2,
        warnings_24h=2,
        pattern_stability_score=0.5,
    )
    d2 = ri.evaluate(test2)
    print("\n=== Test 2: Bear context + high funding (LONG) ===")
    print(f"  allow={d2.allow_entry}")
    print(f"  abort_reasons={d2.abort_reasons}")
    print(f"  factors={json.dumps(d2.factors, indent=2)}")
    print(f"  reasoning: {d2.reasoning}")

    # Test case 3: SHORT in bear — favorable
    test3 = RiskInputs(
        pattern_id="S1_bos_premium",
        direction="SHORT",
        signal_strength=80,
        sl_distance_pct=1.5,
        ema_avg_r_30d=+0.6,
        sharpe_30d=1.0,
        n_trades_30d=120,
        regime="TREND_DOWN",
        btc_regime="bear",
        funding_pct_8h=-0.02,
        open_positions_count=0,
        open_positions_same_dir_corr=0.0,
        warnings_24h=0,
        pattern_stability_score=1.0,
    )
    d3 = ri.evaluate(test3)
    print("\n=== Test 3: SHORT in bear (favorable) ===")
    print(f"  allow={d3.allow_entry}")
    print(f"  risk_pct={d3.risk_pct}% (mult={d3.risk_pct_multiplier})")
    print(f"  leverage={d3.leverage}x")
    print(f"  reasoning: {d3.reasoning}")
