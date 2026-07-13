# -*- coding: utf-8 -*-
"""PP-BOUNCE — бэктест ядра «Слой 1» (08.07, свобода Егора «полный доступ, действуй»).

Гипотеза (из ETH-исследования 06.06-08.07): дневной PP = лучший уровень месяца (отбой 62%
из 60 касаний), коррекции ложатся в OTE 60-70%. Ядро: mean-reversion от дневного PP.

Механика (честная, по стандартам проекта):
  - пивоты classic floor от ВЧЕРАШНЕГО дня (никакого look-ahead);
  - первое касание PP за день (лимитка на PP = fill по touch);
  - сторона: цена пришла СВЕРХУ (open дня > PP) → LONG-отбой; СНИЗУ → SHORT-отбой;
  - SL за уровень 0.4%; TP = следующий пивот по стороне (LONG→R1, SHORT→S1);
  - RR-гейт: dist(TP) >= 1×риск (урок спринта);
  - интрабар SL-first, costs 0.15% (лимит-вход + market-выход), timeout 48×1h баров.
Слои (флаги):
  --wt      WT(10,21) 1h фаза-триггер: LONG только wt1<0 (нижняя половина), SHORT wt1>0;
  --wconf   конфлюэнция: |PP − ближайший недельный пивот| < 0.3% цены;
  --regime  разрез по USDT.D-режиму (ряд с 2025-09): risk-on → только LONG, risk-off → SHORT.
Запуск: python scripts/test_pp_bounce.py [--wt] [--wconf] [--regime]
"""
import sys, sqlite3, time
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
import numpy as np

SYMS = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "LINK", "AVAX", "DOT",
        "LTC", "ARB", "OP", "NEAR", "ATOM", "UNI", "AAVE", "FIL", "INJ", "SEI"]
SL_PCT = 0.4
COSTS = 0.15
TIMEOUT = 48
USE_WT = "--wt" in sys.argv
USE_WCONF = "--wconf" in sys.argv
USE_REGIME = "--regime" in sys.argv


def load(sym: str, tf: str) -> pd.DataFrame | None:
    c = sqlite3.connect("ohlcv_cache.db")
    df = pd.read_sql_query(
        "SELECT time, open, high, low, close FROM ohlcv_cache "
        "WHERE symbol=? AND timeframe=? ORDER BY time", c, params=(f"{sym}/USDT", tf))
    c.close()
    if len(df) < 2000:
        return None
    df.index = pd.to_datetime(df["time"], unit="ms")
    return df[["open", "high", "low", "close"]]


def wt1(closes: pd.Series) -> pd.Series:
    esa = closes.ewm(span=10, adjust=False).mean()
    d = (closes - esa).abs().ewm(span=10, adjust=False).mean()
    ci = (closes - esa) / (0.015 * d.replace(0, np.nan))
    return ci.ewm(span=21, adjust=False).mean().fillna(0)


def usdtd_regime_by_date() -> dict:
    """date -> True(risk-off)/False(risk-on); только период, где есть ряд."""
    try:
        from core.signals.usdtd_regime import _series, _MA_LEN
        conn = sqlite3.connect("ohlcv_cache.db")
        ser = _series(conn)
        conn.close()
        out = {}
        vals = []
        for d, v in ser:
            vals.append(v)
            if len(vals) >= _MA_LEN:
                out[d] = v > sum(vals[-_MA_LEN:]) / _MA_LEN
        return out
    except Exception:
        return {}


REGIME = usdtd_regime_by_date() if USE_REGIME else {}


def run_symbol(sym: str) -> list[dict]:
    h1 = load(sym, "1h")
    if h1 is None:
        return []
    d1 = h1.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    piv = {}
    for i in range(1, len(d1)):
        p = d1.iloc[i - 1]
        pp = (p["high"] + p["low"] + p["close"]) / 3
        piv[d1.index[i].strftime("%Y-%m-%d")] = {
            "PP": pp, "R1": 2 * pp - p["low"], "S1": 2 * pp - p["high"]}
    # недельные для --wconf
    wpiv = {}
    if USE_WCONF:
        w = h1.resample("W").agg({"high": "max", "low": "min", "close": "last"}).dropna()
        for i in range(1, len(w)):
            p = w.iloc[i - 1]
            pp = (p["high"] + p["low"] + p["close"]) / 3
            wpiv[w.index[i]] = [pp, 2 * pp - p["low"], 2 * pp - p["high"],
                                pp + (p["high"] - p["low"]), pp - (p["high"] - p["low"])]
    wt = wt1(h1["close"]) if USE_WT else None
    o, h, l, c = (h1[k].values for k in ("open", "high", "low", "close"))
    idx = h1.index
    n = len(h1)
    out = []
    done_days = set()
    for j in range(24, n - 1):
        day = idx[j].strftime("%Y-%m-%d")
        pv = piv.get(day)
        if pv is None or day in done_days:
            continue
        pp = pv["PP"]
        if not (l[j] <= pp <= h[j]):
            continue
        done_days.add(day)                      # одно касание PP в день
        side = "LONG" if o[j] > pp else "SHORT" # пришли сверху → поддержка → LONG
        if USE_REGIME:
            r = REGIME.get(day)
            if r is None:
                continue                        # нет данных режима — не считаем
            if r and side == "LONG":            # risk-off → только SHORT
                continue
            if (not r) and side == "SHORT":     # risk-on → только LONG
                continue
        if USE_WT and wt is not None:
            wv = float(wt.iloc[j - 1])          # фаза на ПРЕДЫДУЩЕМ баре (без подглядывания)
            if side == "LONG" and wv > 0:
                continue
            if side == "SHORT" and wv < 0:
                continue
        if USE_WCONF:
            wk_key = None
            for wk_ts in wpiv:
                if wk_ts >= idx[j]:
                    wk_key = wk_ts
                    break
            levels = wpiv.get(wk_key, [])
            if not levels or min(abs(pp - x) / pp for x in levels) > 0.003:
                continue
        entry = pp
        if "--swingsl" in sys.argv:
            # ЗАКОН проекта: стоп за СТРУКТУРУ (урок atr_S2: утроил эдж). Swing 12×1h + буфер 0.2%
            if side == "LONG":
                sl = float(l[max(0, j - 12):j].min()) * 0.998
                if sl >= entry:
                    continue
            else:
                sl = float(h[max(0, j - 12):j].max()) * 1.002
                if sl <= entry:
                    continue
        else:
            sl = pp * (1 - SL_PCT / 100) if side == "LONG" else pp * (1 + SL_PCT / 100)
        tp = pv["R1"] if side == "LONG" else pv["S1"]
        risk = abs(entry - sl)
        if risk / entry > 0.05:                 # санити: риск >5% = мусор
            continue
        if abs(tp - entry) < risk:              # RR-гейт >= 1
            continue
        sl_loss = abs(entry - sl) / entry * 100
        res = None
        for k in range(j, min(j + TIMEOUT, n)):
            hit_sl = (l[k] <= sl) if side == "LONG" else (h[k] >= sl)
            hit_tp = (h[k] >= tp) if side == "LONG" else (l[k] <= tp)
            if hit_sl:                           # SL-first консервативно
                res = -sl_loss - COSTS
                break
            if hit_tp:
                res = abs(tp - entry) / entry * 100 - COSTS
                break
        if res is None:                          # timeout — закрытие по close
            end = c[min(j + TIMEOUT, n - 1)]
            res = ((end - entry) / entry * 100 if side == "LONG"
                   else (entry - end) / entry * 100) - COSTS
        out.append({"sym": sym, "side": side, "year": idx[j].year, "day": day, "pnl": res})
    return out


def main():
    t0 = time.time()
    rows = []
    for s in SYMS:
        r = run_symbol(s)
        rows += r
    df = pd.DataFrame(rows)
    tag = " ".join(x for x, f in (("WT", USE_WT), ("WCONF", USE_WCONF), ("REGIME", USE_REGIME)) if f) or "base"
    print(f"=== PP-BOUNCE [{tag}] 1h × {len(SYMS)} монет · SL {SL_PCT}% · TP=R1/S1 · costs {COSTS}% "
          f"({time.time()-t0:.0f}s) ===")
    if df.empty:
        print("нет сделок")
        return
    v = df["pnl"]
    print(f"ИТОГО: n={len(v)} avg={v.mean():+.3f}% · WR={(v>0).mean()*100:.0f}% · sum={v.sum():+.0f}%")
    for side, g in df.groupby("side"):
        print(f"  {side}: n={len(g)} avg={g['pnl'].mean():+.3f}% WR={(g['pnl']>0).mean()*100:.0f}%")
    for yr, g in df.groupby("year"):
        if len(g) >= 50:
            print(f"  {yr}: n={len(g):5} avg={g['pnl'].mean():+.3f}% WR={(g['pnl']>0).mean()*100:.0f}%")


if __name__ == "__main__":
    main()
