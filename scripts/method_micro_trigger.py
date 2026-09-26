# -*- coding: utf-8 -*-
"""МЕТОД ЕГОРА + МИКРОСТРУКТУРА КАК ТРИГГЕР ВХОДА (Егор, 04.09.2026).

    «новые слои в разволновке т.е. микроструктура в помощь, нужно пользоваться»

Куда именно её ставить — задано документом `OTE_METHOD_ENTRY_V2.md`:
    вход на КАСАНИИ OTE (волна 2)  = ловля ножа, −0.70% WR 31%
    вход на СЛОМЕ    (волна 3 BOS) = работает,   +1.13% WR 76%
Между ними — дыра: касание уже случилось, полный BOS ещё нет. Микро-слой эталона
(`internal`, len=5) закрывает её: мини-слом ВНУТРИ зоны = разворот подтверждён
локально, но вход ещё близко к экстремуму.

Сравниваем при ОДНОЙ геометрии (стоп и цели метода не меняем):
  A `touch`  — вход на первом баре в OTE (как сейчас в `ote_retest_setups`);
  B `micro`  — ждём микро-слом В СТОРОНУ сетапа внутри окна после касания;
  C `swing`  — то же, но слом СТАРШЕГО слоя (len=50) — для контраста слоёв;
  D `random` — случайный бар в том же окне (контрольная группа, закон проекта).

🔴 Причинность: событие эталона на баре i известно только ПОСЛЕ его закрытия →
вход на i+1. Старший ТФ — ресемпл со `shift(1)`.

Запуск: python scripts/method_micro_trigger.py [n_symbols] [tf] [wait_bars]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from research_harness import load, universe, COST_LIMIT  # noqa: E402

HOLD = 96
WARMUP = 400
OTE_LO, OTE_HI = 0.62, 0.79        # уровни эталона build_ote (канон 02.06)
IMP_LOOK = 60


def _atr(df, n=14):
    h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def collect_symbol(sym: str, tf: str, wait: int) -> list[dict]:
    """Сетап = импульс + откат в OTE. Дальше 4 способа выбрать бар входа."""
    from core.smc.oko_sm_engine import run_structure
    from core.smc.smc_engine import build_ote

    df = load(sym, tf)
    if len(df) < 3000:
        return []
    idx = df.index
    dd = df.reset_index(drop=True)
    n = len(dd)
    o, h, l, c = dd.open.values, dd.high.values, dd.low.values, dd.close.values
    atr = _atr(dd)

    st = run_structure(dd, swing_len=50, internal_len=5, record_legs=False)
    micro_up = {e.i for e in st.events if e.internal and e.bull}
    micro_dn = {e.i for e in st.events if e.internal and not e.bull}
    swing_up = {e.i for e in st.events if not e.internal and e.bull}
    swing_dn = {e.i for e in st.events if not e.internal and not e.bull}

    rng = np.random.default_rng(abs(hash(sym)) % (2 ** 32))
    out, last = [], -999
    for i in range(WARMUP, n - HOLD - wait - 2):
        if i - last < 20:
            continue
        # ── импульс и зона отката
        hi_i = int(np.argmax(h[i - IMP_LOOK:i + 1])) + i - IMP_LOOK
        lo_i = int(np.argmin(l[i - IMP_LOOK:i + 1])) + i - IMP_LOOK
        if hi_i < lo_i:                       # импульс ВВЕРХ → ждём откат вниз, LONG
            up, a, b = True, float(l[lo_i]), float(h[hi_i])
        else:                                 # импульс ВНИЗ → откат вверх, SHORT
            up, a, b = False, float(h[hi_i]), float(l[lo_i])
        if abs(b - a) / max(abs(a), 1e-9) < 0.02:
            continue
        ote = build_ote(a, b)
        z1, z2 = ote["levels"][OTE_LO], ote["levels"][OTE_HI]
        zlo, zhi = min(z1, z2), max(z1, z2)
        if not (zlo <= c[i] <= zhi):          # касание зоны = момент сетапа
            continue
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue

        # ── стоп/цель ОДНИ для всех вариантов.
        # 🔴 ЦЕЛЬ — ФИБО-РАСШИРЕНИЕ за конец импульса (уровень −0.62), а НЕ сам конец.
        # Первый смоук ставил цель на b и дал RR 0.33-0.49: в зоне OTE до конца импульса
        # остаётся лишь 21-38% размаха, а стоп за начало — 62-79%. Канон метода —
        # «стоп короткий, цель огромная», и `build_ote` держит для этого отрицательные
        # фибо (−0.62/−1.0/−1.618, докстринг: «лестница целей метода Егора»).
        sl = a * (1.0015 if not up else 0.9985)
        tp = ote["levels"][-0.62]
        # LONG после импульса вверх: покупаем откат; SHORT после импульса вниз
        want_up, want_dn = (micro_up, micro_dn) if up else (micro_dn, micro_up)
        sw_want = swing_up if up else swing_dn

        bars = {"touch": i + 1}
        for tag, src in (("micro", want_up), ("swing", sw_want)):
            hit = next((j for j in range(i, i + wait + 1) if j in src), None)
            bars[tag] = (hit + 1) if hit is not None else None
        bars["random"] = int(rng.integers(i + 1, i + wait + 2))

        for tag, eb in bars.items():
            if eb is None or eb + HOLD >= n:
                continue
            e = float(o[eb])
            risk = (e - sl) if up else (sl - e)
            if risk <= 0:
                continue
            reward = (tp - e) if up else (e - tp)
            if reward <= 0:
                continue
            pnl = None
            for j in range(eb, min(eb + HOLD, n)):
                if (l[j] <= sl) if up else (h[j] >= sl):
                    pnl = (sl - e) / e * 100 * (1 if up else -1) - COST_LIMIT
                    break
                if (h[j] >= tp) if up else (l[j] <= tp):
                    pnl = (tp - e) / e * 100 * (1 if up else -1) - COST_LIMIT
                    break
            if pnl is None:
                x = float(c[min(eb + HOLD, n - 1)])
                pnl = (x - e) / e * 100 * (1 if up else -1) - COST_LIMIT
            out.append({"sym": sym, "variant": tag, "side": "long" if up else "short",
                        "year": int(pd.Timestamp(idx[eb]).year),
                        "delay": eb - i, "stop_pct": risk / e * 100,
                        "rr": reward / risk, "pnl": pnl})
        last = i
    return out


def _line(tag, R):
    if len(R) < 25:
        print(f"{tag:26s} n={len(R):5d}  — мало")
        return
    p = R.pnl.values
    frag = np.sort(p)[:-max(1, len(p) // 10)].sum()
    cov = (R.groupby("sym").pnl.sum() > 0).mean() * 100
    w, l_ = p[p > 0].sum(), -p[p < 0].sum()
    pf = w / l_ if l_ > 0 else float("inf")
    print(f"{tag:26s} n={len(p):5d} WR {(p > 0).mean()*100:4.1f}% PF {pf:5.2f} "
          f"ср {p.mean():+6.3f}% стоп {R.stop_pct.median():5.2f}% RR {R.rr.median():4.1f} "
          f"лаг {R.delay.median():3.0f}б безтоп10% {frag:+8.1f}% монет+ {cov:4.0f}%")


def main() -> None:
    n_sym = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    tf = sys.argv[2] if len(sys.argv) > 2 else "1h"
    wait = int(sys.argv[3]) if len(sys.argv) > 3 else 12
    syms = universe(tf, n=n_sym)
    print(f"вселенная {len(syms)} монет · {tf} · окно ожидания триггера {wait} баров")
    print("стоп/цель ОДНИ для всех вариантов — меняется ТОЛЬКО бар входа\n")
    rows = []
    for i, s in enumerate(syms, 1):
        try:
            rows += collect_symbol(s, tf, wait)
        except Exception as e:  # noqa: BLE001
            print(f"  [{s}] {type(e).__name__}: {str(e)[:60]}")
        if i % 5 == 0:
            print(f"  ... {i}/{len(syms)} · {len(rows)}", flush=True)
    R = pd.DataFrame(rows)
    if R.empty:
        print("НОЛЬ сетапов — отказ, а не вывод.")
        return
    print(f"\nсобрано {len(R)} · монет {R.sym.nunique()}\n")
    print("=" * 130)
    print("ЧЕМ ТРИГГЕРИТЬ ВХОД В ЗОНЕ OTE")
    print("=" * 130)
    for v in ("touch", "micro", "swing", "random"):
        _line(v, R[R.variant == v])
    print("\n── по сторонам ──")
    for v in ("touch", "micro", "swing", "random"):
        for sd in ("long", "short"):
            _line(f"  {v}/{sd}", R[(R.variant == v) & (R.side == sd)])
    print("\n── микро-триггер по годам ──")
    M = R[R.variant == "micro"]
    for y in sorted(M.year.unique()):
        _line(f"  micro/{y}", M[M.year == y])


if __name__ == "__main__":
    main()
