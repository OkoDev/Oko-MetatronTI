# -*- coding: utf-8 -*-
"""DEAD-GATE AUDIT (13.08.2026, DS).

Для каждого гейта бота: сколько реально заблокировал (signal_drops, полное окно),
включён ли в конфиге, вызывается ли в коде. Вердикт: ЖИВ / МЁРТВ / OFF (осознанно
выключен) / НЕВИДИМ (SOFT — пенальтит strength, не пишет дропы).

Запуск: python scripts/deadgate_audit.py
"""
import re
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(".")
DB = "subscriptions.db"

# ── все gate_name, которые ПИШУТ в signal_drops (из кода) ──────────────
GATES_FROM_CODE = [
    "validate_inputs", "dedup_open", "sl_cooldown", "min_sl_dist",
    "rr_filter", "qty_validation", "btc_market", "regime_safety",
    "time_gate", "correlation_guard", "market_stress", "pair_cooldown_streak",
    "strength_threshold", "below_min_strength", "strength_too_low",
    "register_returned_none", "open_bracket_fail", "cascade_1d_gate",
    "exchange_position_already_open", "min_strength_register",
    "min_strength", "atr_change_s2_only", "watch_neutral",
    "order_params_zero", "qty_zero",
    "arch104_low_strength", "arch104_long_banned", "arch104_d051_no_wt_cross",
    "verdict_gate", "weekly_bias", "mtf_gate", "smc_none_gate",
    "circuit_breaker", "phase_guard", "btc_filter",
    "dev186_wt_signal_regime_gate", "crowd_gate", "cluster_gate",
    "session_gate", "bos_gate", "cooldown_h",
]

# ── какие гейты SOFT (не пишут дропы, пенальтят strength) ──────────────
SOFT_GATES = {
    "btc_market", "regime_safety", "time_gate", "correlation_guard",
    "market_stress", "pair_cooldown_streak", "strength_threshold",
    "weekly_bias", "mtf_gate", "smc_none_gate", "dev186_wt_signal_regime_gate",
}

con = sqlite3.connect(DB)
# полное окно
rows_all = dict(con.execute(
    "SELECT gate_name, COUNT(*) FROM signal_drops GROUP BY gate_name"
).fetchall())
# 90 дней
rows_90 = dict(con.execute(
    "SELECT gate_name, COUNT(*) FROM signal_drops "
    "WHERE dropped_at >= datetime('now','-90 days') GROUP BY gate_name"
).fetchall())
# 30 дней
rows_30 = dict(con.execute(
    "SELECT gate_name, COUNT(*) FROM signal_drops "
    "WHERE dropped_at >= datetime('now','-30 days') GROUP BY gate_name"
).fetchall())
con.close()

# ── статус в конфиге (enabled флаги по секциям) ────────────────────────
cfg_text = (ROOT / "config.yaml").read_text(encoding="utf-8")

def cfg_flag(pattern: str) -> str:
    """Находит enabled/shadow флаг по секции. Возвращает ✅/⭕/❓."""
    m = re.search(pattern, cfg_text, re.S)
    if not m:
        return "❓нет в конфиге"
    block = m.group(0)
    en = re.search(r"enabled:\s*(true|false)", block)
    sh = re.search(r"shadow(?:_mode)?:\s*(true|false)", block)
    parts = []
    if en:
        parts.append("✅" if en.group(1) == "true" else "⭕OFF")
    if sh:
        parts.append("shadow" if sh.group(1) == "true" else "")
    return " ".join(x for x in parts if x) or "❓"

# ── вывод ───────────────────────────────────────────────────────────────
print("=" * 78)
print("DEAD-GATE AUDIT · полное окно signal_drops (96 дней, 09.05-13.08.2026)")
print("=" * 78)
print(f"{'гейт':<32}{'всего':>8}{'90д':>8}{'30д':>8}  статус конфига")
print("-" * 78)

dead = []
for g in GATES_FROM_CODE:
    a, n90, n30 = rows_all.get(g, 0), rows_90.get(g, 0), rows_30.get(g, 0)
    # конфиг-флаг по имени
    flag = "❓"
    cfg_map = {
        "time_gate": r"time_gate:\s*\{[^}]*enabled:\s*(true|false)",
        "market_stress": r"market_stress_gate:\s*\{[^}]*enabled:\s*(true|false)",
        "circuit_breaker": r"circuit_breaker:\s*\{[^}]*enabled:\s*(true|false)",
        "btc_market": r"btc_market_gate:\s*\{[^}]*enabled:\s*(true|false)",
        "verdict_gate": r"verdict_gate:\s*\{[^}]*enabled:\s*(true|false)",
        "weekly_bias": r"weekly_bias_gate:\s*\{[^}]*enabled:\s*(true|false)",
        "mtf_gate": r"mtf_gate_enabled:\s*(true|false)",
        "smc_none_gate": r"smc_none_gate:\s*\{[^}]*enabled:\s*(true|false)",
        "cascade_1d_gate": r"cascade_gate:\s*(true|false)",
        "phase_guard": r"phase_guard_enabled:\s*(true|false)",
        "btc_filter": r"btc_filter_enabled:\s*(true|false)",
        "dev186_wt_signal_regime_gate": r"dev186_wt_signal_regime_gate:\s*(true|false)",
    }
    if g in cfg_map:
        m = re.search(cfg_map[g], cfg_text)
        if m:
            val = m.group(1)
            flag = "✅" if val == "true" else "⭕OFF"
    if a == 0:
        dead.append(g)

    mark = ""
    if a == 0:
        if g in SOFT_GATES:
            mark = "  ⚠️ SOFT (penalty, не пишет дропы)"
        else:
            mark = "  🔴 МЁРТВ/не вызывается"
    print(f"{g:<32}{a:>8}{n90:>8}{n30:>8}  {flag}{mark}")

print("-" * 78)
print(f"Гейтов с 0 дропов за ВСЁ время: {len(dead)}")
print("  (для HARD — мёртвые/не вызываются; для SOFT — невидимые, нужен замер penalty)")
print()
print("ИСТОЧНИКИ ДРОПОВ ВНЕ СПИСКА (если есть):")
all_keys = set(rows_all)
known = set(GATES_FROM_CODE)
for g in sorted(all_keys - known):
    print(f"  🆕 {g}: {rows_all[g]} (не было в инвентаризации!)")
