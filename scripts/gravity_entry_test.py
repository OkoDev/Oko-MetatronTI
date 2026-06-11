"""
GRAVITY-НА-ВХОДЕ → avgR — валидация «баллистической ракеты» (11.06.2026).

Гипотеза (юзер): вход в точке МАКСИМАЛЬНОЙ MTF-конфлюенции (пивот+swing+FVG+OTE
совпали рядом) = edge. ote_nested (+2.08) = частный случай (OTE-конфлюенция).
Полный gravity-вход = ВСЕ типы уровней → потенциально сильнее.

Метод (переиспользует механику tp_selector: gravity=Σw/dist^1.5):
  Для каждой закрытой сделки с локальной историей:
    1. срез df до входа (created_at)
    2. собрать уровни рядом с entry_price (dist<3%): daily-пивоты (PP/S/R),
       swing H/L (zigzag 11/3), FVG, OTE-зона
    3. gravity = Σ [вес_типа / dist_pct^1.5] по уровням рядом
    4. бакеты gravity → avgR (растёт ли edge с конфлюенцией?)

Вывод: data/research/2026-06-11--gravity-entry/result.md
"""
import sqlite3, sys, statistics as st
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.smc.smc_engine import zigzag_atr, ote_retest_setups

H = {"5m": Path("data/history/5m"), "15m": Path("data/history/15m"), "1h": Path("data/history/1h")}
ALPHA = 1.5          # tp_selector: score = gravity/dist^1.5 (доказан)
NEAR_PCT = 3.0       # уровни в пределах 3% от entry
W = {"pivot": 2.0, "swing": 2.0, "fvg": 1.5, "ote": 2.5}     # веса ТИПА
WTF = {"5m": 1.0, "15m": 1.5, "1h": 2.5, "4h": 3.5, "1d": 5.0, "1w": 7.0}  # веса ТФ (HTF≫LTF, mtf_weight_hierarchy)

def _norm(df):
    df.columns = [c.lower() for c in df.columns]
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    return df

def load_tf(base, tf):
    for cand in (f"{base}USDT", base):
        p = H[tf] / f"{cand}.parquet"
        if p.exists():
            return _norm(pd.read_parquet(p))
    return None

def agg(df1h, rule):
    if df1h is None or not isinstance(df1h.index, pd.DatetimeIndex):
        return None
    o = df1h.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()
    return o if len(o) > 20 else None

def _pivots(df):
    """Классические пивоты из последнего полного бара ТФ."""
    if df is None or len(df) < 2:
        return []
    H_, L_, C_ = df["high"].iloc[-2], df["low"].iloc[-2], df["close"].iloc[-2]
    pp = (H_ + L_ + C_) / 3
    return [pp, 2 * pp - L_, 2 * pp - H_, pp + (H_ - L_), pp - (H_ - L_)]

def _tf_levels(df, td):
    """Уровни одного ТФ: swing(zigzag) + FVG + OTE."""
    lv = []
    if df is None or len(df) < 60:
        return lv
    try:
        for _ts, zp in zigzag_atr(df, 11, 3)[-6:]:
            lv.append((zp, "swing"))
    except Exception:
        pass
    try:
        h, l = df["high"].values, df["low"].values
        for i in range(max(0, len(df) - 30), len(df) - 2):
            if l[i + 2] > h[i]:
                lv.append(((l[i + 2] + h[i]) / 2, "fvg"))
            elif h[i + 2] < l[i]:
                lv.append(((h[i + 2] + l[i]) / 2, "fvg"))
    except Exception:
        pass
    try:
        for s in ote_retest_setups(df):
            if s["direction"] == td:
                lo, hi = s["ote"]
                lv.append(((lo + hi) / 2, "ote")); break
    except Exception:
        pass
    return lv

def gravity_at(store, price, td):
    """MTF-gravity: уровни со ВСЕХ ТФ × вес_ТФ. store={tf: df}."""
    if price <= 0:
        return 0.0, 0
    typed = []  # (level_price, type, tf)
    # пивоты: 1d/1w (HTF-якоря)
    for tf in ("1d", "1w"):
        for pv in _pivots(store.get(tf)):
            typed.append((pv, "pivot", tf))
    # swing/FVG/OTE: все ТФ
    for tf in ("5m", "15m", "1h", "4h"):
        df = store.get(tf)
        for lp, typ in _tf_levels(df, td):
            typed.append((lp, typ, tf))
    g = 0.0; cnt = 0
    for lp, typ, tf in typed:
        if lp <= 0:
            continue
        dist = abs(lp - price) / price * 100
        if dist <= NEAR_PCT:
            g += W.get(typ, 1.0) * WTF.get(tf, 1.0) / max(dist, 0.05) ** ALPHA
            cnt += 1
    return g, cnt

def main():
    c = sqlite3.connect("subscriptions.db")
    rows = c.execute("""SELECT symbol, direction, R_multiple, entry_price, created_at
        FROM simulated_trades WHERE status!='OPEN' AND R_multiple IS NOT NULL
          AND entry_price>0 ORDER BY id DESC LIMIT 6000""").fetchall()
    c.close()
    cache = {}
    res = []  # (gravity, n_levels, R)
    for sym, direction, R, ep, ca in rows:
        base = sym.split("/")[0]
        if base not in cache:
            d1h = load_tf(base, "1h")
            cache[base] = {"5m": load_tf(base, "5m"), "15m": load_tf(base, "15m"), "1h": d1h,
                           "4h": agg(d1h, "4h"), "1d": agg(d1h, "1d"), "1w": agg(d1h, "1w")}
        full = cache[base]
        if full["15m"] is None:
            continue
        try:
            ets = pd.Timestamp(ca)
            if ets.tz is not None:
                ets = ets.tz_convert("UTC").tz_localize(None)
            ep = float(ep); R = float(R)
        except Exception:
            continue
        store = {}
        for tf, df in full.items():
            if df is None:
                store[tf] = None; continue
            sl = df[df.index <= ets]
            store[tf] = sl.iloc[-300:] if len(sl) >= 30 else None
        if store["15m"] is None or len(store["15m"]) < 60:
            continue
        td = "long" if str(direction).upper() == "LONG" else "short"
        g, cnt = gravity_at(store, ep, td)
        res.append((g, cnt, R))

    def S(lst):
        if not lst: return "n=  0"
        return (f"n={len(lst):>4} avgR={sum(lst)/len(lst):+.3f} med={st.median(lst):+.3f} "
                f"WR={100*sum(1 for x in lst if x>0)/len(lst):.0f}%")
    # бакеты по gravity
    out = ["# GRAVITY-НА-ВХОДЕ MTF → avgR (валидация ракеты) — 11.06.2026\n",
           f"Обработано: {len(res)} сделок. MTF-уровни (5m/15m/1h/4h/1d/1w): пивот+swing+FVG+OTE × вес_ТФ, dist<{NEAR_PCT}%\n"]
    buckets = [("gravity 0 (нет уровней)", lambda g: g == 0),
               ("gravity 0-5 (слабая)",    lambda g: 0 < g <= 5),
               ("gravity 5-15",            lambda g: 5 < g <= 15),
               ("gravity 15-40 (сильная)", lambda g: 15 < g <= 40),
               ("gravity 40-100",          lambda g: 40 < g <= 100),
               ("gravity 100+ (РАКЕТА)",   lambda g: g > 100)]
    out.append("## avgR по gravity-бакетам (растёт ли edge с конфлюенцией?)")
    for name, f in buckets:
        rs = [R for g, _, R in res if f(g)]
        out.append(f"  {name:<26} {S(rs)}")
    # по числу совпавших уровней
    out.append("\n## avgR по числу уровней рядом (n_levels)")
    for lo, hi in [(0, 0), (1, 2), (3, 4), (5, 7), (8, 99)]:
        rs = [R for _, cnt, R in res if lo <= cnt <= hi]
        out.append(f"  уровней {lo}-{hi if hi<99 else '8+':<3} {S(rs)}")
    txt = "\n".join(out)
    print(txt)
    od = Path("data/research/2026-06-11--gravity-entry")
    od.mkdir(parents=True, exist_ok=True)
    (od / "result.md").write_text(txt, encoding="utf-8")
    print(f"\n→ {od/'result.md'}")

if __name__ == "__main__":
    main()
