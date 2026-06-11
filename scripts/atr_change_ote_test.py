"""
ATR-CHANGE × OTE backtest MTF v2 (REGIME-V2 шаг 2, 11.06.2026).

Гипотеза (юзер): atr_change = ATRTrend ±1 (направление верное), но СЛЕП к структуре.
atr_change входит на ВСПЛЕСКЕ → садится НИЖЕ OTE (поздно). OTE-зона (откат) = правильный вход.

Метод (массовый): OTE считаем САМ из последней ноги ZigZag (zigzag_atr 11/3 = OKO-SM),
фибо 0.5-0.79. Для каждой atr_change сделки на каждом ТФ (5m/15m/1h/4h):
  - последняя нога нужного направления (SHORT=нога вниз→откат вверх; LONG=нога вверх→откат вниз)
  - зона OTE [0.5, 0.79]; entry in / below(поздно) / above(рано)
  - recency: нога завершилась ≤ N баров до входа
Сравниваем avgR по позиции — есть ли edge у входа В OTE.

Вывод: data/research/2026-06-11--atr-change-ote/result_mtf.md
"""
import sqlite3, sys, statistics as st
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.smc.smc_engine import zigzag_atr

H = {"5m": Path("data/history/5m"), "15m": Path("data/history/15m"), "1h": Path("data/history/1h")}
LEG_RECENCY = 80   # нога завершилась не дальше N баров назад

def _norm(df):
    df.columns = [c.lower() for c in df.columns]
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    return df

def load(base, tf):
    for cand in (f"{base}USDT", base):
        p = H[tf] / f"{cand}.parquet"
        if p.exists():
            return _norm(pd.read_parquet(p))
    return None

def agg4h(d1h):
    if d1h is None or not isinstance(d1h.index, pd.DatetimeIndex):
        return None
    o = d1h.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                 "close": "last", "volume": "sum"}).dropna()
    return o if len(o) > 50 else None

def ote_pos(dfx, td, ep):
    """Позиция entry относительно OTE 0.5-0.79 последней ноги нужного направления."""
    try:
        zz = zigzag_atr(dfx, 11, 3)
    except Exception:
        return None, None
    if len(zz) < 2:
        return None, None
    (a_ts, a), (b_ts, b) = zz[-2], zz[-1]
    # recency ноги
    bars_since = len(dfx[dfx.index > b_ts])
    if bars_since > LEG_RECENCY:
        return None, None
    leg_down = a > b                       # импульс вниз (high→low)
    if td == "short" and not leg_down:     # SHORT нужен импульс вниз → откат вверх
        return None, None
    if td == "long" and leg_down:          # LONG нужен импульс вверх → откат вниз
        return None, None
    hi, lo = max(a, b), min(a, b)
    rng = hi - lo
    if rng <= 0:
        return None, None
    if td == "short":                      # откат вверх: зона между 0.5 и 0.79 от low
        o_lo, o_hi = lo + 0.5 * rng, lo + 0.79 * rng
    else:                                  # long откат вниз
        o_lo, o_hi = hi - 0.79 * rng, hi - 0.5 * rng
    if ep < o_lo:
        return "below", 100 * (o_lo - ep) / ep
    if ep > o_hi:
        return "above", 100 * (ep - o_hi) / ep
    return "in", 0.0

def main():
    c = sqlite3.connect("subscriptions.db")
    rows = c.execute("""SELECT symbol, direction, R_multiple, entry_price, created_at
        FROM simulated_trades WHERE signal_type='atr_change' AND status!='OPEN'
          AND R_multiple IS NOT NULL AND entry_price IS NOT NULL""").fetchall()
    c.close()
    cache = {}
    TFS = ["5m", "15m", "1h", "4h"]
    agg = {tf: {"in": [], "below": [], "above": [], "none": []} for tf in TFS}
    dist = {tf: [] for tf in TFS}
    tot = 0
    for sym, direction, R, ep, ca in rows:
        base = sym.split("/")[0]
        if base not in cache:
            d1h = load(base, "1h")
            cache[base] = {"5m": load(base, "5m"), "15m": load(base, "15m"),
                           "1h": d1h, "4h": agg4h(d1h)}
        store = cache[base]
        if store["15m"] is None:
            continue
        try:
            ets = pd.Timestamp(ca)
            if ets.tz is not None:
                ets = ets.tz_convert("UTC").tz_localize(None)
            ep = float(ep); R = float(R)
        except Exception:
            continue
        td = "long" if str(direction).upper() == "LONG" else "short"
        used = False
        for tf in TFS:
            df = store[tf]
            if df is None:
                continue
            dfx = df[df.index <= ets]
            if len(dfx) < 120:
                continue
            dfx = dfx.iloc[-400:]
            pos, d = ote_pos(dfx, td, ep)
            agg[tf][pos if pos else "none"].append(R)
            if pos == "below" and d is not None:
                dist[tf].append(d)
            used = True
        if used:
            tot += 1

    def S(l):
        if not l: return "n=  0"
        return (f"n={len(l):>4} avgR={sum(l)/len(l):+.3f} med={st.median(l):+.3f} "
                f"WR={100*sum(1 for x in l if x>0)/len(l):.0f}% sumR={sum(l):+7.1f}")
    out = ["# ATR-CHANGE × OTE MTF backtest v2 — 11.06.2026 (REGIME-V2 шаг 2)\n",
           f"Обработано: {tot} | OTE 0.5-0.79 от последней ноги ZigZag(11/3), recency ≤{LEG_RECENCY} баров\n"]
    for tf in TFS:
        a = agg[tf]
        out.append(f"\n## OTE на {tf}")
        out.append(f"  В OTE (откат, оптимум):  {S(a['in'])}")
        out.append(f"  НИЖЕ OTE (поздно/импульс): {S(a['below'])}" +
                   (f"  [медиана {st.median(dist[tf]):.1f}% ниже]" if dist[tf] else ""))
        out.append(f"  ВЫШЕ OTE (рано):         {S(a['above'])}")
        out.append(f"  нет ноги направления:    {S(a['none'])}")
    txt = "\n".join(out)
    print(txt)
    od = Path("data/research/2026-06-11--atr-change-ote")
    od.mkdir(parents=True, exist_ok=True)
    (od / "result_mtf.md").write_text(txt, encoding="utf-8")
    print(f"\n→ {od/'result_mtf.md'}")

if __name__ == "__main__":
    main()
