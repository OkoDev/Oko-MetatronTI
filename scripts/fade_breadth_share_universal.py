# -*- coding: utf-8 -*-
"""ГЕЙТ ШИРИНЫ КАК ДОЛЯ ВСЕЛЕННОЙ — переносится ли порог между ТФ? (13.08.2026, Даат).

Проблема, которую закрываем: гейт «ширина залива» найден в АБСОЛЮТЕ —
на 4h порог ≥61 монет (вселенная 140), на 15m ≥42 (вселенная 60). Абсолютное число
не переносится между ТФ и между размерами вселенной → правило в такой форме
подозрительно как подгонка под конкретную выборку.

Гипотеза: настоящая величина — ДОЛЯ вселенной, сигналящая одновременно
(«какая часть рынка льётся прямо сейчас»), а не число монет.
Если один и тот же порог ДОЛИ работает и на 4h, и на 15m — форма правила верна.

Активная вселенная считается ЧЕСТНО: сколько монет реально торговалось (имели бары)
в окне [t−24ч, t] — а не сколько их всего в дампе. Иначе доля поедет из-за листингов.

Запуск:  python scripts/fade_breadth_share_universal.py
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DB = "ohlcv_cache.db"
W_MS = 24 * 3600 * 1000
DUMPS = [("4h", "scripts/_fade_signals_4h_2022_breadth.csv"),
         ("15m", "scripts/_fade_signals_15m_2024.csv")]


def causal_breadth(d: pd.DataFrame) -> np.ndarray:
    """Сколько РАЗНЫХ монет дали сигнал в окне [t−24ч, t] — только прошлое."""
    ts, sym = d.ts.values, d.symbol.values
    br = np.zeros(len(d), dtype=int)
    lo, cnt, uniq = 0, defaultdict(int), 0
    for i in range(len(d)):
        while ts[lo] < ts[i] - W_MS:
            cnt[sym[lo]] -= 1
            if cnt[sym[lo]] == 0:
                uniq -= 1
            lo += 1
        if cnt[sym[i]] == 0:
            uniq += 1
        cnt[sym[i]] += 1
        br[i] = uniq
    return br


def active_universe(tf: str, days: pd.Series) -> dict:
    """Сколько монет РЕАЛЬНО торговалось в каждый день (есть бары) — честный знаменатель."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    q = ("SELECT strftime('%Y-%m-%d', time/1000, 'unixepoch') d, COUNT(DISTINCT symbol) n "
         "FROM ohlcv_cache WHERE timeframe=? GROUP BY d")
    rows = con.execute(q, (tf,)).fetchall()
    con.close()
    return {d: n for d, n in rows}


def stat(s: pd.Series):
    if len(s) == 0:
        return None
    pf = s[s > 0].sum() / abs(s[s < 0].sum()) if (s < 0).any() else 99.0
    return len(s), float(s.median()), 100.0 * float((s > 0).mean()), float(pf)


def main() -> int:
    print("═" * 104)
    print("ГЕЙТ ШИРИНЫ КАК ДОЛЯ ВСЕЛЕННОЙ · переносится ли ОДИН порог между 4h и 15m?")
    print("доля = (монет с сигналом за 24ч) / (монет, реально торговавшихся в этот день)")
    print("═" * 104)

    prepared = {}
    for tf, path in DUMPS:
        try:
            d = pd.read_csv(path).sort_values("ts").reset_index(drop=True)
        except FileNotFoundError:
            print(f"\n[{tf}] дамп не найден: {path}")
            continue
        d["br24"] = causal_breadth(d)
        d["t"] = pd.to_datetime(d.ts, unit="ms")
        d["day"] = d.t.dt.strftime("%Y-%m-%d")
        act = active_universe(tf, d.day)
        d["active"] = d.day.map(act).fillna(np.nan)
        d = d[d.active.notna() & (d.active > 0)].copy()
        d["share"] = d.br24 / d.active
        prepared[tf] = d
        L = d[(d.side == "LONG") & (d.stop_pct > 8) & (d.stop_pct <= 12)]
        print(f"\n[{tf}] сигналов {len(d)} · LONG(стоп8-12%) {len(L)} · "
              f"активных монет медиана {d.active.median():.0f} · "
              f"доля: медиана {d.share.median():.3f}, макс {d.share.max():.3f}")

    if len(prepared) < 2:
        print("\nнужны оба дампа")
        return 1

    # ── единая сетка порогов ДОЛИ ──────────────────────────────────────────────
    print("\n" + "═" * 104)
    print("ЕДИНЫЙ ПОРОГ ДОЛИ на обоих ТФ (LONG · стоп 8–12%)")
    print("─" * 104)
    print(f"{'порог доли':<14} " + " ".join(f"{'│ ' + tf + ': n / медиана / PF':<34}" for tf in prepared))
    for thr in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
        cells = []
        for tf, d in prepared.items():
            L = d[(d.side == "LONG") & (d.stop_pct > 8) & (d.stop_pct <= 12) & (d.share >= thr)]
            r = stat(L.net)
            cells.append(f"│ {r[0]:>5} / {r[1]:>+7.2f}% / {r[3]:>6.2f}     " if r and r[0] >= 20
                         else f"│ {'—' if r is None else r[0]:>5} мало{'':>22}")
        print(f"доля ≥ {thr:<7.2f} " + " ".join(f"{c:<34}" for c in cells))

    # ── контроль: то же для НЕ прошедших гейт ──────────────────────────────────
    print("\n" + "─" * 104)
    print("КОНТРОЛЬ — сигналы НИЖЕ порога (должно быть заметно хуже)")
    for thr in (0.15, 0.20, 0.25):
        cells = []
        for tf, d in prepared.items():
            L = d[(d.side == "LONG") & (d.stop_pct > 8) & (d.stop_pct <= 12) & (d.share < thr)]
            r = stat(L.net)
            cells.append(f"│ {r[0]:>5} / {r[1]:>+7.2f}% / {r[3]:>6.2f}     " if r else "│ —")
        print(f"доля < {thr:<7.2f} " + " ".join(f"{c:<34}" for c in cells))

    # ── значимость на лучшем общем пороге ──────────────────────────────────────
    print("\n" + "═" * 104)
    print("ЗНАЧИМОСТЬ (Mann–Whitney, односторонний: выше порога лучше)")
    print("─" * 104)
    for thr in (0.15, 0.20, 0.25):
        line = f"порог {thr:.2f}: "
        for tf, d in prepared.items():
            L = d[(d.side == "LONG") & (d.stop_pct > 8) & (d.stop_pct <= 12)]
            a, b = L[L.share < thr].net, L[L.share >= thr].net
            if len(a) < 20 or len(b) < 20:
                line += f"{tf}: мало  "
                continue
            p = stats.mannwhitneyu(a, b, alternative="less").pvalue
            pfa = a[a > 0].sum() / abs(a[a < 0].sum()) if (a < 0).any() else 99
            pfb = b[b > 0].sum() / abs(b[b < 0].sum()) if (b < 0).any() else 99
            line += f"{tf}: PF {pfa:.2f}→{pfb:.2f} p={p:.5f}   "
        print(line)

    # ── зеркало SHORT и охват ──────────────────────────────────────────────────
    print("\n" + "─" * 104)
    print("ЗЕРКАЛО SHORT и охват при доле ≥0.20")
    for tf, d in prepared.items():
        S = d[(d.side == "SHORT") & (d.stop_pct > 8) & (d.stop_pct <= 12) & (d.share >= 0.20)]
        L = d[(d.side == "LONG") & (d.stop_pct > 8) & (d.stop_pct <= 12) & (d.share >= 0.20)]
        rs, rl = stat(S.net), stat(L.net)
        print(f"  [{tf}] LONG n={rl[0] if rl else 0} PF {rl[3]:.2f} монет {L.symbol.nunique()} "
              f"дней {L.day.nunique()} │ SHORT n={rs[0] if rs else 0} "
              f"PF {rs[3]:.2f}" if rs and rl else f"  [{tf}] мало данных")
    print("═" * 104)
    return 0


if __name__ == "__main__":
    sys.exit(main())
