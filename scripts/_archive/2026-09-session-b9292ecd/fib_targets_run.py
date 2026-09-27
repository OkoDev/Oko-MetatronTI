# -*- coding: utf-8 -*-
"""ЦЕЛИ ПО МИНУСОВЫМ ФИБО (метод Егора, 12.09.2026), v2 — с ВАРИАНТАМИ СТОПА.

Вход — один в один как scripts/ote_remine.py (`_nested_entry`): HTF-слом структуры задаёт
OTE-зону 0.5-0.79 отката, цена возвращается в зону, вход на LTF.
Выход — ЛЕСТНИЦА ЦЕЛЕЙ ЕГОРА: фибо-расширения за конец импульса -0.62 / -1.0 / -1.618 / -2.618
(уровни из самого сетапа `build_ote.levels`). Каждая цель = отдельная политика.

🔴 v2: ПЕРВЫЙ ПРОГОН ПОКАЗАЛ ДЕФЕКТ ИНСТРУМЕНТА — тугой LTF-SL даёт медиану 0.32% и стоп-аут 93%,
до дальних целей дойти нечем. Закон проекта: «весь эдж в РАЗМЕРЕ стопа». Поэтому меряем ДВА стопа
на одном и том же входе:
  · `ltf`  — структурный за 6 баров LTF + буфер (как в ote_remine, «тугой»);
  · `fib1` — за НАЧАЛО импульса (фибо 1.0) + буфер — это стоп метода Егора (ZEC: вход ~385, стоп 368).
Строка пишется на каждый (сетап × sl_mode), в отчёте это отдельная ось.

Причинность: SL проверяется ПЕРВЫМ в баре, цель — только если SL не задет. Всё вперёд от входа.
КОНТРОЛЬ: случайный вход по тому же символу/ТФ ±30 дней с ТОЙ ЖЕ геометрией в % (стоп и цели).
Оси: sl_mode · kind (CHoCH/BOS) · сторона · год · связка · RR · свежесть импульса.
Запуск: python fib_targets_run.py [--pairs N] [--htf 4h 1h] [--cost 0.10]
"""
from __future__ import annotations
import argparse, os, sqlite3, sys, warnings, random
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import pandas as pd

from core.smc.smc_engine import zigzag_atr, find_setups_zz

CACHE = ROOT / "ohlcv_cache.db"
NEST = {"4h": ["1h", "15m"], "1h": ["15m", "5m"]}
TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
BUF = 0.0015
SL_LOOKBACK = 6
ZONE_ACTIVE_HTF = 14
FWD_BARS = 480
TARGETS = [-0.62, -1.0, -1.618, -2.618]
MIN_N = 40
rng = random.Random(20260912)


def _load(conn, sym, tf):
    df = pd.read_sql_query(
        "SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
        conn, params=(sym, tf))
    if df.empty:
        return None
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df


def _nested_entry(dfl, direction, lo, hi, act_ts, end_ts):
    """КОПИЯ ote_remine._nested_entry. → (entry, sl_ltf, entry_ts) | None."""
    win = dfl.loc[(dfl.index >= act_ts) & (dfl.index <= end_ts)]
    if len(win) < SL_LOOKBACK + 2:
        return None
    for i in range(SL_LOOKBACK, len(win)):
        bar = win.iloc[i]
        if not (bar["low"] <= hi and bar["high"] >= lo):
            continue
        seg = win.iloc[i - SL_LOOKBACK:i + 1]
        if direction == "long":
            entry = min(float(bar["close"]), hi)
            sl = float(seg["low"].min()) * (1 - BUF)
            if entry <= sl:
                continue
            return entry, sl, win.index[i]
        entry = max(float(bar["close"]), lo)
        sl = float(seg["high"].max()) * (1 + BUF)
        if sl <= entry:
            continue
        return entry, sl, win.index[i]
    return None


def _walk(dfl, direction, entry, sl, tgt_px, entry_ts):
    """Для КАЖДОЙ цели: дошли ли раньше стопа. SL первым в баре. Не дошли → стоп или хвост окна."""
    fwd = dfl.loc[dfl.index > entry_ts].head(FWD_BARS)
    if fwd.empty:
        return None
    highs, lows, closes = fwd["high"].values, fwd["low"].values, fwd["close"].values
    is_long = direction == "long"
    sgn = 1 if is_long else -1
    res, hit = {}, {}
    pending = set(tgt_px)
    stop_i = None
    for i in range(len(fwd)):
        if (is_long and lows[i] <= sl) or (not is_long and highs[i] >= sl):
            stop_i = i
            break
        for f in list(pending):
            px = tgt_px[f]
            if (highs[i] >= px) if is_long else (lows[i] <= px):
                res[f] = (px - entry) / entry * 100 * sgn
                hit[f] = i
                pending.discard(f)
        if not pending:
            break
    sl_pnl = (sl - entry) / entry * 100 * sgn
    tail_px = closes[stop_i] if stop_i is not None else closes[-1]
    tail_pnl = (tail_px - entry) / entry * 100 * sgn
    for f in tgt_px:
        if f not in res:
            res[f] = sl_pnl if stop_i is not None else tail_pnl
    return {"pnl": res, "hit": {f: (f in hit) for f in tgt_px}, "stopped": stop_i is not None}


def _control(dfl, direction, sig_ts, sl_pct, tgt_pct):
    """Случайный вход той же геометрии: тот же символ/ТФ, случайный бар ±30 дней, те же % стопа/целей."""
    pool = dfl.loc[(dfl.index >= sig_ts - pd.Timedelta(days=30)) & (dfl.index <= sig_ts + pd.Timedelta(days=30))]
    if len(pool) < 60:
        return None
    j = rng.randrange(0, len(pool) - 10)
    ets, entry = pool.index[j], float(pool.iloc[j]["close"])
    is_long = direction == "long"
    sl = entry * (1 - sl_pct / 100) if is_long else entry * (1 + sl_pct / 100)
    tgt_px = {f: (entry * (1 + p / 100) if is_long else entry * (1 - p / 100)) for f, p in tgt_pct.items()}
    return _walk(dfl, direction, entry, sl, tgt_px, ets)


def run_symbol(conn, sym, htfs):
    rows, dfs = [], {}
    for tf in ("4h", "1h", "15m", "5m"):
        d = _load(conn, sym, tf)
        if d is not None and len(d) > 300:
            dfs[tf] = d
    for htf in htfs:
        dfh = dfs.get(htf)
        if dfh is None:
            continue
        try:
            setups = find_setups_zz(zigzag_atr(dfh), dfh)
        except Exception:
            continue
        span = pd.Timedelta(minutes=TF_MIN[htf] * ZONE_ACTIVE_HTF)
        for s in setups:
            direction, ote, levels = s.get("direction"), s.get("ote"), (s.get("levels") or {})
            act = s.get("choch_ts")
            if not ote or direction not in ("long", "short") or act is None or 1.0 not in levels:
                continue
            act_ts = pd.Timestamp(act)
            if act_ts.tzinfo is None:
                act_ts = act_ts.tz_localize("UTC")
            lo, hi = float(ote[0]), float(ote[1])
            tgt_px = {f: float(levels[f]) for f in TARGETS if f in levels}
            if len(tgt_px) < len(TARGETS):
                continue
            imp_end = s.get("to", (None, None))[0]
            for ltf in NEST[htf]:
                dfl = dfs.get(ltf)
                if dfl is None:
                    continue
                ent = _nested_entry(dfl, direction, lo, hi, act_ts, act_ts + span)
                if not ent:
                    continue
                entry, sl_ltf, ets = ent
                # СТОП ЕГОРА: за начало импульса (фибо 1.0) + буфер
                lvl1 = float(levels[1.0])
                sl_fib1 = lvl1 * (1 - BUF) if direction == "long" else lvl1 * (1 + BUF)
                fresh_h = None
                if imp_end is not None:
                    t_end = pd.Timestamp(imp_end)
                    if t_end.tzinfo is None:
                        t_end = t_end.tz_localize("UTC")
                    fresh_h = (ets - t_end).total_seconds() / 3600
                for mode, slv in (("ltf", sl_ltf), ("fib1", sl_fib1)):
                    if (direction == "long" and slv >= entry) or (direction == "short" and slv <= entry):
                        continue
                    w = _walk(dfl, direction, entry, slv, tgt_px, ets)
                    if not w:
                        continue
                    sl_pct = abs(entry - slv) / entry * 100
                    tgt_pct = {f: abs(tgt_px[f] - entry) / entry * 100 for f in tgt_px}
                    ctrl = _control(dfl, direction, ets, sl_pct, tgt_pct)
                    row = {"sym": sym, "setup": f"{htf}->{ltf}", "dir": direction, "sl_mode": mode,
                           "kind": s.get("kind"), "ts": ets, "year": ets.year, "sl_pct": sl_pct,
                           "fresh_h": fresh_h, "stopped": w["stopped"]}
                    for f in TARGETS:
                        row[f"hit{f}"] = w["hit"][f]
                        row[f"pnl{f}"] = w["pnl"][f]
                        row[f"rr{f}"] = tgt_pct[f] / sl_pct if sl_pct > 0 else np.nan
                        row[f"ctl{f}"] = ctrl["pnl"][f] if ctrl else np.nan
                        row[f"ctlhit{f}"] = ctrl["hit"][f] if ctrl else np.nan
                    rows.append(row)
    return rows


def report(df, cost):
    def block(title, g):
        if len(g) < MIN_N:
            return
        out = []
        for f in TARGETS:
            pnl, ctl = g[f"pnl{f}"] - cost, g[f"ctl{f}"] - cost
            keep = pnl.sort_values(ascending=False).iloc[int(len(g) * 0.1):]
            out.append({"цель": f, "RR": g[f"rr{f}"].median(), "дошли%": g[f"hit{f}"].mean() * 100,
                        "на сделку%": pnl.mean(), "WR%": (pnl > 0).mean() * 100,
                        "контроль%": ctl.mean(), "над контр": pnl.mean() - ctl.mean(),
                        "к.дошли%": g[f"ctlhit{f}"].mean() * 100,
                        "безтоп10": keep.sum(), "сумма": pnl.sum()})
        print(f"\n=== {title}  (n={len(g)}, монет={g.sym.nunique()}, стоп мед {g.sl_pct.median():.2f}%, "
              f"стоп-аут {g.stopped.mean()*100:.0f}%)")
        print(pd.DataFrame(out).to_string(index=False, float_format=lambda x: f"{x:8.3f}"))

    for mode, gm in df.groupby("sl_mode"):
        block(f"СТОП = {mode}" + ("  (тугой LTF, как ote_remine)" if mode == "ltf"
                                  else "  (за начало импульса — метод Егора)"), gm)
        for k, g in gm.groupby("kind"):
            block(f"[{mode}] kind={k}  (CHoCH=слом → волна 3 · BOS=продолжение → риск волны 5)", g)
        for k, g in gm.groupby("dir"):
            block(f"[{mode}] сторона={k}", g)
        for k, g in gm.groupby("setup"):
            block(f"[{mode}] связка {k}", g)
        for k, g in gm.groupby("year"):
            block(f"[{mode}] год {k}", g)
        if gm.fresh_h.notna().any():
            fq = pd.cut(gm.fresh_h, [-1e9, 24, 72, 1e9], labels=["≤24ч", "24-72ч", ">72ч"])
            for k, g in gm.groupby(fq):
                block(f"[{mode}] свежесть импульса {k}", g)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=60)
    ap.add_argument("--htf", nargs="+", default=["4h", "1h"])
    ap.add_argument("--cost", type=float, default=0.10)
    ap.add_argument("--out", default="fib_targets_rows.pkl")
    a = ap.parse_args()

    conn = sqlite3.connect(str(CACHE))
    syms = [r[0] for r in conn.execute(
        "SELECT symbol FROM ohlcv_cache WHERE timeframe='1h' GROUP BY symbol HAVING COUNT(*)>5000 "
        "ORDER BY COUNT(*) DESC")][:a.pairs]
    print(f"символов: {len(syms)} · HTF: {a.htf} · цели: {TARGETS} · кост {a.cost}% круг", flush=True)
    allrows = []
    for i, s in enumerate(syms, 1):
        try:
            allrows += run_symbol(conn, s, a.htf)
        except Exception as e:
            print(f"  [skip] {s}: {e}", flush=True)
        if i % 10 == 0:
            print(f"  {i}/{len(syms)} · строк {len(allrows)}", flush=True)
    if not allrows:
        print("НЕТ СДЕЛОК"); return
    df = pd.DataFrame(allrows)
    df.to_pickle(Path(__file__).parent / a.out)
    print(f"\nсделок: {len(df)} · монет: {df.sym.nunique()} · окно: {df.ts.min():%Y-%m-%d} → {df.ts.max():%Y-%m-%d}")
    report(df, a.cost)


if __name__ == "__main__":
    main()
