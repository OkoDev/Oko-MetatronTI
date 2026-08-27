# -*- coding: utf-8 -*-
"""АУДИТ LOOK-AHEAD для 4h-фейда с большим стопом (13.08.2026, Даат).

Повод: разрез по годам дал LONG стоп 8–12% → 2024 PF 5.33 WR 81.7%, 2025 PF 2.71 WR 73.0%,
но 2026 PF 0.19 WR 18.9%. WR 81.7% на контр-трендовой механике — слишком красиво.
Наши же законы (memory/oko_suite_trend_wt_validated) перечисляют 4 класса look-ahead,
и первый из них — «impulse по концу истории», второй — «скан всего df».

Три проверки, каждая ловит свой класс:
  A. ВХОД ПО СЛЕДУЮЩЕМУ БАРУ. Сигнал на закрытии бара i, но исполнение по open[i+1].
     Если эдж жив только при входе по close[i] — мы торгуем цену, которой не было.
  B. ПОРЯДОК TP/SL ВНУТРИ БАРА. Текущий exit проверяет SL раньше TP на одном баре.
     Инвертируем приоритет: если результат сильно меняется — эдж держится на допущении
     о внутрибарной последовательности, а не на движении.
  C. ПРИЧИННОСТЬ ИНДИКАТОРОВ. detector(df[:n]) должен совпадать с detector(df)[i<n].
     Проверяется запуском, а не рассуждением (требование research-verdict п.1.4).

Запуск:  python scripts/fade_lookahead_audit.py [--year 2024] [--coins 60]
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
COOL = 2
TTL = 24


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
    n = len(c); cv = c.values
    u = np.zeros(n); d_ = np.zeros(n); dirn = np.zeros(n)
    u[0], d_[0], dirn[0] = up[0], dn[0], 1
    for i in range(1, n):
        u[i] = max(up[i], u[i - 1]) if cv[i - 1] > u[i - 1] else up[i]
        d_[i] = min(dn[i], d_[i - 1]) if cv[i - 1] < d_[i - 1] else dn[i]
        dirn[i] = 1 if cv[i] > d_[i - 1] else (-1 if cv[i] < u[i - 1] else dirn[i - 1])
    return dirn


def exit_trade(entry_i, entry_px, H, L, C, sl, side, tp_first: bool):
    """tp_first=False — как в боевом бэктесте (SL проверяется первым на баре)."""
    e = entry_px
    if side == "LONG":
        tp = e + (e - sl)
        end = min(entry_i + TTL, len(C) - 1)
        for j in range(entry_i + 1, end + 1):
            hit_sl, hit_tp = L[j] <= sl, H[j] >= tp
            if hit_sl and hit_tp:
                return ((tp - e) / e * 100, "TP") if tp_first else ((sl - e) / e * 100, "SL")
            if hit_sl:
                return (sl - e) / e * 100, "SL"
            if hit_tp:
                return (tp - e) / e * 100, "TP"
        return (C[end] - e) / e * 100, "TTL"
    tp = e - (sl - e)
    end = min(entry_i + TTL, len(C) - 1)
    for j in range(entry_i + 1, end + 1):
        hit_sl, hit_tp = H[j] >= sl, L[j] <= tp
        if hit_sl and hit_tp:
            return ((e - tp) / e * 100, "TP") if tp_first else ((e - sl) / e * 100, "SL")
        if hit_sl:
            return (e - sl) / e * 100, "SL"
        if hit_tp:
            return (e - tp) / e * 100, "TP"
    return (e - C[end]) / e * 100, "TTL"


def run(year: int, coins: int):
    t0 = int(dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    t1 = int(dt.datetime(year + 1, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' AND time>=? AND time<? "
        "GROUP BY symbol HAVING n>400 ORDER BY n DESC LIMIT ?", (t0, t1, coins)).fetchall()]
    con.close()

    res = {k: [] for k in ("base", "nextbar", "tpfirst")}
    exits = {"TP": 0, "SL": 0, "TTL": 0}
    causal_bad = 0
    causal_checked = 0

    for s in syms:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        # берём с запасом назад, чтобы индикаторы прогрелись
        d = pd.read_sql("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? "
                        "AND timeframe='4h' AND time>=? AND time<? ORDER BY time",
                        c, params=(s, t0 - 250 * 4 * 3600 * 1000, t1))
        c.close()
        if len(d) < 300:
            continue
        w_ = wt(d); tr_ = atrt(d)
        O, H, L, C, T = d.open.values, d.high.values, d.low.values, d.close.values, d.time.values

        # ── C. причинность: индикаторы на срезе == индикаторы на полном ряде ──
        if causal_checked < 3:
            n_cut = len(d) - 40
            w_cut = wt(d.iloc[:n_cut]); tr_cut = atrt(d.iloc[:n_cut])
            k = n_cut - 1
            if abs(w_cut[k] - w_[k]) > 1e-6 or tr_cut[k] != tr_[k]:
                causal_bad += 1
            causal_checked += 1

        last = -10 ** 9
        for i in range(210, len(d) - 1):
            if T[i] < t0:
                continue
            if i - last < COOL:
                continue
            if not (tr_[i] > 0 and w_[i] < -60 and w_[i] > w_[i - 1]):
                continue
            sl = L[max(0, i - 3):i + 1].min() * 0.997
            if sl >= C[i]:
                continue
            sp = (C[i] - sl) / C[i] * 100
            if not (8.0 < sp <= 12.0):
                continue
            last = i
            # base: вход по close[i], SL приоритетнее
            r0, e0 = exit_trade(i, C[i], H, L, C, sl, "LONG", tp_first=False)
            res["base"].append(r0 - COST)
            exits[e0] += 1
            # A: вход по open[i+1] — цена, которая реально доступна
            r1, _ = exit_trade(i + 1, O[i + 1], H, L, C, sl, "LONG", tp_first=False)
            res["nextbar"].append(r1 - COST)
            # B: приоритет TP на баре
            r2, _ = exit_trade(i, C[i], H, L, C, sl, "LONG", tp_first=True)
            res["tpfirst"].append(r2 - COST)
    return res, exits, causal_bad, causal_checked, len(syms)


def stat(v):
    a = np.array(v)
    pf = a[a > 0].sum() / abs(a[a < 0].sum()) if (a < 0).any() else 99.0
    return len(a), float(np.median(a)), 100.0 * float((a > 0).mean()), float(pf), float(a.sum())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--coins", type=int, default=60)
    a = ap.parse_args()

    print("═" * 96)
    print(f"АУДИТ LOOK-AHEAD · 4h фейд LONG · стоп 8–12% · год {a.year} · монет ≤{a.coins}")
    print("═" * 96)
    res, exits, cbad, cchk, nsym = run(a.year, a.coins)
    if not res["base"]:
        print("сигналов нет")
        return 1

    print(f"\n{'вариант':<34} {'n':>6} {'медиана':>10} {'WR%':>7} {'PF':>7} {'сумма':>10}")
    print("─" * 96)
    names = {
        "base": "БАЗА (close[i], SL первым)",
        "nextbar": "A. вход по open[i+1]",
        "tpfirst": "B. приоритет TP на баре",
    }
    base_pf = None
    for k in ("base", "nextbar", "tpfirst"):
        n, med, wr, pf, tot = stat(res[k])
        if k == "base":
            base_pf = pf
        print(f"{names[k]:<34} {n:>6} {med:>+9.3f}% {wr:>6.1f}% {pf:>7.2f} {tot:>+9.1f}")

    n_all = sum(exits.values())
    print(f"\nвыходы: TP {exits['TP']} ({100*exits['TP']/n_all:.0f}%) · "
          f"SL {exits['SL']} ({100*exits['SL']/n_all:.0f}%) · "
          f"TTL {exits['TTL']} ({100*exits['TTL']/n_all:.0f}%)")
    print(f"причинность индикаторов: проверено {cchk} символов, расхождений {cbad} "
          f"{'✅ причинно' if cbad == 0 else '🔴 LOOK-AHEAD!'}")

    _, _, _, pf_nb, _ = stat(res["nextbar"])
    _, _, _, pf_tf, _ = stat(res["tpfirst"])
    print("\n" + "═" * 96)
    print("ИНТЕРПРЕТАЦИЯ")
    d_nb = 100 * (pf_nb - base_pf) / base_pf if base_pf else 0
    d_tf = 100 * (pf_tf - base_pf) / base_pf if base_pf else 0
    print(f"  вход по следующему бару: PF {base_pf:.2f} → {pf_nb:.2f} ({d_nb:+.0f}%)"
          f" {'— эдж ВЫЖИЛ' if pf_nb > 1.3 else '— 🔴 эдж РАЗВАЛИЛСЯ'}")
    print(f"  приоритет TP на баре   : PF {base_pf:.2f} → {pf_tf:.2f} ({d_tf:+.0f}%)"
          f" {'— устойчив' if abs(d_tf) < 25 else '— 🔴 держится на внутрибарном допущении'}")
    print("═" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())
