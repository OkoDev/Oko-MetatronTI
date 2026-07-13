"""
DS-GRAVITY-TRI: GRAVITY-триангуляция SHORT-рецепта на Binance-кэше.

1. Входы SHORT-рецепта из test_ote_1h.py на ohlcv_cache.db
2. Gravity-скоринг на каждом входе (gravity_entry_test.py)
3. Бакеты 0 / 0-40 / 40-100 / 100+ → %% net
4. Вопрос: порог gravity для >=2%%/сделку?

Мера: %% net = ход%% - 0.2%% costs. Walk-forward без lookahead.
"""
import sqlite3, sys, time, statistics as st
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.smc.ote_matrix import structure_trend, build_ote

COST_PCT = 0.2
RISK_CAP = 6.0

# 30 символов из SHORT-рецепта
SYMBOLS = ["XLM", "GRT", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "SUI", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE", "SEI",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA", "WLD"]

# Gravity params (из gravity_entry_test.py)
ALPHA = 1.5
NEAR_PCT = 3.0
W = {"pivot": 2.0, "swing": 2.0, "fvg": 1.5, "ote": 2.5}
WTF = {"5m": 1.0, "15m": 1.5, "1h": 2.5, "4h": 3.5, "1d": 5.0, "1w": 7.0}

DB = Path(__file__).resolve().parent.parent / "ohlcv_cache.db"


def load_symbol(cur, base):
    """Загрузить все данные для символа из ohlcv_cache.db."""
    # Ищем варианты: binance:XLM/USDT или XLMUSDT
    patterns = [f"binance:{base}/USDT"]
    rows = []
    for pat in patterns:
        cur.execute(
            "SELECT timeframe, time, open, high, low, close, volume FROM ohlcv_cache "
            "WHERE symbol=? ORDER BY time",
            (pat,)
        )
        r = cur.fetchall()
        if r:
            rows = r
            break
    if not rows:
        return {}
    # Группируем по timeframe
    tfs = {}
    for tf, t, o, h, l, c, v in rows:
        if tf not in tfs:
            tfs[tf] = {"ts": [], "o": [], "h": [], "l": [], "c": [], "v": []}
        tfs[tf]["ts"].append(t)
        tfs[tf]["o"].append(o)
        tfs[tf]["h"].append(h)
        tfs[tf]["l"].append(l)
        tfs[tf]["c"].append(c)
        tfs[tf]["v"].append(v)
    # Конвертируем в DataFrame
    result = {}
    for tf, data in tfs.items():
        df = pd.DataFrame({
            "ts": data["ts"], "open": data["o"], "high": data["h"],
            "low": data["l"], "close": data["c"], "volume": data["v"]
        })
        df["time"] = pd.to_datetime(df["ts"], unit="ms")
        df = df.set_index("time").sort_index()
        result[tf] = df
    return result


def calc_gravity(price, direction, store, entry_ts):
    """Gravity-скоринг на момент входа. store = {tf: df}."""
    if price <= 0:
        return 0.0, 0
    typed = []
    # Пивоты: 1d/1w
    for tf in ("1d", "1w"):
        df = store.get(tf)
        if df is not None and len(df) >= 2:
            hh = df["high"].iloc[-2]
            ll = df["low"].iloc[-2]
            cc = df["close"].iloc[-2]
            pp = (hh + ll + cc) / 3
            for pv in [pp, 2 * pp - ll, 2 * pp - hh, pp + (hh - ll), pp - (hh - ll)]:
                typed.append((pv, "pivot", tf))
    # Swing + FVG + OTE: все ТФ
    for tf in ("5m", "15m", "1h", "4h"):
        df = store.get(tf)
        if df is None or len(df) < 60:
            continue
        try:
            from core.smc.smc_engine import zigzag_atr, ote_retest_setups
            for _ts, zp in zigzag_atr(df, 11, 3)[-6:]:
                typed.append((zp, "swing", tf))
        except Exception:
            pass
        try:
            h, l = df["high"].values, df["low"].values
            for i in range(max(0, len(df) - 30), len(df) - 2):
                if l[i + 2] > h[i]:
                    typed.append(((l[i + 2] + h[i]) / 2, "fvg", tf))
                elif h[i + 2] < l[i]:
                    typed.append(((h[i + 2] + l[i]) / 2, "fvg", tf))
        except Exception:
            pass
        try:
            for s in ote_retest_setups(df):
                if s["direction"] == direction:
                    lo, hi = s["ote"]
                    typed.append(((lo + hi) / 2, "ote", tf))
                    break
        except Exception:
            pass
    g = 0.0
    cnt = 0
    for lp, typ, tf in typed:
        if lp <= 0:
            continue
        dist = abs(lp - price) / price * 100
        if dist <= NEAR_PCT:
            g += W.get(typ, 1.0) * WTF.get(tf, 1.0) / max(dist, 0.05) ** ALPHA
            cnt += 1
    return g, cnt


def simulate_symbol(base, dfs):
    """Прогнать SHORT-рецепт на данных символа, вернуть сделки с gravity."""
    d1h = dfs.get("1h")
    d15 = dfs.get("15m")
    if d1h is None or d15 is None or len(d15) < 400 or len(d1h) < 200:
        return []

    trades = []
    pos = None
    last1_len = -1
    cache = None

    for i in range(200, len(d15)):
        t = d15.index[i]
        bar = d15.iloc[i]
        price = float(bar["close"])
        hi = float(bar["high"])
        lo = float(bar["low"])

        if pos:
            dr = pos["dir"]
            ex_px = None
            if dr == "long":
                if lo <= pos["sl"]:
                    ex_px = pos["sl"]
                elif hi >= pos["tp"]:
                    ex_px = pos["tp"]
            else:
                if hi >= pos["sl"]:
                    ex_px = pos["sl"]
                elif lo <= pos["tp"]:
                    ex_px = pos["tp"]
            if ex_px is not None:
                sign = 1 if dr == "long" else -1
                net = (ex_px - pos["entry"]) / pos["entry"] * 100 * sign - COST_PCT
                trades.append({
                    "net": net, "win": net > 0, "ts": t,
                    "entry": pos["entry"], "sl": pos["sl"], "tp": pos["tp"],
                    "dir": dr, "gravity": pos["gravity"], "n_levels": pos["n_levels"]
                })
                pos = None

        # 1h структура
        d1 = d1h[d1h.index <= t]
        if len(d1) < 120:
            continue
        if len(d1) != last1_len:
            try:
                st1 = structure_trend(d1, lookback=250)
                last1_len = len(d1)
                if st1["trend"] and st1["break_level"] is not None and st1["extreme"] is not None:
                    ob = build_ote(st1["extreme"], st1["break_level"])
                    cache = {"bias": st1["trend"], "lo": ob["ote"][0], "hi": ob["ote"][1], "lv": ob["levels"]}
                else:
                    cache = None
            except Exception:
                cache = None
        if not cache:
            continue
        bias, lo_z, hi_z, lv = cache["bias"], cache["lo"], cache["hi"], cache["lv"]
        if not (lo_z <= price <= hi_z):
            continue
        if lo_z <= float(d15.iloc[i - 1]["close"]) <= hi_z:
            continue  # свежий возврат

        # 15m слом
        try:
            st15 = structure_trend(d15.iloc[:i + 1], lookback=250)
        except Exception:
            continue
        brk15 = st15.get("break_level")
        entry = price
        if brk15 is not None:
            if bias == "long" and brk15 < entry:
                sl = brk15 * 0.999
            elif bias == "short" and brk15 > entry:
                sl = brk15 * 1.001
            else:
                continue
        else:
            continue
        risk = abs(entry - sl)
        if risk <= 0 or risk / entry * 100 > RISK_CAP:
            continue

        # TP = fib_-1.0 (чемпион SHORT-рецепта)
        fib_val = lv.get(-1.0)
        if fib_val is None:
            continue
        if bias == "long" and fib_val <= entry:
            continue
        if bias == "short" and fib_val >= entry:
            continue
        tp = fib_val

        # Gravity на момент входа
        # Срез данных до входа
        store = {}
        for tf, df in dfs.items():
            s = df[df.index <= t]
            store[tf] = s.iloc[-300:] if len(s) >= 30 else None
        direction = "long" if bias == "long" else "short"
        gravity, n_levels = calc_gravity(entry, direction, store, t)

        pos = {"dir": bias, "entry": entry, "sl": sl, "tp": tp,
               "ts": t, "gravity": gravity, "n_levels": n_levels}

    return trades


def main():
    print("=" * 66)
    print("DS-GRAVITY-TRI: GRAVITY-триангуляция SHORT-рецепта")
    print(f"Источник: ohlcv_cache.db ({DB})")
    print(f"Символов: {len(SYMBOLS)}")
    print(f"Costs: {COST_PCT}%")
    print(f"Выход: fib_-1.0 (SHORT-рецепт)")
    print(f"Мера: % net = ход% - costs")
    print("=" * 66)

    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()

    all_trades = []
    for sym in SYMBOLS:
        t0 = time.time()
        dfs = load_symbol(cur, sym)
        if not dfs:
            print(f"  {sym:5} нет данных в БД")
            continue
        if "15m" not in dfs or "1h" not in dfs:
            print(f"  {sym:5} нет 15m/1h")
            continue

        trades = simulate_symbol(sym, dfs)
        all_trades.extend(trades)
        dt = time.time() - t0
        print(f"  {sym:5} | {len(trades):>3} трейдов | {dt:.1f}с")
        if len(all_trades) >= 10000:
            print("  ... лимит 10000 трейдов, стоп")
            break

    conn.close()

    print("\n" + "=" * 66)
    print(f"ВСЕГО: {len(all_trades)} трейдов")
    print("=" * 66)

    if not all_trades:
        print("Нет данных для анализа.")
        return

    # Итог по всем
    nets = [t["net"] for t in all_trades]
    wr = sum(1 for t in all_trades if t["win"]) / len(all_trades) * 100
    print(f"ALL   n={len(all_trades):>5} WR={wr:>4.0f}% mean={st.mean(nets):+.3f}% sum={sum(nets):+.1f}%")

    # Бакеты по gravity
    buckets = [
        ("gravity 0 (нет уровней)", lambda g: g == 0),
        ("gravity 0-10 (слабая)", lambda g: 0 < g <= 10),
        ("gravity 10-40", lambda g: 10 < g <= 40),
        ("gravity 40-100 (сильная)", lambda g: 40 < g <= 100),
        ("gravity 100-200", lambda g: 100 < g <= 200),
        ("gravity 200+ (ракета)", lambda g: g > 200),
    ]

    print(f"\n{'Бакет':<28} {'n':>5} {'WR':>5} {'mean%':>8} {'med%':>8} {'sum%':>8}")
    print("-" * 68)
    for name, fn in buckets:
        ts = [t for t in all_trades if fn(t["gravity"])]
        if not ts:
            print(f"{name:<28} {'n=0':>10}")
            continue
        ns = [t["net"] for t in ts]
        w = sum(1 for t in ts if t["win"]) / len(ts) * 100
        print(f"{name:<28} {len(ts):>5} {w:>4.0f}% {st.mean(ns):>+7.3f} {st.median(ns):>+7.3f} {sum(ns):>+7.1f}")

    # Гранулярные бакеты (для точного порога)
    print(f"\n{'Гранулярные бакеты gravity':^68}")
    print(f"{'Диапазон':<14} {'n':>5} {'WR':>5} {'mean%':>8} {'sum%':>8}")
    for lo in range(0, 210, 10):
        hi = lo + 10
        ts = [t for t in all_trades if lo <= t["gravity"] < hi]
        if len(ts) < 10:
            continue
        ns = [t["net"] for t in ts]
        w = sum(1 for t in ts if t["win"]) / len(ts) * 100
        print(f"{lo:>4}-{hi:<4} {len(ts):>5} {w:>4.0f}% {st.mean(ns):>+7.3f} {sum(ns):>+7.1f}")

    # Поиск порога: минимальный gravity, дающий >=2%/сделку и >=5 сделок
    print(f"\n{'ПОИСК ПОРОГА (>=2%/сделку)':^68}")
    thresholds = []
    for g_thresh in range(0, 300, 5):
        ts = [t for t in all_trades if t["gravity"] >= g_thresh]
        if len(ts) < 5:
            continue
        mean_n = st.mean([t["net"] for t in ts])
        if mean_n >= 2.0:
            thresholds.append((g_thresh, len(ts), mean_n))
    if thresholds:
        print(f"{'Порог':>8} {'n':>6} {'mean%':>8}")
        for g, n, m in thresholds[:15]:
            print(f"  gravity>={g:>3} n={n:>4} mean={m:+.2f}%")
        # Оптимальный порог (минимальный, дающий >=2%)
        best = thresholds[0]
        print(f"\n>> ОПТИМАЛЬНЫЙ ПОРОГ: gravity >= {best[0]} (n={best[1]}, mean={best[2]:+.2f}%/сделку)")
        # сделок/день
        years = 4  # 2022-2026
        per_day = best[1] / (years * 365)
        print(f">> СДЕЛОК/ДЕНЬ на пороге: {per_day:.1f}")
    else:
        print("Порог не найден: ни один бакет не даёт >=2%/сделку при n>=5")

    # Walk-forward OOS split
    print(f"\n{'OOS-СПЛИТ (IS 1я пол / OOS 2я)':^68}")
    sorted_trades = sorted(all_trades, key=lambda x: x["ts"])
    mid = len(sorted_trades) // 2
    for label, part in [("IS (1я пол)", sorted_trades[:mid]), ("OOS (2я пол)", sorted_trades[mid:])]:
        ns = [t["net"] for t in part]
        w = sum(1 for t in part if t["win"]) / len(part) * 100
        print(f"  {label:14} n={len(part):>5} WR={w:>4.0f}% mean={st.mean(ns):+.3f}% sum={sum(ns):+.1f}%")

    # По бакетам OOS-сплит
    print(f"\n{'OOS-СПЛИТ ПО БАКЕТАМ':^68}")
    for name, fn in buckets:
        is_ts = [t for t in sorted_trades[:mid] if fn(t["gravity"])]
        oos_ts = [t for t in sorted_trades[mid:] if fn(t["gravity"])]
        is_n = st.mean([t["net"] for t in is_ts]) if is_ts else 0
        oos_n = st.mean([t["net"] for t in oos_ts]) if oos_ts else 0
        print(f"  {name:<28} IS={is_n:+.3f}% (n={len(is_ts):>3}) OOS={oos_n:+.3f}% (n={len(oos_ts):>3})")

    # По числу уровней
    print(f"\n{'avgR по числу уровней (n_levels)':^68}")
    for lo, hi in [(0, 0), (1, 2), (3, 4), (5, 7), (8, 15), (16, 99)]:
        ts = [t for t in all_trades if lo <= t["n_levels"] <= hi]
        if not ts:
            continue
        ns = [t["net"] for t in ts]
        w = sum(1 for t in ts if t["win"]) / len(ts) * 100
        print(f"  levels {lo:>2}-{hi:>2} n={len(ts):>4} WR={w:>3.0f}% mean={st.mean(ns):+.3f}%")

    print(f"\ncosts={COST_PCT}% | зона=1h OTE | SL=15m-слом | TP=fib_-1.0 | вход=свежий возврат")
    print(f"gravity: alpha={ALPHA}, near={NEAR_PCT}% | source=ohlcv_cache.db (Binance)")


if __name__ == "__main__":
    main()
