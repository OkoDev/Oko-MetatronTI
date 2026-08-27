# -*- coding: utf-8 -*-
"""RR FORWARD OOS: предсказывает ли RR(t) сторону фейда в СЛЕДУЮЩЕМ окне? (13.08.2026, Даат).

Зачем ещё один тест, когда DS уже проверил RR на всех ТФ:
  1. У DS окно `SINCE_Y=2024` → нейтраль + два медведя. Бычий 2023 (медиана монеты
     +57.7%, 76% растущих, 147 монет на 4h) ЛЕЖИТ В КЭШЕ и не использован.
     Запрет research-verdict п.1.2 — «t0 копировался вслепую и спрятал бычий год».
     Без бычьего контроля «переворот 2025-08» неотличим от входа в медвежий режим.
  2. Все прошлые замеры IN-SAMPLE: RR агрегируется по окну, и сторона-лидер берётся
     из ТОГО ЖЕ окна. Практический вопрос другой: зная RR на конец окна t,
     угадаем ли сторону в t+1? Здесь решение принимается ТОЛЬКО по прошлому.
  3. DS брал 45 монет на 4h через `ORDER BY n DESC LIMIT` — это отбор по длине истории,
     то есть выжившие. Здесь вселенная шире и фиксируется по ликвидности.

Механика фейда 1:1 с fade_rr_by_tf.py (ATRTrend↑ + WT<−60 + разворот → LONG, зеркало SHORT),
TP1R, TTL 24 бара, косты 0.35%, стоп 4–12%.

Метрика — не «угадал знак», а ДЕНЬГИ: медиана % net стратегии «сторона по RR» против
контролей «всегда LONG», «всегда SHORT», «монетка». Плюс разрезы по протоколу вердикта.

Запуск:  python scripts/fade_rr_forward_oos.py [--tf 4h] [--since 2022]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DB = "ohlcv_cache.db"
COST = 0.35
COOL = {"5m": 72, "15m": 24, "1h": 6, "4h": 2}
BARS_33D = {"5m": 9504, "15m": 3168, "1h": 792, "4h": 198}
MS_M = 30.44 * 24 * 3600 * 1000
DEAD_ZONE = 0.15          # мёртвая зона |RR| — требование роя (4/6) и DS
MIN_SIG_SIDE = 12         # минимум сигналов на сторону в окне, иначе окно не считаем


# ── механика (1:1 с fade_rr_by_tf.py) ───────────────────────────────────────────
def wt(df, n1=10, n2=21):
    hlc = (df.high + df.low + df.close) / 3
    esa = hlc.ewm(span=n1).mean()
    d = (hlc - esa).abs().ewm(span=n1).mean()
    return ((hlc - esa) / (0.015 * d.replace(0, np.nan))).ewm(span=n2).mean().fillna(0).values


def atrt(df, period=43, factor=1.25):
    h, l, c = df.high, df.low, df.close
    hl2 = ((h + l) / 2).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean().values
    up = hl2 - factor * atr
    dn = hl2 + factor * atr
    n = len(c)
    cv = c.values
    u = np.zeros(n); d_ = np.zeros(n); dirn = np.zeros(n)
    u[0], d_[0], dirn[0] = up[0], dn[0], 1
    for i in range(1, n):
        u[i] = max(up[i], u[i - 1]) if cv[i - 1] > u[i - 1] else up[i]
        d_[i] = min(dn[i], d_[i - 1]) if cv[i - 1] < d_[i - 1] else dn[i]
        dirn[i] = 1 if cv[i] > d_[i - 1] else (-1 if cv[i] < u[i - 1] else dirn[i - 1])
    return dirn


def ex_tp1r(i, H, L, C, sl, side, ttl=24):
    e = C[i]
    if side == "LONG":
        tp = e + (e - sl)
        end = min(i + ttl, len(C) - 1)
        for j in range(i + 1, end + 1):
            if L[j] <= sl:
                return (sl - e) / e * 100
            if H[j] >= tp:
                return (tp - e) / e * 100
        return (C[end] - e) / e * 100
    tp = e - (sl - e)
    end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if H[j] >= sl:
            return (e - sl) / e * 100
        if L[j] <= tp:
            return (e - tp) / e * 100
    return (e - C[end]) / e * 100


def rr_feat(r, i, lb):
    """RR по ПРОШЛЫМ барам [i-lb, i) — причинно, будущее не используется."""
    w = r[i - lb:i]
    w = w[np.isfinite(w)]
    if len(w) < lb * 0.8:
        return np.nan
    sd = w.std()
    if sd <= 0:
        return np.nan
    shock = np.where(np.abs(w) > 2 * sd)[0]
    shock = shock[shock < len(w) - 12]
    if len(shock) < 5:
        return np.nan
    return float(np.median([w[k + 1:k + 13].sum() for k in shock]) / sd)


# ── сбор сигналов ───────────────────────────────────────────────────────────────
def collect(tf: str, since_y: int, max_coins: int):
    t0 = int(dt.datetime(since_y, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    lb = BARS_33D[tf]
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? AND time>=? "
        "GROUP BY symbol HAVING n>? ORDER BY n DESC LIMIT ?",
        (tf, t0, lb * 2, max_coins)).fetchall()]
    con.close()

    DATA, turn = {}, {}
    for s in syms:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        d = pd.read_sql("SELECT time,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                        "AND timeframe=? AND time>=? ORDER BY time", c, params=(s, tf, t0))
        c.close()
        if len(d) >= lb * 2:
            DATA[s] = d
            turn[s] = float(np.nanmedian((d.close * d.volume).values))
    if not DATA:
        return [], 0, 0
    mt = np.nanmedian(list(turn.values()))
    liq_set = {s for s in DATA if turn[s] >= mt}

    sig = []  # (ts, side, net, rr, stop_pct, liquid, symbol)
    for s, d in DATA.items():
        w_ = wt(d); tr_ = atrt(d)
        H, L, C, T = d.high.values, d.low.values, d.close.values, d.time.values
        r = np.concatenate([[np.nan], np.diff(C) / C[:-1] * 100])
        last = {"LONG": -10 ** 9, "SHORT": -10 ** 9}
        for i in range(max(lb + 5, 210), len(d) - 1):
            for side in ("LONG", "SHORT"):
                if i - last[side] < COOL[tf]:
                    continue
                if side == "LONG":
                    if not (tr_[i] > 0 and w_[i] < -60 and w_[i] > w_[i - 1]):
                        continue
                    sl = L[max(0, i - 3):i + 1].min() * 0.997
                    if sl >= C[i]:
                        continue
                    sp = (C[i] - sl) / C[i] * 100
                else:
                    if not (tr_[i] < 0 and w_[i] > 60 and w_[i] < w_[i - 1]):
                        continue
                    sl = H[max(0, i - 3):i + 1].max() * 1.003
                    if sl <= C[i]:
                        continue
                    sp = (sl - C[i]) / C[i] * 100
                if not (4.0 < sp <= 12.0):
                    continue
                last[side] = i
                sig.append((int(T[i]), side, ex_tp1r(i, H, L, C, sl, side) - COST,
                            rr_feat(r, i, lb), float(sp), s in liq_set, s))
    sig.sort()
    return sig, len(DATA), len(liq_set)


def year_regime(y: int) -> str:
    """Режим года посчитан отдельно (медиана монеты на 4h): печатается в шапке."""
    return {2022: "медведь", 2023: "БЫК", 2024: "нейтраль",
            2025: "медведь", 2026: "медведь"}.get(y, "?")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="4h")
    ap.add_argument("--since", type=int, default=2022)
    ap.add_argument("--coins", type=int, default=140)
    ap.add_argument("--win", type=float, default=3.0, help="длина окна, мес")
    ap.add_argument("--step", type=float, default=1.0)
    a = ap.parse_args()

    print("═" * 112)
    print(f"RR FORWARD OOS · {a.tf} · окно с {a.since} (включая БЫЧИЙ 2023) · "
          f"роллинг {a.win}м/шаг {a.step}м · мёртвая зона |RR|≥{DEAD_ZONE}")
    print("решение по RR окна t → результат меряется в окне t+1 (будущее в решении НЕ участвует)")
    print("═" * 112)

    sig, n_all, n_liq = collect(a.tf, a.since, a.coins)
    if len(sig) < 100:
        print(f"сигналов {len(sig)} — мало")
        return 1
    # Дамп сигналов: пересчёт занимает минуты, а разрезов впереди много (гипотезы DS).
    dump = f"scripts/_fade_signals_{a.tf}_{a.since}.csv"
    pd.DataFrame(sig, columns=["ts", "side", "net", "rr", "stop_pct", "liquid", "symbol"]).to_csv(
        dump, index=False)
    print(f"[dump] сигналы сохранены → {dump}")
    n_long = sum(1 for x in sig if x[1] == "LONG")
    print(f"\nсигналов {len(sig)} (LONG {n_long} · SHORT {len(sig) - n_long}) · "
          f"монет всего {n_all}, ликвидных {n_liq}")
    yrs = sorted({dt.datetime.fromtimestamp(x[0] / 1000, dt.timezone.utc).year for x in sig})
    print("годы в выборке: " + " · ".join(f"{y}({year_regime(y)})" for y in yrs))

    # ── окна ────────────────────────────────────────────────────────────────────
    rows = []          # (метка, rr_окна, med_long, med_short, сигналы окна)
    cur, t_max = sig[0][0], sig[-1][0]
    while cur + a.win * MS_M <= t_max:
        lo, hi = cur, cur + a.win * MS_M
        win = [x for x in sig if lo <= x[0] < hi]
        L_ = [x[2] for x in win if x[1] == "LONG"]
        S_ = [x[2] for x in win if x[1] == "SHORT"]
        if len(L_) >= MIN_SIG_SIDE and len(S_) >= MIN_SIG_SIDE:
            rr = float(np.nanmedian([x[3] for x in win if np.isfinite(x[3])]))
            rows.append((dt.datetime.fromtimestamp(lo / 1000, dt.timezone.utc).strftime("%Y-%m"),
                         rr, float(np.median(L_)), float(np.median(S_)), win))
        cur += a.step * MS_M

    if len(rows) < 6:
        print(f"окон {len(rows)} — мало для forward")
        return 1

    # ── FORWARD: решение по RR окна t, результат в окне t+1 ─────────────────────
    print(f"\n{'окно t':<9} {'RR(t)':>7} {'решение':>8} │ {'окно t+1':<9} "
          f"{'LONG':>8} {'SHORT':>8} {'взято':>8} {'идеал':>8}  вердикт")
    print("─" * 112)
    took, ideal, always_L, always_S, hits, skipped = [], [], [], [], [], 0
    for k in range(len(rows) - 1):
        lbl, rr, _, _, _ = rows[k]
        nlbl, _, mL, mS, _ = rows[k + 1]
        if not np.isfinite(rr):
            continue
        if abs(rr) < DEAD_ZONE:
            skipped += 1
            print(f"{lbl:<9} {rr:+7.3f} {'—мёртв':>8} │ {nlbl:<9} {mL:+8.2f} {mS:+8.2f} "
                  f"{'пропуск':>8} {max(mL, mS):+8.2f}")
            continue
        dec = "LONG" if rr > 0 else "SHORT"
        got = mL if dec == "LONG" else mS
        best = max(mL, mS)
        ok = (dec == "LONG" and mL >= mS) or (dec == "SHORT" and mS > mL)
        hits.append(ok)
        took.append(got); ideal.append(best); always_L.append(mL); always_S.append(mS)
        print(f"{lbl:<9} {rr:+7.3f} {dec:>8} │ {nlbl:<9} {mL:+8.2f} {mS:+8.2f} "
              f"{got:+8.2f} {best:+8.2f}  {'✅' if ok else '❌'}")

    if not took:
        print("\nвсе окна в мёртвой зоне — решений нет")
        return 1

    acc = 100 * np.mean(hits)
    print("\n" + "═" * 112)
    print("ИТОГ FORWARD (медиана % net по окнам)")
    print("─" * 112)
    print(f"  решений {len(took)} (пропущено мёртвой зоной {skipped}) · попаданий {acc:.0f}%")
    print(f"  RR-стратегия  : {np.median(took):+7.3f}%   сумма {np.sum(took):+8.2f}")
    print(f"  всегда LONG   : {np.median(always_L):+7.3f}%   сумма {np.sum(always_L):+8.2f}")
    print(f"  всегда SHORT  : {np.median(always_S):+7.3f}%   сумма {np.sum(always_S):+8.2f}")
    print(f"  идеал (оракул): {np.median(ideal):+7.3f}%   сумма {np.sum(ideal):+8.2f}")
    edge_vs_best_ctrl = np.median(took) - max(np.median(always_L), np.median(always_S))
    print(f"  ➜ преимущество над ЛУЧШИМ контролем: {edge_vs_best_ctrl:+.3f} п.п.")

    # хрупкость: сумма без верхних 10% решений
    srt = np.sort(took)
    cut = max(1, int(len(srt) * 0.10))
    print(f"  хрупкость (сумма без топ-10% окон): {np.sum(srt[:-cut]):+8.2f}")

    # ── РАЗРЕЗЫ по протоколу ────────────────────────────────────────────────────
    print("\n" + "═" * 112)
    print("РАЗРЕЗЫ (протокол вердикта)")
    print("─" * 112)

    # по году+режиму
    print(f"{'год (режим)':<20} {'решений':>8} {'попад.':>8} {'RR-стратегия':>14} {'лучший контроль':>17}")
    by_year = {}
    for k in range(len(rows) - 1):
        lbl, rr, _, _, _ = rows[k]
        nlbl, _, mL, mS, _ = rows[k + 1]
        if not np.isfinite(rr) or abs(rr) < DEAD_ZONE:
            continue
        y = int(nlbl[:4])
        dec = "LONG" if rr > 0 else "SHORT"
        got = mL if dec == "LONG" else mS
        ok = (dec == "LONG" and mL >= mS) or (dec == "SHORT" and mS > mL)
        by_year.setdefault(y, []).append((got, ok, mL, mS))
    for y in sorted(by_year):
        v = by_year[y]
        g = [x[0] for x in v]
        ctrl = max(np.median([x[2] for x in v]), np.median([x[3] for x in v]))
        print(f"{str(y) + ' (' + year_regime(y) + ')':<20} {len(v):>8} "
              f"{100 * np.mean([x[1] for x in v]):>7.0f}% {np.median(g):>+13.3f}% {ctrl:>+16.3f}%")

    # сторона решения
    print(f"\n{'решение':<20} {'окон':>8} {'попад.':>8} {'медиана':>14}")
    for dside in ("LONG", "SHORT"):
        v = []
        for k in range(len(rows) - 1):
            lbl, rr, _, _, _ = rows[k]
            _, _, mL, mS, _ = rows[k + 1]
            if not np.isfinite(rr) or abs(rr) < DEAD_ZONE:
                continue
            if ("LONG" if rr > 0 else "SHORT") != dside:
                continue
            got = mL if dside == "LONG" else mS
            ok = (dside == "LONG" and mL >= mS) or (dside == "SHORT" and mS > mL)
            v.append((got, ok))
        if v:
            print(f"{dside:<20} {len(v):>8} {100 * np.mean([x[1] for x in v]):>7.0f}% "
                  f"{np.median([x[0] for x in v]):>+13.3f}%")

    # размер стопа и ликвидность — на уровне сигналов следующего окна
    print(f"\n{'разрез сигналов':<24} {'n':>7} {'медиана net':>14}")
    allsig = [x for _, _, _, _, w in rows for x in w]
    for name, pred in (
        ("стоп 4-6%", lambda x: 4 < x[4] <= 6),
        ("стоп 6-8%", lambda x: 6 < x[4] <= 8),
        ("стоп 8-12%", lambda x: 8 < x[4] <= 12),
        ("ликвидные", lambda x: x[5]),
        ("неликвидные", lambda x: not x[5]),
    ):
        v = [x[2] for x in allsig if pred(x)]
        if v:
            print(f"{name:<24} {len(v):>7} {np.median(v):>+13.3f}%")

    cov = len({x[6] for x in allsig})
    print(f"\nохват монет: {cov} · всего сигналов в окнах: {len(allsig)}")
    print("═" * 112)
    return 0


if __name__ == "__main__":
    sys.exit(main())
