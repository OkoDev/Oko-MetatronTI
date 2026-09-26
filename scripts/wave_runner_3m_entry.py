# -*- coding: utf-8 -*-
"""ОЦИФРОВКА РУЧНОЙ СХЕМЫ ЕГОРА: слом на 3m в зоне → откат → волна-3.

Егор, 04.09.2026: «руками я захожу по слому на 3м». Схема записана ещё 08.06
([[user_wave_runner_strategy]], $50→$7000 руками):

    «ждал слом на 3m в нужной зоне → откат → волна-3. Работало многократно»
    «RR честный = от инвалидации: вход на младшем ТФ → стоп КОМПАКТНЫЙ
     (под 5m/3m swing, инвалидация близко) → RR 7:1 (vs 2.4:1 с дальним 4h-стопом)»

🔴 ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ МОИХ ПРЕДЫДУЩИХ ЗАМЕРОВ (и почему те дали 0.33 RR):
  · стоп я ставил под начало импульса СТАРШЕГО масштаба — далеко, RR разваливался.
    Здесь стоп под swing МЛАДШЕГО ТФ: инвалидация локальной структуры, компактно.
  · вход я делал на самом сломе. Здесь слом — только ТРИГГЕР; вход на ОТКАТЕ после него.
  · зону брал на том же ТФ. Здесь зона приходит со СТАРШЕГО (OTE его импульса).

Три этажа, как в методе:
  1. СТАРШИЙ (1h/4h) — зона: OTE его импульса. Причинность: ресемпл + `shift(1)`.
  2. МЛАДШИЙ (3m/5m/15m) — слом эталона OKO-SM внутри зоны = разворот подтверждён.
     Слои РАЗДЕЛЕНЫ: micro(len=5) против swing(len=50) — что из них триггер.
  3. ВХОД — откат после слома; стоп под локальный swing; цель — расширение старшего.

Контроль (закон проекта): `nowait` — вход сразу на сломе без отката, и `random` —
случайный бар в том же окне. Без них «сработало» ничего не значит.

Запуск: python scripts/wave_runner_3m_entry.py [n_symbols] [ltf] [htf]
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

OTE_LO, OTE_HI = 0.62, 0.79     # уровни эталона build_ote (канон Егора 02.06)
TARGET_EXT = 1.0                # цель волны 3 = measured move: конец в.1 + 1.0×(в.1)
SWING_LOOK = 20                 # окно локального swing под стоп (баров младшего)
PULLBACK_WAIT = 10              # сколько баров ждём откат после слома
HOLD = 400                      # держим до цели/стопа (волна-3 длинная)
WARMUP = 300
RULE = {"3m": "3min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h"}


def _htf_zone(dl: pd.DataFrame, htf: str) -> pd.DataFrame:
    """Зона OTE старшего ТФ на сетке младшего. shift(1) = только ЗАКРЫТЫЙ бар."""
    from core.smc.smc_engine import build_ote
    agg = dl.resample(RULE[htf]).agg({"open": "first", "high": "max", "low": "min",
                                      "close": "last", "volume": "sum"}).dropna()
    if len(agg) < 120:
        return pd.DataFrame(index=dl.index)
    h, l = agg["high"].values, agg["low"].values
    zlo, zhi, tgt, up = [], [], [], []
    LOOK = 40
    for i in range(len(agg)):
        if i < LOOK:
            zlo.append(np.nan); zhi.append(np.nan); tgt.append(np.nan); up.append(False); continue
        hi_i = int(np.argmax(h[i - LOOK:i + 1])) + i - LOOK
        lo_i = int(np.argmin(l[i - LOOK:i + 1])) + i - LOOK
        # 🔴 ЭТО ПРОДОЛЖЕНИЕ (волна 3), а НЕ разворот. Волна 1 = импульс, волна 2 =
        # откат в OTE, вход в ту же сторону. Не путать с `method_egor`, который
        # mean-reversion у экстремума: у `build_ote` поле `direction` считает именно
        # разворот (импульс вверх → 'short'), нам оно НЕ подходит.
        if lo_i < hi_i:                       # волна 1 ВВЕРХ (low → high) → LONG в в.3
            a, b, u = float(l[lo_i]), float(h[hi_i]), True
        else:                                 # волна 1 ВНИЗ (high → low) → SHORT в в.3
            a, b, u = float(h[hi_i]), float(l[lo_i]), False
        if abs(b - a) / max(abs(a), 1e-9) < 0.03:
            zlo.append(np.nan); zhi.append(np.nan); tgt.append(np.nan); up.append(False); continue
        o = build_ote(a, b)                   # 0 = начало в.1, 1 = конец в.1
        z1, z2 = o["levels"][OTE_LO], o["levels"][OTE_HI]
        zlo.append(min(z1, z2)); zhi.append(max(z1, z2))
        # 🔴 ЦЕЛЬ волны 3 = measured move ЗА конец волны 1: b + k·(b−a).
        # В `build_ote` таких уровней нет — отрицательные фибо там лежат ЗА НАЧАЛО
        # (проверено: импульс 100→110 даёт −0.62 = 93.8, то есть ниже старта).
        tgt.append(b + TARGET_EXT * (b - a)); up.append(u)
    out = pd.DataFrame({"zlo": zlo, "zhi": zhi, "tgt": tgt, "up": up}, index=agg.index)
    return out.shift(1).reindex(dl.index, method="ffill")


def collect_symbol(sym: str, ltf: str, htf: str) -> list[dict]:
    from core.smc.oko_sm_engine import run_structure
    dl = load(sym, ltf)
    if len(dl) < 5000:
        return []
    z = _htf_zone(dl, htf)
    if z.empty or "zlo" not in z:
        return []
    idx = dl.index
    dd = dl.reset_index(drop=True)
    n = len(dd)
    o, h, l, c = dd.open.values, dd.high.values, dd.low.values, dd.close.values
    st = run_structure(dd, swing_len=50, internal_len=5, record_legs=False)
    ev = {"micro": {}, "swing": {}}
    for e in st.events:
        ev["micro" if e.internal else "swing"].setdefault(e.i, []).append(e.bull)
    zlo, zhi, tgt, upv = z["zlo"].values, z["zhi"].values, z["tgt"].values, z["up"].values

    rng = np.random.default_rng(abs(hash(sym)) % (2 ** 32))
    out, last = [], -999
    for i in range(WARMUP, n - HOLD - PULLBACK_WAIT - 2):
        if i - last < 30:
            continue
        if not (np.isfinite(zlo[i]) and np.isfinite(zhi[i]) and np.isfinite(tgt[i])):
            continue
        if not (zlo[i] <= c[i] <= zhi[i]):        # цена В ЗОНЕ старшего
            continue
        up = bool(upv[i])
        for layer in ("micro", "swing"):
            # ── ТРИГГЕР: слом младшего В СТОРОНУ сетапа, внутри зоны
            brk = None
            for j in range(i, min(i + PULLBACK_WAIT, n)):
                if any(b == up for b in ev[layer].get(j, ())):
                    brk = j
                    break
            if brk is None:
                continue
            # ── ВХОД: откат после слома (цена возвращается к цене слома), иначе — по рынку
            lvl = float(c[brk])
            eb = None
            for j in range(brk + 1, min(brk + 1 + PULLBACK_WAIT, n)):
                if (l[j] <= lvl) if up else (h[j] >= lvl):
                    eb = j
                    break
            variants = {f"{layer}_pullback": eb,
                        f"{layer}_nowait": brk + 1,
                        f"{layer}_random": int(rng.integers(brk + 1, brk + 2 + PULLBACK_WAIT))}
            for tag, b_ in variants.items():
                if b_ is None or b_ + HOLD >= n or b_ >= n:
                    continue
                e = float(o[b_])
                # ── СТОП под локальный swing МЛАДШЕГО (компактная инвалидация)
                k0 = max(0, b_ - SWING_LOOK)
                sl = (float(l[k0:b_].min()) * 0.999 if up else float(h[k0:b_].max()) * 1.001)
                risk = (e - sl) if up else (sl - e)
                if risk <= 0:
                    continue
                tp = float(tgt[i])
                reward = (tp - e) if up else (e - tp)
                if reward <= 0:
                    continue
                pnl = None
                for j in range(b_, min(b_ + HOLD, n)):
                    if (l[j] <= sl) if up else (h[j] >= sl):
                        pnl = (sl - e) / e * 100 * (1 if up else -1) - COST_LIMIT
                        break
                    if (h[j] >= tp) if up else (l[j] <= tp):
                        pnl = (tp - e) / e * 100 * (1 if up else -1) - COST_LIMIT
                        break
                if pnl is None:
                    x = float(c[min(b_ + HOLD, n - 1)])
                    pnl = (x - e) / e * 100 * (1 if up else -1) - COST_LIMIT
                out.append({"sym": sym, "variant": tag, "side": "long" if up else "short",
                            "year": int(pd.Timestamp(idx[b_]).year),
                            "stop_pct": risk / e * 100, "rr": reward / risk,
                            "delay": b_ - i, "pnl": pnl})
        last = i
    return out


def _line(tag, R):
    if len(R) < 20:
        print(f"{tag:24s} n={len(R):5d}  — мало")
        return
    p = R.pnl.values
    frag = np.sort(p)[:-max(1, len(p) // 10)].sum()
    cov = (R.groupby("sym").pnl.sum() > 0).mean() * 100
    w, l_ = p[p > 0].sum(), -p[p < 0].sum()
    pf = w / l_ if l_ > 0 else float("inf")
    print(f"{tag:24s} n={len(p):5d} WR {(p > 0).mean()*100:4.1f}% PF {pf:5.2f} "
          f"ср {p.mean():+6.2f}% стоп {R.stop_pct.median():5.2f}% RR {R.rr.median():5.1f} "
          f"безтоп10% {frag:+8.1f}% монет+ {cov:4.0f}%")


def main() -> None:
    n_sym = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    ltf = sys.argv[2] if len(sys.argv) > 2 else "15m"
    htf = sys.argv[3] if len(sys.argv) > 3 else "4h"
    syms = universe(ltf, n=n_sym)
    print(f"СХЕМА ЕГОРА: зона {htf} → слом {ltf} → откат → волна-3")
    print(f"вселенная {len(syms)} · стоп под swing {ltf} ({SWING_LOOK} баров) · "
          f"цель = фибо {TARGET_FIB} старшего · косты {COST_LIMIT}%\n")
    rows = []
    for i, s in enumerate(syms, 1):
        try:
            rows += collect_symbol(s, ltf, htf)
        except Exception as e:  # noqa: BLE001
            print(f"  [{s}] {type(e).__name__}: {str(e)[:60]}")
        if i % 5 == 0:
            print(f"  ... {i}/{len(syms)} · {len(rows)}", flush=True)
    R = pd.DataFrame(rows)
    if R.empty:
        print("НОЛЬ сетапов — отказ, а не вывод.")
        return
    print(f"\nсобрано {len(R)} · монет {R.sym.nunique()}\n")
    print("=" * 128)
    print("ТРИГГЕР И СПОСОБ ВХОДА (стоп/цель одинаковы)")
    print("=" * 128)
    for layer in ("micro", "swing"):
        for kind in ("pullback", "nowait", "random"):
            _line(f"{layer}_{kind}", R[R.variant == f"{layer}_{kind}"])
        print()
    print("── лучший вариант по сторонам и годам ──")
    best = max(("micro_pullback", "swing_pullback", "micro_nowait", "swing_nowait"),
               key=lambda v: (R[R.variant == v].pnl.mean() if (R.variant == v).sum() > 20 else -9))
    B = R[R.variant == best]
    print(f"({best})")
    for sd in ("long", "short"):
        _line(f"  {sd}", B[B.side == sd])
    for y in sorted(B.year.unique()):
        _line(f"  {y}", B[B.year == y])


if __name__ == "__main__":
    main()
