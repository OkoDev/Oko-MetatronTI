# -*- coding: utf-8 -*-
"""DS-FEATURES-VALIDATE (09.07) — проверка DS-mining перед использованием в router.

Проверки:
  1. TIME-SPLIT робастность: половина/половина истории — знак и масштаб дельты стабильны?
  2. Гипотеза Егора #1: WT-OS «вред» = режим-зависимость (выборка медвежья) → split по
     USDT.D-режиму (risk-on/off по MA20).
  3. Гипотеза Егора #2: малые n у SMC-топов = СВЕЖЕСТЬ фич → first_seen дата.
  4. Чистота: сделки с ledger_mismatch исключены.
Дельта = mean(net | фича=1) − mean(net | ВСЕ) — как у DS (сверено по его скрипту).
"""
import sys, sqlite3, json, statistics as st
from collections import defaultdict
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TOP = ["smc.bear_ob_mitigated_1h", "smc.bull_choch_1h", "smc.bull_bos_15m",
       "smc.bear_bos_15m", "smc.bull_ob_4h", "mom.vol_spike_1h",
       "wt.wt_div_bull_hidden_1d", "wt.wt_div_bear_hidden_1d", "wt.wt_os_1h"]
PIVOT_KEYS = ["pivot.pivot_above_R3_1D", "pivot.pivot_below_R3_1D"]


def flatten(fj):
    flat = {}
    ctx = (fj or {}).get("context", {})
    for category in ["smc", "trend", "mom", "pivot", "rsi", "wt", "volume"]:
        cd = ctx.get(category, {})
        if not isinstance(cd, dict):
            continue
        for k, v in cd.items():
            if isinstance(v, (int, float)) and v == 1:
                flat[f"{category}.{k}"] = 1
            elif category == "pivot" and isinstance(v, str):
                flat[f"{category}.{k}={v}"] = 1
    return flat


def usdtd_by_date():
    from core.signals.usdtd_regime import _series, _MA_LEN
    c = sqlite3.connect("ohlcv_cache.db")
    ser = _series(c)
    c.close()
    out, vals = {}, []
    for d, v in ser:
        vals.append(v)
        if len(vals) >= _MA_LEN:
            out[d] = v > sum(vals[-_MA_LEN:]) / _MA_LEN
    return out


def _weight(delta_pct: float) -> float:
    """Формула адаптивных весов проекта, но от % net (ЗАКОН №1): clamp(1+Δ%×0.2, 0.5, 2.0)."""
    return max(0.5, min(2.0, 1.0 + delta_pct * 0.2))


def main():
    conn = sqlite3.connect("subscriptions.db")
    cur = conn.cursor()
    cur.execute("""SELECT s.id, s.profit_pct, s.created_at, t.features_json
        FROM simulated_trades s JOIN trade_features t ON t.trade_id = s.id
        WHERE s.status IN ('SL','TP','TSL') AND s.profit_pct IS NOT NULL
          AND t.features_json IS NOT NULL AND t.features_json != ''
          AND (s.features_json IS NULL OR s.features_json NOT LIKE '%ledger_mismatch%')""")
    rows = []
    for tid, pct, ts, fj in cur.fetchall():
        try:
            flat = flatten(json.loads(fj))
        except Exception:
            continue
        rows.append({"id": tid, "pct": float(pct), "ts": str(ts), "f": flat})
    conn.close()
    rows.sort(key=lambda r: r["ts"])
    n = len(rows)
    mid_ts = rows[n // 2]["ts"]
    base_all = st.mean(r["pct"] for r in rows)
    h1 = rows[:n // 2]
    h2 = rows[n // 2:]
    b1 = st.mean(r["pct"] for r in h1)
    b2 = st.mean(r["pct"] for r in h2)
    print(f"чистых сделок: {n} (ledger_mismatch исключены) · base {base_all:+.3f}% · "
          f"split @ {mid_ts[:10]} (H1 {b1:+.3f} / H2 {b2:+.3f})")
    regime = usdtd_by_date()

    write = "--write-weights" in sys.argv
    whitelist = []                       # (feature, regime, delta, n) прошедшие валидацию
    print(f"\n{'фича':34} {'n':>5} {'Δall':>7} {'ΔH1':>7} {'ΔH2':>7} {'вердикт':10} {'first_seen':10}")
    for feat in TOP + PIVOT_KEYS:
        sel = [r for r in rows if feat in r["f"]]
        if len(sel) < 10:
            print(f"{feat:34} {len(sel):5}  — мало данных")
            continue
        d_all = st.mean(r["pct"] for r in sel) - base_all
        s1 = [r for r in sel if r["ts"] < mid_ts]
        s2 = [r for r in sel if r["ts"] >= mid_ts]
        d1 = (st.mean(r["pct"] for r in s1) - b1) if len(s1) >= 5 else None
        d2 = (st.mean(r["pct"] for r in s2) - b2) if len(s2) >= 5 else None
        first = min(r["ts"] for r in sel)[:10]
        if d1 is None or d2 is None:
            verdict = "СВЕЖАЯ" if d1 is None else "УГАСЛА?"
        elif d1 * d2 > 0 and abs(d1) > 0.1 and abs(d2) > 0.1:
            verdict = "РОБАСТНА"
        elif d1 * d2 > 0:
            verdict = "слабая"
        else:
            verdict = "ФЛИП"
        f1 = f"{d1:+.2f}" if d1 is not None else "  —  "
        f2 = f"{d2:+.2f}" if d2 is not None else "  —  "
        print(f"{feat:34} {len(sel):5} {d_all:+7.2f} {f1:>7} {f2:>7} {verdict:10} {first}")
        # белый список: только РОБАСТНА и с достаточным n (порог адаптивных весов = 20)
        if verdict == "РОБАСТНА" and len(sel) >= 20:
            # WT-фичи — режим-зависимы (гипотеза Егора): вес per-режим, не 'any'
            if feat.startswith("wt."):
                for want, rname in ((False, "risk_on"), (True, "risk_off")):
                    selr = [r for r in sel if regime.get(r["ts"][:10]) is want]
                    unir = [r for r in rows if regime.get(r["ts"][:10]) is want]
                    if len(selr) >= 20 and len(unir) >= 100:
                        dr = st.mean(r["pct"] for r in selr) - st.mean(r["pct"] for r in unir)
                        whitelist.append((feat, rname, dr, len(selr)))
            else:
                whitelist.append((feat, "any", d_all, len(sel)))

    # Гипотеза Егора: WT-OS по режимам USDT.D
    print("\n=== wt.os_1h по режимам USDT.D (гипотеза Егора: режим-зависимость) ===")
    for feat in ("wt.wt_os_1h", "wt.wt_ob_1h", "wt.wt_os_1d"):
        for want, label in ((False, "risk-ON (бычье альтам)"), (True, "risk-OFF (медвежье)")):
            sel = [r for r in rows if feat in r["f"] and regime.get(r["ts"][:10]) is want]
            uni = [r for r in rows if regime.get(r["ts"][:10]) is want]
            if len(sel) >= 20 and len(uni) >= 50:
                d = st.mean(r["pct"] for r in sel) - st.mean(r["pct"] for r in uni)
                print(f"  {feat:12} {label:24} n={len(sel):5} Δ={d:+.3f}%")
            else:
                print(f"  {feat:12} {label:24} n={len(sel):5} — мало")

    # --write-weights: белый список → feature_weights (СТУПЕНЬ 2 читает оттуда)
    if write and whitelist:
        from core.intelligence.feature_weights import ensure_table
        ensure_table("subscriptions.db")
        import datetime as dt
        with sqlite3.connect("subscriptions.db", timeout=10) as c:
            c.execute("UPDATE feature_weights SET validated=0")   # старый список гасим
            for feat, rname, delta, nn in whitelist:
                c.execute("INSERT OR REPLACE INTO feature_weights VALUES (?,?,?,?,?,1,?)",
                          (feat, rname, round(delta, 4), nn, round(_weight(delta), 4),
                           dt.datetime.utcnow().isoformat()))
            c.commit()
        print(f"\n[WEIGHTS] записано {len(whitelist)} validated-весов:")
        for feat, rname, delta, nn in whitelist:
            print(f"  {feat:34} [{rname:8}] Δ={delta:+.2f}% n={nn} → w={_weight(delta):.2f}")


if __name__ == "__main__":
    main()
