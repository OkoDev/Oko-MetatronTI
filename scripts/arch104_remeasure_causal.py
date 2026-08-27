# -*- coding: utf-8 -*-
"""ПЕРЕМЕР arch104 НА ПОЧИНЕННОМ ФЛАГЕ FVG, В ДЕНЬГАХ (13.08.2026, Даат).

До 13.08 все 200 паттернов arch104 измерялись на флаге FVG, смещённом на 2 бара назад
(`swing_bridge` брал `f[0]`=ts_left вместо `f[4]`=ts_i). 179 из 200 паттернов содержат
FVG-фактор. Значит их настоящий результат не видел никто ни разу.

Здесь перемер на ПОЧИНЕННОМ флаге и в правильной метрике:
  • % net с костами 0.35% (ЗАКОН №1), не avgR;
  • WR по деньгам, а не «любой плюсовой ход»;
  • стоп на баре сигнала проверяется ПЕРВЫМ (биржа бьёт touch);
  • разрезы протокола вердикта: год · сторона · размер стопа · хрупкость · охват монет.

Дополнительно — ответ на вопрос Егора «можем ли по SMC-признакам искать входы
по экономике на 15m»: считается срез по ТФ и отдельно ячейка с экономическим
фильтром стопа (стоп кратно больше костов).

Запуск:  python scripts/arch104_remeasure_causal.py [--coins 40] [--tf 15m,1h,4h] [--enabled-only]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.calculators.combinator_core import compute_flags  # noqa: E402

DB = "ohlcv_cache.db"
COST = 0.35
BAR_H = {"5m": 1 / 12, "15m": 0.25, "1h": 1.0, "4h": 4.0, "1d": 24.0}
HTF_OF = {"15m": ["1h", "4h", "1d"], "1h": ["4h", "1d"], "4h": ["1d"]}


def agg(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()


def simulate_pct(df, tp_r: float, ttl_bars: int, sl_lookback: int = 10):
    """Возврат в % от входа. SL проверяется ПЕРВЫМ на баре (консервативно).
    Отдельно возвращается размер стопа в % — для экономических срезов."""
    n = len(df)
    H, L, C = df.high.values, df.low.values, df.close.values
    out_l = np.full(n, np.nan); sp_l = np.full(n, np.nan)
    out_s = np.full(n, np.nan); sp_s = np.full(n, np.nan)
    for i in range(sl_lookback + 2, n - 2):
        e = C[i]
        end = min(i + ttl_bars, n - 1)
        fl = L[i + 1:end + 1]; fh = H[i + 1:end + 1]
        if len(fl) == 0:
            continue
        # LONG — SL проверяется первым при равенстве баров (биржа бьёт touch)
        sl = L[i - sl_lookback:i + 1].min() * 0.999
        if sl < e:
            sp_l[i] = (e - sl) / e * 100
            tp = e + tp_r * (e - sl)
            hs = fl <= sl; ht = fh >= tp
            js = int(np.argmax(hs)) if hs.any() else 10 ** 9
            jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
            if js <= jt and js < 10 ** 9:
                out_l[i] = (sl - e) / e * 100
            elif jt < 10 ** 9:
                out_l[i] = (tp - e) / e * 100
            else:
                out_l[i] = (C[end] - e) / e * 100
        # SHORT
        sh = H[i - sl_lookback:i + 1].max() * 1.001
        if sh > e:
            sp_s[i] = (sh - e) / e * 100
            tp = e - tp_r * (sh - e)
            hs = fh >= sh; ht = fl <= tp
            js = int(np.argmax(hs)) if hs.any() else 10 ** 9
            jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
            if js <= jt and js < 10 ** 9:
                out_s[i] = (e - sh) / e * 100
            elif jt < 10 ** 9:
                out_s[i] = (e - tp) / e * 100
            else:
                out_s[i] = (e - C[end]) / e * 100
    return out_l, sp_l, out_s, sp_s


def stat(v):
    v = np.asarray(v, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return None
    neg = abs(v[v < 0].sum())
    pf = v[v > 0].sum() / neg if neg > 0 else 99.0
    s = np.sort(v)
    cut = max(1, int(len(s) * 0.10))
    return dict(n=len(v), wr=100.0 * (v > 0).mean(), pf=pf, mean=float(v.mean()),
                med=float(np.median(v)), frag=float(s[:-cut].sum()), total=float(v.sum()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=40)
    ap.add_argument("--since", type=int, default=2023)
    ap.add_argument("--tf", type=str, default="15m,1h,4h")
    ap.add_argument("--tp", type=float, default=2.0)
    ap.add_argument("--min-n", type=int, default=40)
    ap.add_argument("--enabled-only", action="store_true")
    a = ap.parse_args()

    tfs = [t.strip() for t in a.tf.split(",") if t.strip()]
    pats = yaml.safe_load(open("config/arch104_patterns.yaml", encoding="utf-8"))["patterns"]
    if a.enabled_only:
        pats = {k: v for k, v in pats.items() if v.get("enabled")}
    pats = {k: v for k, v in pats.items() if v.get("detection_tf") in tfs}

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? "
        "GROUP BY symbol HAVING n>8000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 120)
    print(f"ПЕРЕМЕР arch104 НА ПОЧИНЕННОМ FVG · {len(pats)} паттернов · ТФ {','.join(tfs)} · "
          f"{len(syms)} монет с {a.since}")
    print(f"метрика: % net (косты {COST}%) · TP={a.tp}R · SL проверяется первым · "
          f"{'только enabled' if a.enabled_only else 'все'}")
    print("═" * 120)

    # накопители: pid -> списки (net, stop_pct, year, side, symbol)
    acc = defaultdict(lambda: {"net": [], "sp": [], "yr": [], "sym": [], "tf": []})
    base_acc = defaultdict(lambda: {"net": [], "sp": []})

    for si, sym in enumerate(syms, 1):
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        raw = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                          "WHERE symbol=? AND timeframe='15m' AND time>=? ORDER BY time",
                          c, params=(sym, t0))
        c.close()
        if len(raw) < 5000:
            continue
        raw["ts"] = pd.to_datetime(raw.time, unit="ms", utc=True)
        base = raw.set_index("ts")[["open", "high", "low", "close", "volume"]]

        # считаем ТОЛЬКО нужные ТФ: запрошенные + их HTF. compute_flags на 15m-ряду
        # (десятки тысяч баров, со свингами и структурой) — самая дорогая операция,
        # и она не нужна, если 15m не запрошен.
        needed = set(tfs)
        for t in tfs:
            needed |= set(HTF_OF.get(t, []))
        all_bars = {"15m": base, "1h": ("1h",), "4h": ("4h",), "1d": ("1D",)}
        bars = {}
        for tf in needed:
            bars[tf] = base if tf == "15m" else agg(base, all_bars[tf][0])
        flags_raw = {}
        for tf, d in bars.items():
            if len(d) < 300:
                continue
            try:
                flags_raw[tf] = compute_flags(d, tf, include_pivots=(tf in ("15m", "1h")))
            except Exception:
                continue

        for tf in tfs:
            if tf not in flags_raw or tf not in bars:
                continue
            d = bars[tf]
            F = flags_raw[tf].copy()
            # HTF только с ЗАКРЫТОГО бара: индекс сдвигается на длительность бара HTF
            for h in HTF_OF.get(tf, []):
                if h not in flags_raw:
                    continue
                fh = flags_raw[h].copy()
                fh.index = fh.index + pd.Timedelta(hours=BAR_H[h])
                fh = fh.reindex(d.index, method="ffill")
                for col in fh.columns:
                    if col not in F.columns:
                        F[col] = fh[col]
            ttl = max(4, int(round(24.0 / BAR_H[tf])))       # time_exit_hours=24 у набора
            rl, spl, rs, sps = simulate_pct(d, a.tp, ttl)
            yrs = d.index.year.values
            ok_l = ~np.isnan(rl); ok_s = ~np.isnan(rs)
            base_acc[tf]["net"].extend((rl[ok_l] - COST).tolist())
            base_acc[tf]["sp"].extend(spl[ok_l].tolist())

            for pid, meta in pats.items():
                if meta.get("detection_tf") != tf:
                    continue
                facs = meta.get("anchor_factors") or []
                if not facs or any(f not in F.columns for f in facs):
                    continue
                m = np.ones(len(d), dtype=bool)
                for f in facs:
                    try:
                        m &= np.asarray(F[f].fillna(False), dtype=bool)
                    except Exception:
                        m &= np.zeros(len(d), dtype=bool)
                long_side = meta.get("direction") == "LONG"
                r, sp, ok = (rl, spl, ok_l) if long_side else (rs, sps, ok_s)
                mm = m & ok
                if not mm.any():
                    continue
                idx = np.flatnonzero(mm)
                acc[pid]["net"].extend((r[idx] - COST).tolist())
                acc[pid]["sp"].extend(sp[idx].tolist())
                acc[pid]["yr"].extend(yrs[idx].tolist())
                acc[pid]["sym"].extend([sym] * len(idx))
                acc[pid]["tf"].extend([tf] * len(idx))
        if si % 10 == 0:
            print(f"  … обработано монет: {si}/{len(syms)}")

    print(f"\n=== БАЗА (все бары, без паттернов), LONG, TP={a.tp}R ===")
    print(f"{'ТФ':<8} {'n':>9} {'WR':>7} {'PF':>7} {'%/сд net':>11} {'мед стоп':>10}")
    for tf in tfs:
        s = stat(base_acc[tf]["net"])
        if s:
            print(f"{tf:<8} {s['n']:>9} {s['wr']:>6.1f}% {s['pf']:>7.2f} {s['mean']:>+10.3f}% "
                  f"{np.nanmedian(base_acc[tf]['sp']):>9.2f}%")

    rows = []
    for pid, d_ in acc.items():
        s = stat(d_["net"])
        if s and s["n"] >= a.min_n:
            meta = pats[pid]
            rows.append((pid, meta, s, d_))
    rows.sort(key=lambda x: -x[2]["mean"])

    print(f"\n=== ПАТТЕРНЫ arch104 НА ПОЧИНЕННОМ ФЛАГЕ (n ≥ {a.min_n}) — {len(rows)} шт ===")
    print(f"{'id':<30} {'ТФ':<5} {'сторона':<7} {'ЗАЯВЛ':>13} {'n':>7} {'WR':>7} {'PF':>7} "
          f"{'%/сд net':>10} {'безтоп10%':>11}")
    print("─" * 120)
    for pid, meta, s, _ in rows[:25]:
        cl = f"R{meta.get('test_avgR', 0):.2f}/W{meta.get('test_WR', 0):.0f}"
        print(f"{pid[:28]:<30} {str(meta.get('detection_tf')):<5} "
              f"{str(meta.get('direction'))[:5]:<7} {cl:>13} {s['n']:>7} {s['wr']:>6.1f}% "
              f"{s['pf']:>7.2f} {s['mean']:>+9.3f}% {s['frag']:>+10.1f}")
    if len(rows) > 25:
        print(f"  … и ещё {len(rows) - 25}")

    pos = [r for r in rows if r[2]["mean"] > 0]
    print(f"\nплюсовых паттернов: {len(pos)} из {len(rows)}")

    if pos:
        print(f"\n=== ЛУЧШИЕ: РАЗРЕЗЫ ПРОТОКОЛА ===")
        for pid, meta, s, d_ in pos[:5]:
            net = np.array(d_["net"]); sp = np.array(d_["sp"])
            yr = np.array(d_["yr"]); sy = np.array(d_["sym"])
            print(f"\n▌ {pid}  [{meta.get('detection_tf')} {meta.get('direction')}]  "
                  f"факторы: {', '.join(meta.get('anchor_factors', []))}")
            print(f"  всего: n={s['n']} WR {s['wr']:.1f}% PF {s['pf']:.2f} {s['mean']:+.3f}%/сд "
                  f"безтоп10% {s['frag']:+.1f}")
            print(f"  по годам:", end=" ")
            for y in sorted(set(yr.tolist())):
                ss = stat(net[yr == y])
                if ss and ss["n"] >= 15:
                    print(f"{y}: {ss['mean']:+.2f}%(n={ss['n']})", end="  ")
            print()
            print(f"  по стопу:", end=" ")
            for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 100)):
                ss = stat(net[(sp > lo) & (sp <= hi)])
                if ss and ss["n"] >= 15:
                    print(f"{lo}-{hi}%: {ss['mean']:+.2f}%(n={ss['n']})", end="  ")
            print()
            per = pd.Series(net).groupby(pd.Series(sy)).mean()
            print(f"  охват монет: плюс на {int((per > 0).sum())} из {len(per)} "
                  f"({100 * (per > 0).mean():.0f}%)")

    # ── ГЕЙТ ПО РАЗМЕРУ СТОПА: единственный рычаг против костов ──
    print(f"\n=== ЭКОНОМИЧЕСКИЙ ГЕЙТ: что даёт отбор по РАЗМЕРУ СТОПА (все паттерны вместе) ===")
    print(f"косты {COST}% фиксированы, значит их ДОЛЯ в цели падает с ростом стопа")
    print(f"{'зона стопа':<16} {'n':>9} {'WR':>7} {'PF':>7} {'%/сд net':>11} "
          f"{'косты/стоп':>11} {'плюсовых паттернов':>20}")
    print("─" * 120)
    for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 8), (8, 100)):
        vals, npos, ntot = [], 0, 0
        for pid, d_ in acc.items():
            net = np.array(d_["net"]); sp = np.array(d_["sp"])
            sel = net[(sp > lo) & (sp <= hi)]
            if len(sel) == 0:
                continue
            vals.extend(sel.tolist())
            if len(sel) >= 30:
                ntot += 1
                if sel.mean() > 0:
                    npos += 1
        s = stat(vals)
        if s:
            mid = (lo + min(hi, 20)) / 2
            print(f"{f'{lo}-{hi}%':<16} {s['n']:>9} {s['wr']:>6.1f}% {s['pf']:>7.2f} "
                  f"{s['mean']:>+10.3f}% {100 * COST / max(mid, 0.01):>10.0f}% "
                  f"{f'{npos} из {ntot}':>20}")

    # то же для БАЗЫ — чтобы отличить эдж от подмены базы (закон golden_keys_matrix)
    print(f"\n  контроль — ТА ЖЕ нарезка на БАЗЕ (без паттернов), чтобы гейт не подменил базу:")
    for tf in tfs:
        bn = np.array(base_acc[tf]["net"]); bs = np.array(base_acc[tf]["sp"])
        line = f"    {tf}: "
        for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 8), (8, 100)):
            s = stat(bn[(bs > lo) & (bs <= hi)])
            if s and s["n"] >= 100:
                line += f"{lo}-{hi}%: {s['mean']:+.3f}%(PF{s['pf']:.2f})  "
        print(line)

    print("\n" + "═" * 120)
    print("Заявленные test_avgR/test_WR мерились на СМЕЩЁННОМ флаге и в R без костов —")
    print("сравнимы только знак и ранг. Здесь: % net, косты вычтены, SL первым на баре.")
    print("═" * 120)
    return 0


if __name__ == "__main__":
    sys.exit(main())
