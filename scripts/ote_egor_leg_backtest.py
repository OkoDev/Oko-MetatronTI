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


def _floor_pivots(H, L, C):
    """ТОЧНАЯ формула OKO-SM f_getPivotTraditional (S1/R1 с 2.003/1.997 — сдвиг за свип!),
    уровни PP + S1-S3 + R1-R3 (дефолт индикатора показывает 3)."""
    pp = (H + L + C) / 3
    return [pp,
            pp * 2.003 - H, pp - (H - L), pp * 2 - (2 * H - L),      # S1..S3
            pp * 1.997 - L, pp + (H - L), pp * 2 + (H - 2 * L)]      # R1..R3


def _period_pivots(df, rule):
    """Каузальные floor-пивоты периода (D/W/M): уровни ИЗ ПРОШЛОГО периода действуют в текущем.
    → список массивов уровней на каждый бар (индекс df)."""
    ts = pd.to_datetime(df["time"], unit="ms", utc=True)
    if rule == "D":
        key = ts.dt.strftime("%Y-%m-%d")
    elif rule == "W":
        key = ts.dt.strftime("%G-%V")
    else:
        key = ts.dt.strftime("%Y-%m")
    lv_by_key = {}
    agg = {}
    for i in range(len(df)):
        k = key.iloc[i]
        a = agg.setdefault(k, [df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]])
        a[0] = max(a[0], df["high"].iloc[i]); a[1] = min(a[1], df["low"].iloc[i]); a[2] = df["close"].iloc[i]
    keys = list(agg.keys())
    prev_of = {keys[j]: keys[j-1] for j in range(1, len(keys))}
    out = []
    for i in range(len(df)):
        pk = prev_of.get(key.iloc[i])
        if pk is None:
            out.append(())
        else:
            if pk not in lv_by_key:
                H, L, C = agg[pk]
                lv_by_key[pk] = tuple(_floor_pivots(H, L, C))
            out.append(lv_by_key[pk])
    return out


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
    # КОНВЕРГЕНЦИЯ (вопрос Егора «моменты сходящиеся в единой точке»): каузальные уровни
    pivD = _period_pivots(df, "D"); pivW = _period_pivots(df, "W"); pivM = _period_pivots(df, "M")
    # FVG-края (3-бар гэпы, последние 24) и структурные полки (len5-свинги, последние 24)
    from core.smc.oko_sm_engine import _swings as _sw5
    shelf_by_conf = {}
    for conf_i, sw_i, price, is_top in _sw5(df["high"], df["low"], 5):
        shelf_by_conf.setdefault(conf_i, []).append(price)
    fvg_edges = []          # (появился_на_баре, уровень)
    shelves = []
    hvv, lvv = df["high"].values, df["low"].values
    fvg_at = [[] for _ in range(n)]
    sh_at = [[] for _ in range(n)]
    for t in range(n):
        if t >= 2:
            if lvv[t] > hvv[t-2]:
                fvg_edges.append(hvv[t-2]); fvg_edges.append(lvv[t])
            elif hvv[t] < lvv[t-2]:
                fvg_edges.append(lvv[t-2]); fvg_edges.append(hvv[t])
            fvg_edges = fvg_edges[-24:]
        shelves.extend(shelf_by_conf.get(t, ())); shelves = shelves[-24:]
        fvg_at[t] = list(fvg_edges); sh_at[t] = list(shelves)
    # Дивергенции OkoTrend (порт): фракталы wt1, regBull=LL цены+HL WT, regBear=HH цены+LH WT
    divB = [False]*n; divS = [False]*n
    _pb = None; _pt = None   # (wt_prev, price_prev) последнего bot/top фрактала
    for t in range(4, n):
        w4,w3,w2,w1_,w0 = wt1v[t-4],wt1v[t-3],wt1v[t-2],wt1v[t-1],wt1v[t]
        if w4<w2 and w3<w2 and w2>w1_ and w2>w0:      # top fractal @ t-2
            if _pt is not None and hvv[t-2] > _pt[1] and w2 < _pt[0]:
                divS[t] = True
            _pt = (w2, hvv[t-2])
        if w4>w2 and w3>w2 and w2<w1_ and w2<w0:      # bot fractal @ t-2
            if _pb is not None and lvv[t-2] < _pb[1] and w2 > _pb[0]:
                divB[t] = True
            _pb = (w2, lvv[t-2])
    DIVWIN = 10
    divB_rec = [any(divB[max(0,i-DIVWIN):i+1]) for i in range(n)]
    divS_rec = [any(divS[max(0,i-DIVWIN):i+1]) for i in range(n)]
    TOL = 0.003
    def _cluster(price, t, prevleg):
        cnt = 0
        for grp in (pivD[t-1], pivW[t-1], pivM[t-1]):
            if any(abs(price-x)/price <= TOL for x in grp): cnt += 1; break
        if any(abs(price-x)/price <= TOL for x in fvg_at[t-1]): cnt += 1
        if any(abs(price-x)/price <= TOL for x in sh_at[t-1]): cnt += 1
        if prevleg is not None:
            po, pe = prevleg["origin"], prevleg["extreme"]
            for f2 in (0.0,0.382,0.5,0.618,0.705,0.786,1.0,-0.27,-0.62):
                lvl = pe - f2*(pe-po)
                if lvl > 0 and abs(price-lvl)/price <= TOL: cnt += 1; break
        return cnt
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
                       "ma_up": mav[t-1] > mav[t-2] if t >= 2 else False,
                       "clu": _cluster(entry, t, prev_leg),
                       "divB": divB_rec[t-1], "divS": divS_rec[t-1],
                       "ws2": (len(pivW[t-1]) > 5 and abs(entry - pivW[t-1][2]) / entry <= TOL),
                       "wr2": (len(pivW[t-1]) > 5 and abs(entry - pivW[t-1][5]) / entry <= TOL)}
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
                       "ma_up": mav[t-1] > mav[t-2] if t >= 2 else False,
                       "clu": _cluster(entry, t, prev_leg),
                       "divB": divB_rec[t-1], "divS": divS_rec[t-1],
                       "ws2": (len(pivW[t-1]) > 5 and abs(entry - pivW[t-1][2]) / entry <= TOL),
                       "wr2": (len(pivW[t-1]) > 5 and abs(entry - pivW[t-1][5]) / entry <= TOL)}
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
                "vs_ma": sgn * w["vs_ma"], "ma_al": (w["ma_up"] if x[1]=="LONG" else not w["ma_up"]),
                "clu": w.get("clu", 0),
                "div_al": (w.get("divB") if x[1]=="LONG" else w.get("divS")),
                "wpiv": (w.get("ws2") if x[1]=="LONG" else w.get("wr2")), "net": x[2]}
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
    print("   ── КЛАСТЕР схождения на цене входа (пивоты D/W/M + FVG + полки + сетка соседа, ±0.3%) ──")
    for cl_lo, cl_hi, lbl in ((0,0,"кластер 0 (голый fib)"),(1,1,"кластер 1"),(2,2,"кластер 2"),(3,9,"кластер 3+")):
        _b([r for r in mm if cl_lo <= r.get("clu",0) <= cl_hi], f"{lbl}")
    _b([r for r in mm if r.get("clu",0) >= 2 and r["wt"] < -30], "🎯 кластер≥2 + WT<-30")
    _b([r for r in mm if r.get("clu",0) >= 3 and r["wt"] < -30], "🎯🎯 кластер≥3 + WT<-30")
    _b([r for r in mm if r.get("div_al")], "ДИВЕРГЕНЦИЯ ПО входу (свежая ≤10 бар)")
    _b([r for r in mm if not r.get("div_al")], "без дивергенции")
    _b([r for r in mm if r.get("div_al") and r["wt"] < -30], "🎯 див + WT<-30")
    _b([r for r in mm if r.get("div_al") and r.get("clu",0) >= 1], "🎯 див + кластер≥1")
    _b([r for r in mm if r.get("div_al") and r.get("clu",0) >= 2], "🎯🎯 див + кластер≥2")
    _b([r for r in mm if r.get("div_al") and r["wt"] < -30 and r.get("clu",0) >= 1], "🎯🎯🎯 див+WT<-30+кластер≥1 (ЕДИНАЯ ТОЧКА)")
    _b([r for r in mm if r.get("wpiv")], "⭐ вход ∩ недельный S2/R2 (магнит 62-69%)")
    _b([r for r in mm if r.get("wpiv") and r["wt"] < -30], "⭐🎯 W-S2/R2 + WT<-30")
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
