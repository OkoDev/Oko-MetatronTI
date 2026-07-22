# -*- coding: utf-8 -*-
"""OTE-EGOR-LEG — решающий бэктест: ожидающий лимит на НОГАХ ЕГОРА (23.07).

Нога = oko_sm_engine (порт OKO-SM v163, верифицирован 1:1 с графиком: BTC 15/15, ETH 13/13).
Правило Егора (23.07, прямая речь): «пока структура старшего не сломана — внутреннее движение
коррекционно; на OTE-зоне старшего развилка: откат от зоны → сопровождать ПО старшему на
обновление экстремума; пробой насквозь → слом (это наш SL за fib 1.0)».

Механика (каузально: нога бара t-1 → решение на баре t):
  senior trend определён → ожидающий лимит на fib F старшей ноги (retracement к origin),
  направление ПО тренду. SL за fib 1.0 (origin ± буфер). TP = extreme (fib 0, «обновление»).
  Нога растёт (trail) → лимит переставляется. Тренд флипнул → pending отмена; позиция живёт до SL/TP.
  Fill: касание лимита баром. Конфликт в баре: SL приоритет (консервативно).

Свип fib: 0.618 / 0.705 / 0.786 / 0.886. net% = ход − costs (0.1%). ЗАКОН №1.
Данные: ohlcv_cache 4h (2022-01..2026-05), топ-N ликвидных. По годам + LONG/SHORT.
Запуск: python scripts/ote_egor_leg_backtest.py [--syms 50]
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import sqlite3
from datetime import datetime, timezone

import pandas as pd

from core.smc.oko_sm_engine import run_structure

CACHE = "ohlcv_cache.db"
FIBS = (0.618, 0.705, 0.786, 0.886)
COSTS = 0.10
SL_BUF = 0.0015


def _liquid_universe(o, n):
    """Топ-N по $-обороту (avg volume*close последних 2000 баров 4h)."""
    syms = [r[0] for r in o.execute(
        "SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='4h' AND symbol NOT LIKE '%:%'")]
    turn = []
    for s in syms:
        r = o.execute(
            "SELECT AVG(volume*close) FROM (SELECT volume, close FROM ohlcv_cache "
            "WHERE symbol=? AND timeframe='4h' ORDER BY time DESC LIMIT 2000)", (s,)).fetchone()
        if r and r[0]:
            turn.append((s, r[0]))
    turn.sort(key=lambda x: -x[1])
    return [s for s, _ in turn[:n]]


def _load(o, sym):
    rows = o.execute("SELECT time,open,high,low,close FROM ohlcv_cache "
                     "WHERE symbol=? AND timeframe='4h' ORDER BY time", (sym,)).fetchall()
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])


def backtest_symbol(df, fib):
    """→ list[(year, dir, net%)] по правилу Егора для одного fib.
    Ит.2 (фикс 3 нарушений): SL-буфер=1×ATR20 за origin (ЗАКОН свипа), TP=2R (тугой стоп-
    большая цель без всё-или-ничего), нога ≥ 4×ATR (шум-фильтр после флипов)."""
    st = run_structure(df, record_legs=True)
    legs = st.leg_history
    hv, lv, tv = df["high"].values, df["low"].values, df["time"].values
    tr_ = (df["high"] - df["low"]).rolling(20).mean().values   # ATR-прокси (H-L mean)
    # OkoTrend (порт 1:1 из OkoTrend v171): WT + медиана EMA200 + направление медианы
    ap = (df["high"] + df["low"] + df["close"]) / 3
    esa = ap.ewm(span=10, adjust=False).mean()
    dd = (ap - esa).abs().ewm(span=10, adjust=False).mean()
    ci = (ap - esa) / (0.015 * dd)
    wt1s = ci.ewm(span=21, adjust=False).mean()
    wt2s = wt1s.rolling(4).mean()
    mas = wt1s.ewm(span=200, adjust=False).mean()
    wt1v, wt2v, mav = wt1s.values, wt2s.values, mas.values
    n = len(df)
    trades = []
    pos = None      # dict(dir, entry, sl, tp, t_in)
    prev_leg = None                 # предыдущий импульс (до флипа) — сетка-сосед для конфлюэнции
    _last = None
    GRID = (0.0, 0.382, 0.5, 0.618, 0.705, 0.786, 1.0, -0.27, -0.62)
    def _conf(price):
        if prev_leg is None or not price:
            return False
        po, pe = prev_leg["origin"], prev_leg["extreme"]
        for f in GRID:
            lvl = pe - f * (pe - po)
            if lvl > 0 and abs(price - lvl) / price <= 0.003:
                return True
        return False
    for t in range(1, n):
        leg = legs[t - 1]           # нога ПОСЛЕ бара t-1 — каузально
        if leg is not None and _last is not None and leg["trend"] != _last["trend"]:
            prev_leg = _last        # флип → ушедшая нога = сосед-сетка
        if leg is not None:
            _last = leg
        # управление открытой позицией (SL приоритет)
        if pos is not None:
            if pos["dir"] == "long":
                if lv[t] <= pos["sl"]:
                    exitp = pos["sl"]
                elif hv[t] >= pos["tp"]:
                    exitp = pos["tp"]
                else:
                    exitp = None
                if exitp is not None:
                    net = (exitp - pos["entry"]) / pos["entry"] * 100 - COSTS
                    trades.append((datetime.fromtimestamp(tv[t] / 1000, timezone.utc).year, "LONG", net, pos["conf"], pos["wt"]))
                    pos = None
            else:
                if hv[t] >= pos["sl"]:
                    exitp = pos["sl"]
                elif lv[t] <= pos["tp"]:
                    exitp = pos["tp"]
                else:
                    exitp = None
                if exitp is not None:
                    net = (pos["entry"] - exitp) / pos["entry"] * 100 - COSTS
                    trades.append((datetime.fromtimestamp(tv[t] / 1000, timezone.utc).year, "SHORT", net, pos["conf"], pos["wt"]))
                    pos = None
            continue                 # одна позиция на символ; pending не работает пока в позиции

        if leg is None:
            continue
        o_, e_ = leg["origin"], leg["extreme"]
        atr = tr_[t - 1]
        if not atr or atr != atr:
            continue
        if abs(e_ - o_) < 4 * atr:          # нога-шум после флипа — не торгуем
            continue
        if leg["trend"] == "long":
            # откат ВНИЗ к origin: fib f цена = extreme - f*(extreme-origin)
            lim = e_ - fib * (e_ - o_)
            sl = o_ - 1.0 * atr             # ЗАКОН: стоп ЗА свип-зону origin (1×ATR)
            if lim <= sl or sl <= 0:
                continue
            if lv[t] <= lim:         # ожидающий лимит-BUY зафилился
                entry = lim
                tp = entry + 2 * (entry - sl)      # 2R
                _cf = _conf(entry)
                _wt = {"wt": wt1v[t-1], "x_up": wt1v[t-1] > wt2v[t-1], "vs_ma": wt1v[t-1] - mav[t-1],
                       "ma_up": mav[t-1] > mav[t-2] if t >= 2 else False}
                if lv[t] <= sl:
                    net = (sl - entry) / entry * 100 - COSTS
                    trades.append((datetime.fromtimestamp(tv[t] / 1000, timezone.utc).year, "LONG", net, _cf, _wt))
                else:
                    pos = {"dir": "long", "entry": entry, "sl": sl, "tp": tp, "t_in": t, "conf": _cf, "wt": _wt}
        else:
            lim = e_ + fib * (o_ - e_)
            sl = o_ + 1.0 * atr
            if lim >= sl:
                continue
            if hv[t] >= lim:
                entry = lim
                tp = entry - 2 * (sl - entry)
                _cf = _conf(entry)
                _wt = {"wt": wt1v[t-1], "x_up": wt1v[t-1] > wt2v[t-1], "vs_ma": wt1v[t-1] - mav[t-1],
                       "ma_up": mav[t-1] > mav[t-2] if t >= 2 else False}
                if hv[t] >= sl:
                    net = (entry - sl) / entry * 100 - COSTS
                    trades.append((datetime.fromtimestamp(tv[t] / 1000, timezone.utc).year, "SHORT", net, _cf, _wt))
                else:
                    pos = {"dir": "short", "entry": entry, "sl": sl, "tp": tp, "t_in": t, "conf": _cf, "wt": _wt}
    return trades


def _st(a):
    if not a:
        return 0, 0.0, 0.0
    return len(a), 100 * sum(1 for x in a if x > 0) / len(a), sum(a) / len(a)


def main():
    nsyms = 50
    if "--syms" in sys.argv:
        nsyms = int(sys.argv[sys.argv.index("--syms") + 1])
    o = sqlite3.connect(CACHE)
    uni = _liquid_universe(o, nsyms)
    print(f"🏛️ OTE НА НОГАХ ЕГОРА (oko_sm_engine) · 4h 2022-2026 · топ-{len(uni)} ликвидных")
    print(f"   правило: лимит на fib старшей ноги ПО тренду · SL за fib1.0 · TP=extreme\n")
    allres = {f: [] for f in FIBS}
    for i, sym in enumerate(uni):
        df = _load(o, sym)
        if len(df) < 300:
            continue
        for f in FIBS:
            allres[f].extend(backtest_symbol(df, f))
        if (i + 1) % 10 == 0:
            print(f"   … {i+1}/{len(uni)} символов")
    print(f"\n{'fib':>7} {'n':>6} {'WR':>5} {'net/сд':>9} | LONG net (n) | SHORT net (n)")
    print("   " + "─" * 66)
    for f in FIBS:
        tr = allres[f]
        n, wr, net = _st([x[2] for x in tr])
        cy = [x[2] for x in tr if x[3]]
        cn = [x[2] for x in tr if not x[3]]
        ncy, wrcy, netcy = _st(cy)
        ncn, _, netcn = _st(cn)
        mark = "🟢" if net > 0.10 else ("🔴" if net < -0.10 else "⚪")
        cmark = "🟢" if netcy > 0.10 else ("🔴" if netcy < -0.10 else "⚪")
        print(f"{mark} {f:5.3f} {n:6} {wr:4.0f}% {net:+8.3f}% | conf=ДА {cmark} n={ncy:4} WR{wrcy:3.0f}% {netcy:+7.3f}% | conf=нет n={ncn} {netcn:+7.3f}%")
    # WT-РАЗРЕЗЫ (задание Егора «сравни зависимости»): fib 0.886, wt зеркалим для SHORT
    print("\n── ЗАВИСИМОСТЬ ОТ OkoTrend (fib 0.886, WT в момент филла; для SHORT знак зеркален) ──")
    tr886 = allres[0.886]
    def _mir(x):
        w = x[4]
        sgn = 1 if x[1] == "LONG" else -1
        return {"wt": sgn * w["wt"], "x_al": (w["x_up"] if x[1]=="LONG" else not w["x_up"]),
                "vs_ma": sgn * w["vs_ma"], "ma_al": (w["ma_up"] if x[1]=="LONG" else not w["ma_up"]), "net": x[2]}
    mm = [_mir(x) for x in tr886 if len(x) > 4]
    def _b(rows, label):
        n, wr, net = _st([r["net"] for r in rows])
        if n: 
            mk = "🟢" if net > 0.10 else ("🔴" if net < -0.10 else "⚪")
            print(f"   {mk} {label:34} n={n:5} WR{wr:3.0f}% net={net:+.3f}%")
    _b([r for r in mm if r["wt"] < -60], "WT экстремум ЗА вход (<-60)")
    _b([r for r in mm if -60 <= r["wt"] < -30], "WT -60..-30")
    _b([r for r in mm if -30 <= r["wt"] < 0], "WT -30..0")
    _b([r for r in mm if r["wt"] >= 0], "WT >0 (против входа)")
    _b([r for r in mm if r["x_al"]], "кросс WT ПО входу")
    _b([r for r in mm if not r["x_al"]], "кросс WT против")
    _b([r for r in mm if r["vs_ma"] > 0], "WT выше медианы (по входу)")
    _b([r for r in mm if r["vs_ma"] <= 0], "WT ниже медианы")
    _b([r for r in mm if r["ma_al"]], "медиана ПО входу (dirMa)")
    _b([r for r in mm if not r["ma_al"]], "медиана против")
    _b([r for r in mm if r["wt"] < -60 and r["x_al"]], "🎯 экстремум + кросс ПО (стрелка)")
    _b([r for r in mm if r["wt"] < -60 and r["x_al"] and r["ma_al"]], "🎯🎯 стрелка + медиана ПО")
    # по годам для лучшего fib
    best = max(FIBS, key=lambda f: _st([x[2] for x in allres[f]])[2] if allres[f] else -9)
    print(f"\n── fib {best:.3f} по годам ──")
    for y in (2022, 2023, 2024, 2025, 2026):
        yr = [x[2] for x in allres[best] if x[0] == y]
        n, wr, net = _st(yr)
        if n:
            mark = "🟢" if net > 0.10 else ("🔴" if net < -0.10 else "⚪")
            print(f"   {mark} {y}: n={n:5} WR{wr:3.0f}% net={net:+.3f}%")


if __name__ == "__main__":
    main()
