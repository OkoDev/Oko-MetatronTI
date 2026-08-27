# -*- coding: utf-8 -*-
"""MTF: СЕТАП НА СТАРШЕМ ТФ, ВХОД НА МЛАДШЕМ — проверка изначальной концепции проекта.
(13.08.2026, Даат)

Егор: «сетапы, которые мы должны находить и торговать, находятся на часовиках и 4h.
Но ВХОДЫ мы ищем на младших ТФ — 15m, 5m. Отсюда частота и отличные точки входа.
15m-торговля запущена только чтобы быстро собрать данные симуляции».

Весь замер 13.08 был ОДНОТФ-ным (сетап и вход на одном ТФ) — то есть проверял НЕ ту
архитектуру, которая заложена в проект. Здесь проверяется настоящая:

    СЕТАП (HTF):  ATRTrend↑ + WT<−60 + разворот WT   ← качество, редко
    ВХОД  (LTF):  внутри окна сетапа ждём разворота WT на младшем ТФ  ← точность, часто
    СТОП:         по структуре ЛТФ (3 бара) → он МЕНЬШЕ, чем стоп HTF
    ЦЕЛЬ:         в R от своего (меньшего) стопа

Гипотеза: тот же сетап + более точный вход = меньший стоп при том же движении =
лучше RR и выше % net. Если она верна — это и есть недостающий рычаг проекта.

Контроль: тот же сетап со входом и стопом на HTF (как мерили весь день).

Запуск:  python scripts/mtf_setup_htf_entry_ltf.py [--htf 4h --ltf 15m]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DB = "ohlcv_cache.db"
COST = 0.35
ENTRY_MODE, LIMIT_PCT = "wt", 1.0
Cl_entry_override = None
BARS_PER = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


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
    up, dn = hl2 - factor * atr, hl2 + factor * atr
    n, cv = len(c), c.values
    u = np.zeros(n); d_ = np.zeros(n); dirn = np.zeros(n)
    u[0], d_[0], dirn[0] = up[0], dn[0], 1
    for i in range(1, n):
        u[i] = max(up[i], u[i - 1]) if cv[i - 1] > u[i - 1] else up[i]
        d_[i] = min(dn[i], d_[i - 1]) if cv[i - 1] < d_[i - 1] else dn[i]
        dirn[i] = 1 if cv[i] > d_[i - 1] else (-1 if cv[i] < u[i - 1] else dirn[i - 1])
    return dirn


def exit_tp(i, H, L, C, sl, tp_r, ttl, entry_px=None):
    e = entry_px if entry_px is not None else C[i]
    tp = e + tp_r * (e - sl)
    end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if L[j] <= sl:
            return (sl - e) / e * 100
        if H[j] >= tp:
            return (tp - e) / e * 100
    return (C[end] - e) / e * 100


def load(sym, tf, t0):
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    d = pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? "
                    "AND timeframe=? AND time>=? ORDER BY time", c, params=(sym, tf, t0))
    c.close()
    return d


def stat(v):
    v = np.asarray(v)
    if len(v) == 0:
        return None
    pf = v[v > 0].sum() / abs(v[v < 0].sum()) if (v < 0).any() else 99.0
    return len(v), float(np.median(v)), 100.0 * float((v > 0).mean()), float(pf), float(v.mean())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--htf", default="4h")
    ap.add_argument("--ltf", default="15m")
    ap.add_argument("--coins", type=int, default=50)
    ap.add_argument("--since", type=int, default=2024)
    ap.add_argument("--window-bars", type=int, default=6, help="сколько HTF-баров ждём вход на LTF")
    ap.add_argument("--entry", default="wt", choices=["wt", "limit"], help="способ входа на LTF")
    ap.add_argument("--limit-pct", type=float, default=1.0, help="насколько ниже close HTF ставим лимит")
    a = ap.parse_args()

    global ENTRY_MODE, LIMIT_PCT
    ENTRY_MODE, LIMIT_PCT = a.entry, a.limit_pct
    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? AND time>=? "
        "GROUP BY symbol HAVING n>500 ORDER BY n DESC LIMIT ?", (a.htf, t0, a.coins)).fetchall()]
    con.close()

    print("═" * 100)
    print(f"MTF: СЕТАП {a.htf} → ВХОД {a.ltf} · окно ожидания {a.window_bars} баров {a.htf}")
    print(f"контроль: тот же сетап, вход и стоп на {a.htf} (как мерили весь день)")
    print("═" * 100)

    htf_res, ltf_res = {tp: [] for tp in (1.0, 2.0, 3.0)}, {tp: [] for tp in (1.0, 2.0, 3.0)}
    htf_stops, ltf_stops = [], []
    pairs = 0

    for sym in syms:
        H4 = load(sym, a.htf, t0)
        L15 = load(sym, a.ltf, t0)
        if len(H4) < 300 or len(L15) < 1000:
            continue
        pairs += 1
        w4, tr4 = wt(H4), atrt(H4)
        Hh, Lh, Ch, Th = H4.high.values, H4.low.values, H4.close.values, H4.time.values
        Hl, Ll, Cl, Tl = L15.high.values, L15.low.values, L15.close.values, L15.time.values
        wl = wt(L15)
        last = -10 ** 9
        cool = 2
        for i in range(210, len(H4) - 1):
            if i - last < cool:
                continue
            # ── СЕТАП на HTF ──
            if not (tr4[i] > 0 and w4[i] < -60 and w4[i] > w4[i - 1]):
                continue
            sl_h = Lh[max(0, i - 3):i + 1].min() * 0.997
            if sl_h >= Ch[i]:
                continue
            sp_h = (Ch[i] - sl_h) / Ch[i] * 100
            if not (4.0 < sp_h <= 12.0):
                continue
            last = i
            # контроль: вход на HTF
            htf_stops.append(sp_h)
            for tp in (1.0, 2.0, 3.0):
                htf_res[tp].append(exit_tp(i, Hh, Lh, Ch, sl_h, tp, 96) - COST)

            # ── ВХОД на LTF: первый разворот WT вверх после закрытия HTF-бара ──
            t_from = int(Th[i]) + BARS_PER[a.htf]           # только ПОСЛЕ закрытия бара сетапа
            t_to = t_from + a.window_bars * BARS_PER[a.htf]
            j0 = int(np.searchsorted(Tl, t_from))
            j1 = int(np.searchsorted(Tl, t_to))
            if j0 < 5 or j1 <= j0 or j1 >= len(Cl) - 1:
                continue
            # ВАРИАНТ ВХОДА (переключается --entry): 'wt' = ждём разворот WT на LTF
            # (это ПОДТВЕРЖДЕНИЕ → опоздание, WR падает 57.7%→46.6%);
            # 'limit' = НЕ ждём сигнал, ставим лимит на LIMIT_PCT ниже закрытия HTF-бара
            # и берём лучшую цену, если её нальют. Это и есть смысл «входы на младших ТФ».
            entry_j = -1
            if ENTRY_MODE == 'wt':
                for j in range(j0, min(j1, len(Cl) - 1)):
                    if wl[j] < -50 and wl[j] > wl[j - 1]:
                        entry_j = j
                        break
            else:
                lim = Ch[i] * (1.0 - LIMIT_PCT / 100.0)
                for j in range(j0, min(j1, len(Cl) - 1)):
                    if Ll[j] <= lim:            # лимит налили
                        entry_j = j
                        break
                if entry_j >= 0:
                    globals()['Cl_entry_override'] = lim     # входим ПО ЦЕНЕ ЛИМИТА, не по close
            if entry_j < 0:
                continue
            # 🔴 ПРАВИЛЬНЫЙ MTF: вход точный (LTF), но СТОП ПО СТАРШЕМУ ТФ.
            # Первая версия брала стоп по структуре LTF → он падал 7.83% → 1.48%,
            # косты съедали 24% цели, а шум выбивал (WR 57.7% → 47.4%). Это убивало идею.
            # Смысл MTF: вход ближе к развороту при ТОМ ЖЕ риске → расстояние до стопа
            # меньше, цель та же → RR выше.
            sl_l = sl_h                      # стоп с HTF-структуры
            if sl_l >= (Cl_entry_override if ENTRY_MODE == 'limit' else Cl[entry_j]):
                continue
            entry_px = Cl_entry_override if ENTRY_MODE == 'limit' else Cl[entry_j]
            sp_l = (entry_px - sl_l) / entry_px * 100
            if not (0.2 < sp_l <= 12.0):
                continue
            ltf_stops.append(sp_l)
            # TTL на LTF эквивалентен 96 барам HTF
            ttl_l = int(96 * BARS_PER[a.htf] / BARS_PER[a.ltf])
            for tp in (1.0, 2.0, 3.0):
                ltf_res[tp].append(exit_tp(entry_j, Hl, Ll, Cl, sl_l, tp, ttl_l,
                                           entry_px=entry_px) - COST)

    print(f"\nпар обработано: {pairs} · сетапов HTF: {len(htf_stops)} · из них вход на LTF найден: "
          f"{len(ltf_stops)} ({100 * len(ltf_stops) / max(len(htf_stops), 1):.0f}%)")
    if htf_stops:
        print(f"медиана стопа: {a.htf} {np.median(htf_stops):.2f}%  →  {a.ltf} "
              f"{np.median(ltf_stops):.2f}%" if ltf_stops else "")

    print(f"\n{'вариант':<28} {'n':>6} {'медиана':>10} {'WR%':>7} {'PF':>7} {'%/сделку':>11}")
    for tp in (1.0, 2.0, 3.0):
        r = stat(htf_res[tp])
        if r:
            print(f"{f'КОНТРОЛЬ {a.htf} · TP={tp}R':<28} {r[0]:>6} {r[1]:>+9.3f}% {r[2]:>6.1f}% "
                  f"{r[3]:>7.2f} {r[4]:>+10.3f}%")
    print()
    for tp in (1.0, 2.0, 3.0):
        r = stat(ltf_res[tp])
        if r:
            print(f"{f'MTF {a.htf}→{a.ltf} · TP={tp}R':<28} {r[0]:>6} {r[1]:>+9.3f}% {r[2]:>6.1f}% "
                  f"{r[3]:>7.2f} {r[4]:>+10.3f}%")

    print("\n" + "═" * 100)
    bh = max(((stat(htf_res[tp]) or [0, 0, 0, 0, -9])[4], tp) for tp in (1.0, 2.0, 3.0))
    bl = max(((stat(ltf_res[tp]) or [0, 0, 0, 0, -9])[4], tp) for tp in (1.0, 2.0, 3.0))
    print(f"лучший контроль ({a.htf}):  TP={bh[1]}R → {bh[0]:+.3f}%/сделку")
    print(f"лучший MTF ({a.htf}→{a.ltf}): TP={bl[1]}R → {bl[0]:+.3f}%/сделку")
    print(f"➜ MTF {'ЛУЧШЕ' if bl[0] > bh[0] else 'ХУЖЕ'} контроля на {bl[0] - bh[0]:+.3f} п.п. на сделку")
    print("═" * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
