"""ТЕСТ младших триггеров SMC-набора на матричном входе (Егор 02.07: «найти валидные триггеры тестом»).

База: вход = свежий тэг 4h-OTE в сторону bias (structure_trend на прошлом), TP=1R, SL=за слом, costs 0.2%.
Тестируем РАЗНЫЕ младшие (15m) триггеры SMC-набора и сравниваем % net — какой даёт edge:
  T0 baseline   — без триггера (сырой тэг)
  T1 choch      — младший CHoCH в сторону bias (смена характера = разворот в зоне)
  T2 aligned    — любой слом (BOS+CHoCH) в сторону bias (структура с нами)
  T3 fvg        — свежий FVG в сторону bias
  T4 ob         — Order Block в сторону bias
  T5 choch+fvg  — CHoCH И FVG вместе (конфлюэнция)
Честный walk-forward: LTF SMC каузальны (посчитаны раз, фильтр по ts ≤ бара). 4h-структура кэш/4h-бар.
Запуск: python scripts/test_ote_triggers.py
"""
from __future__ import annotations
import sys, time
import pandas as pd
import ccxt

sys.path.insert(0, ".")
from core.smc.ote_matrix import structure_trend, build_ote
from core.smc.smc_engine import detect_structure_breaks, detect_fvg, detect_order_blocks

COST_PCT = 0.2
ANCHOR_LB = 250
LTF_TF = "15m"                # сравнение 15m vs 5m; 15m CHoCH был лучший (+0.462) — проверка на 45 днях
WIN = 6                        # окно свежести триггера (баров) до входа
SYMBOLS = ["XLM", "GRT", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "SUI", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE", "SEI",
           "BNB", "ETH", "XRP", "MATIC", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA"]
TRIGGERS = ["T0_base", "T1_choch", "T2_aligned", "T3_fvg", "T4_ob", "T5_choch_fvg", "T6_fvg_then_choch"]
_TF_MS = {"5m": 300000, "15m": 900000, "4h": 14400000}


def fetch(ex, sym, tf, limit):
    for _ in range(5):
        try:
            o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", tf, limit=limit)
            if o:
                df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
                df["time"] = pd.to_datetime(df["ts"], unit="ms")
                return df.set_index("time")
        except Exception:
            time.sleep(1.5)
    return None


def fetch_paged(ex, sym, tf, chunks=3):
    """Пагинация назад: chunks×1440 баров (5m×3=~15 дней) для значимого сэмпла."""
    step = _TF_MS.get(tf, 300000)
    frames = []
    since = None
    # идём НАЗАД от текущего: первый чанк последний, затем всё раньше
    latest = fetch(ex, sym, tf, 1440)
    if latest is None:
        return None
    frames.append(latest)
    earliest_ts = int(latest["ts"].iloc[0])
    for _ in range(chunks - 1):
        since = earliest_ts - 1440 * step
        for _r in range(4):
            try:
                o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", tf, since=since, limit=1440)
                break
            except Exception:
                time.sleep(1.5); o = None
        if not o:
            break
        df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["ts"], unit="ms"); df = df.set_index("time")
        frames.append(df)
        earliest_ts = int(df["ts"].iloc[0])
    full = pd.concat(frames).sort_index()
    full = full[~full.index.duplicated(keep="first")]
    return full


def precompute_ltf(d15):
    """Каузальные LTF SMC-сигналы → списки idx по направлению."""
    out = {"choch_bull": set(), "choch_bear": set(), "brk_bull": set(), "brk_bear": set(),
           "fvg_bull": set(), "fvg_bear": set(), "ob_bull": set(), "ob_bear": set()}
    try:
        brks = detect_structure_breaks(d15, length=5)
        for b in brks:
            d = "bull" if b.direction == "bull" else "bear"
            out[f"brk_{d}"].add(b.idx)
            if b.kind == "CHoCH":
                out[f"choch_{d}"].add(b.idx)
    except Exception:
        brks = []
    try:
        for f in detect_fvg(d15):
            ts_i = f[4]; kind = f[3]
            try: idx = d15.index.get_loc(ts_i)
            except Exception: continue
            out[f"fvg_{'bull' if kind=='bull' else 'bear'}"].add(idx)
    except Exception:
        pass
    try:
        for ob in detect_order_blocks(d15, brks):
            idx = getattr(ob, "idx", None); kind = getattr(ob, "kind", None)
            if idx is not None and kind in ("bull", "bear"):
                out[f"ob_{kind}"].add(idx)
    except Exception:
        pass
    return out


def _recent(idxset, i, win):
    return any((i - win) <= x <= i for x in idxset)


def fire(trig, bias, i, sig):
    d = "bull" if bias == "long" else "bear"
    if trig == "T0_base":       return True
    if trig == "T1_choch":      return _recent(sig[f"choch_{d}"], i, WIN)
    if trig == "T2_aligned":    return _recent(sig[f"brk_{d}"], i, WIN)
    if trig == "T3_fvg":        return _recent(sig[f"fvg_{d}"], i, WIN)
    if trig == "T4_ob":         return _recent(sig[f"ob_{d}"], i, WIN)
    if trig == "T5_choch_fvg":  return _recent(sig[f"choch_{d}"], i, WIN) and _recent(sig[f"fvg_{d}"], i, WIN)
    if trig == "T6_fvg_then_choch":
        # ПОРЯДОК (Егор): FVG-имбаланс формируется ПЕРВЫМ, ПОТОМ CHoCH подтверждает (fvg_idx < choch_idx)
        fvgs = [f for f in sig[f"fvg_{d}"] if (i - WIN) <= f <= i]
        chochs = [c for c in sig[f"choch_{d}"] if (i - WIN) <= c <= i]
        return any(f < c for f in fvgs for c in chochs)
    return False


def backtest_symbol(d4h, d15, sig):
    """Одним проходом по 15m копим сделки для ВСЕХ триггеров сразу (общая зона/тэг)."""
    res = {t: [] for t in TRIGGERS}
    pos = {t: None for t in TRIGGERS}
    last4_len = -1; cache = None
    for i in range(200, len(d15)):
        t = d15.index[i]; bar = d15.iloc[i]
        price = float(bar["close"]); hi = float(bar["high"]); lo = float(bar["low"])
        # закрытие открытых по каждому триггеру
        for trg in TRIGGERS:
            p = pos[trg]
            if not p:
                continue
            d = p["dir"]; ex_px = None
            if d == "long":
                if lo <= p["sl"]: ex_px = p["sl"]
                elif hi >= p["tp"]: ex_px = p["tp"]
            else:
                if hi >= p["sl"]: ex_px = p["sl"]
                elif lo <= p["tp"]: ex_px = p["tp"]
            if ex_px is not None:
                sign = 1 if d == "long" else -1
                net = (ex_px - p["entry"]) / p["entry"] * 100 * sign - COST_PCT
                res[trg].append({"dir": d, "net": net, "win": net > 0})
                pos[trg] = None
        # 4h структура (кэш на 4h-бар)
        d4 = d4h[d4h.index <= t]
        if len(d4) < 120:
            continue
        if len(d4) != last4_len:
            st = structure_trend(d4, lookback=ANCHOR_LB)
            last4_len = len(d4)
            if st["trend"] and st["break_level"] is not None and st["extreme"] is not None:
                ob = build_ote(st["extreme"], st["break_level"])
                cache = {"bias": st["trend"], "brk": st["break_level"],
                         "lo": ob["ote"][0], "hi": ob["ote"][1]}
            else:
                cache = None
        if not cache:
            continue
        bias, brk, lo_z, hi_z = cache["bias"], cache["brk"], cache["lo"], cache["hi"]
        if not (lo_z <= price <= hi_z):
            continue
        prev = float(d15.iloc[i - 1]["close"])
        if lo_z <= prev <= hi_z:
            continue                    # не свежий тэг
        entry = price
        sl = brk * 0.999 if (bias == "long" and brk < entry) else (brk * 1.001 if (bias == "short" and brk > entry) else None)
        if sl is None:
            continue
        risk = abs(entry - sl)
        if risk <= 0 or risk / entry > 0.15:
            continue
        tp = entry + risk if bias == "long" else entry - risk    # 1R (ближний, валидирован)
        for trg in TRIGGERS:
            if pos[trg] is None and fire(trg, bias, i, sig):
                pos[trg] = {"dir": bias, "entry": entry, "sl": sl, "tp": tp}
    return res


def main():
    import statistics as s
    ex = ccxt.bingx({"enableRateLimit": True})
    agg = {t: [] for t in TRIGGERS}
    for sym in SYMBOLS:
        d4h = fetch(ex, sym, "4h", 400); d15 = fetch_paged(ex, sym, LTF_TF, chunks=3)
        if d4h is None or d15 is None or len(d15) < 300:
            print(f"  {sym}: нет данных"); continue
        sig = precompute_ltf(d15)
        res = backtest_symbol(d4h, d15, sig)
        for t in TRIGGERS:
            agg[t].extend(res[t])
        print(f"  {sym:5} готов (base n={len(res['T0_base'])})")
    print("=" * 64)
    print(f"{'триггер':14} {'n':>4} {'WR':>5} {'mean%':>8} {'med%':>8} {'sum%':>8}")
    for t in TRIGGERS:
        tr = agg[t]
        if not tr:
            print(f"{t:14} n=0"); continue
        nets = [x["net"] for x in tr]
        wr = 100 * sum(1 for x in tr if x["win"]) / len(tr)
        print(f"{t:14} {len(tr):>4} {wr:>4.0f}% {s.mean(nets):>+7.3f} {s.median(nets):>+7.3f} {sum(nets):>+7.1f}")
    print(f"costs={COST_PCT}% · TP=1R · anchor=4h · ltf={LTF_TF} · WIN={WIN}бар · честный walk-forward")


if __name__ == "__main__":
    main()
