# -*- coding: utf-8 -*-
"""МЕТОД ЕГОРА: ФИБО НА ИМПУЛЬС-СЛОМЩИК → ВХОД НА КОРРЕКЦИИ → ЦЕЛЬ −1 (05.09.2026).

Записано с разметки Егора на ETH 15m (10-15 июня) и его описания:

  «Белые линии на левом сетапе — отмечен СЛОМ СТРУКТУРЫ. На ЭТОТ ИМПУЛЬС, КОТОРЫЙ СЛОМАЛ
   СТРУКТУРУ, натянута сетка. Цена дала коррекцию по фибоначчи 0.705 → ВХОД. Стоп ПОД
   СТРУКТУРУ. Далее цена даёт импульс, подтверждает сломом. На коррекции ЭТОГО импульса
   по фибо 0.5 → ВХОД, стоп за структурный уровень. Далее ещё импульс, коррекция 0.62 →
   ВХОД, стоп за структурный уровень. Цели по фибоначчи консервативные — МИНУС ОДИН,
   тейк-профит. После обновления хая цена корректируется по фибо НА ВЕСЬ ИМПУЛЬС — 0.75,
   даёт реакцию → ВХОД, стоп КОРОТКИЙ за ближайшую вершину. Цели −1 и выше.»

🔴 ЧЕМ ОТЛИЧАЕТСЯ ОТ ТОГО, ЧТО Я ТЕСТИРОВАЛ РАНЬШЕ (три ошибки подряд):
  1. сетка на ИМПУЛЬС-СЛОМЩИК, а не на `leg_history` структуры;
  2. цель — РАСШИРЕНИЕ −1 (extreme + амплитуда), а не сам extreme (это ноль по фибо);
  3. стоп — ЗА СТРУКТУРНЫЙ УРОВЕНЬ (основание импульса / ближайшая вершина), короткий;
  4. КАСКАД: каждый следующий импульс даёт новую сетку и новый вход.

Зона входа: 0.5-0.75 (у Егора на разметке 0.5 · 0.62 · 0.705 · 0.75 — разные сетапы).
Сломы берутся из ЭТАЛОНА `oko_sm_engine.run_structure` (swing_len=50, internal_len=5).

Контроль — случайный вход той же геометрии. Косты явной ставкой. Счёт в % цены.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from research_harness import load, core_universe          # noqa: E402

COST = 0.35
WAIT = 96          # сколько баров ждём коррекцию после импульса (24 ч на 15m)
HOLD = 384         # сколько держим позицию (4 суток) — цель −1 требует хода
FIB_IN = (0.5, 0.75)      # зона входа: от 0.5 до 0.75 отката
TP_EXT = 1.0              # цель −1 = extreme + 1.0 × амплитуда (консервативная у Егора)


def htf_trend(df_htf: pd.DataFrame) -> pd.Series:
    """Тренд СТАРШЕГО порядка: 1 пока лои НЕ обновляются, -1 пока не обновляются хаи.

    🔴 Егор: «выбирать исходя из КОНТЕКСТА СТАРШЕГО ПОРЯДКА: лои не обновлялись, значит
    тренд сохраняется восходящим». Это ровно `trend` эталона (swing_len=50): он держится
    бычьим, пока не случился медвежий слом Strong Low.
    """
    from core.smc.oko_sm_engine import run_structure
    d = df_htf.reset_index(drop=True)
    st = run_structure(d, swing_len=50, internal_len=5)
    tr = np.zeros(len(d), dtype=int)
    cur = 0
    ev_by_bar = {}
    for ev in st.events:
        if bool(getattr(ev, "internal", False)):
            continue                                    # только СТАРШИЙ слой
        ev_by_bar[int(ev.i)] = 1 if bool(ev.bull) else -1
    for i in range(len(d)):
        if i in ev_by_bar:
            cur = ev_by_bar[i]
        tr[i] = cur
    return pd.Series(tr, index=df_htf.index)


def setups(df: pd.DataFrame, internal: bool = False, htf: pd.Series | None = None):
    """Импульсы, СЛОМАВШИЕ структуру, и входы на их коррекции (каскадом).

    Для каждого слома:
      origin  = экстремум ПЕРЕД сломом (основание импульса, структурный уровень для стопа)
      extreme = максимум/минимум, достигнутый ПОСЛЕ слома (вершина импульса)
      вход    = первое касание зоны 0.5-0.75 отката
      стоп    = за origin (структура) с буфером
      цель    = extreme ± 1.0 × амплитуда  (фибо −1)
    """
    from core.smc.oko_sm_engine import run_structure
    d = df.reset_index(drop=True)
    st = run_structure(d, swing_len=50, internal_len=5)
    H, L, C = d.high.values, d.low.values, d.close.values
    n = len(C)
    # 🔴 ДВЕ СТРУКТУРЫ В ОДНОМ ДВИЖКЕ (Егор: «на то тебе и дано две структуры»):
    #   СТАРШИЙ слой (len=50) = КОНТЕКСТ — пока лои не обновляются, тренд восходящий;
    #   ВНУТРЕННИЙ (len=5)    = ИМПУЛЬС-СЛОМЩИК, на него натягивается сетка.
    # Старший ТФ грузить не нужно — оба слоя считаются одним прогоном на этом же ТФ.
    ctx = np.zeros(n, dtype=int)
    cur = 0
    major = {int(e.i): (1 if bool(e.bull) else -1)
             for e in st.events if not bool(getattr(e, "internal", False))}
    for t_ in range(n):
        if t_ in major:
            cur = major[t_]
        ctx[t_] = cur
    out = []
    for ev in st.events:
        if bool(getattr(ev, "internal", False)) != internal:
            continue
        i = int(ev.i)
        bull = bool(ev.bull)
        lvl_i = int(getattr(ev, "level_i", 0) or 0)
        if i < 50 or i >= n - WAIT - HOLD - 2:
            continue
        # 🔴 КОНТЕКСТ: сетап только В СТОРОНУ старшего слоя (лои/хаи не обновлены)
        if ctx[i] == 0 or (ctx[i] > 0) != bull:
            continue
        # ── импульс, который сломал структуру ────────────────────────────
        a = max(0, min(lvl_i, i - 1))
        origin = float(L[a:i + 1].min()) if bull else float(H[a:i + 1].max())
        # вершина импульса: идём вперёд, пока цена не откатится на половину хода
        ext, ext_j = (float(H[i]), i) if bull else (float(L[i]), i)
        j = i + 1
        while j < min(i + WAIT, n):
            if bull:
                if H[j] > ext:
                    ext, ext_j = float(H[j]), j
                if (ext - L[j]) >= 0.5 * (ext - origin) and ext > origin:
                    break
            else:
                if L[j] < ext:
                    ext, ext_j = float(L[j]), j
                if (H[j] - ext) >= 0.5 * (origin - ext) and origin > ext:
                    break
            j += 1
        amp = abs(ext - origin)
        if amp <= 0 or ext_j >= n - HOLD - 2:
            continue
        # ── зона входа: коррекция 0.5-0.75 от импульса ──────────────────
        z_a = ext - FIB_IN[0] * amp if bull else ext + FIB_IN[0] * amp
        z_b = ext - FIB_IN[1] * amp if bull else ext + FIB_IN[1] * amp
        z_lo, z_hi = min(z_a, z_b), max(z_a, z_b)
        entry_i = None
        for q in range(ext_j + 1, min(ext_j + WAIT, n - HOLD - 1)):
            px = L[q] if bull else H[q]
            if z_lo <= px <= z_hi:
                entry_i = q
                break
            # ушли за 0.786 — сетап отменён (инвалидация)
            if bull and L[q] < ext - 0.786 * amp:
                break
            if (not bull) and H[q] > ext + 0.786 * amp:
                break
        if entry_i is None:
            continue
        entry = float(np.clip(z_hi if bull else z_lo, min(L[entry_i], z_lo), max(H[entry_i], z_hi)))
        entry = z_hi if bull else z_lo          # лимит в зоне (консервативно — верх зоны)
        sl = origin * (1 - 0.002) if bull else origin * (1 + 0.002)   # СТОП ЗА СТРУКТУРУ
        if (bull and sl >= entry) or ((not bull) and sl <= entry):
            continue
        tp = ext + TP_EXT * amp if bull else ext - TP_EXT * amp       # ЦЕЛЬ −1
        out.append(dict(i=entry_i, d=1 if bull else -1, entry=entry, sl=sl, tp=tp,
                        origin=origin, ext=ext, amp=amp, kind=str(ev.kind)))
    return out


def run(H, L, C, pos, e, d, sl, tp, hold=HOLD):
    lo, hi = L[pos:pos + hold], H[pos:pos + hold]
    if len(lo) == 0:
        return None
    hs = (lo <= sl) if d > 0 else (hi >= sl)
    ht = (hi >= tp) if d > 0 else (lo <= tp)
    i_s = int(np.argmax(hs)) if hs.any() else 10 ** 9
    i_t = int(np.argmax(ht)) if ht.any() else 10 ** 9
    if i_s == 10 ** 9 and i_t == 10 ** 9:
        return (float(C[min(pos + hold, len(C) - 1)]) - e) / e * 100.0 * d
    return (sl - e) / e * 100.0 * d if i_s <= i_t else (tp - e) / e * 100.0 * d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=40)
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--cost", type=float, default=COST)
    ap.add_argument("--internal", action="store_true", help="сломы микроструктуры вместо swing")
    ap.add_argument("--max-stop", type=float, default=20.0)
    a = ap.parse_args()

    syms = core_universe(a.tf, n=a.symbols)
    print(f"МЕТОД ЕГОРА · {len(syms)} монет · {a.tf} · сломы "
          f"{'internal len=5' if a.internal else 'swing len=50'}")
    print(f"фибо на импульс-сломщик · вход {FIB_IN[0]}-{FIB_IN[1]} · стоп за структуру · "
          f"цель −{TP_EXT:.0f} · держим {HOLD} баров · косты {a.cost}%\n")

    rng = np.random.default_rng(61)
    rows = []
    t0 = time.time()
    for k, sym in enumerate(syms, 1):
        try:
            df = load(sym, a.tf)
        except Exception:                                   # noqa: BLE001
            continue
        if df is None or len(df) < 4000:
            continue
        flat = float(((df.open == df.high) & (df.high == df.low) & (df.low == df.close)).mean())
        if flat > 0.10:
            continue
        try:
            S = setups(df, internal=a.internal)
        except Exception as e:                              # noqa: BLE001
            print(f"  ⚠ {sym}: {type(e).__name__}: {str(e)[:50]}")
            continue
        # ДИВЕРГЕНЦИЯ — Егор назвал её первой («две белые линии = дивергенция»).
        # Берём ПРИЧИННЫЕ флаги из матрицы (reuse, не свой детектор).
        DIVB = DIVS = None
        try:
            from core.calculators.combinator_core import compute_flags
            FL = compute_flags(df, a.tf, include_pivots=False)
            import numpy as _np
            def _any(cols):
                got = [FL[c].astype(bool).values for c in cols if c in FL.columns]
                return _np.logical_or.reduce(got) if got else _np.zeros(len(df), dtype=bool)
            tf = a.tf
            DIVB = _any([f"wt_div_bull_regular_{tf}", f"wt_div_bull_hidden_{tf}",
                         f"rsi_div_bull_regular_{tf}", f"rsi_div_bull_hidden_{tf}"])
            DIVS = _any([f"wt_div_bear_regular_{tf}", f"wt_div_bear_hidden_{tf}",
                         f"rsi_div_bear_regular_{tf}", f"rsi_div_bear_hidden_{tf}"])
        except Exception:                                   # noqa: BLE001
            pass
        H, L, C = df.high.values, df.low.values, df.close.values
        years = df.index.year.values
        oos = int(hashlib.md5(sym.encode()).hexdigest(), 16) % 2 == 1
        for s in S:
            sp = abs(s["entry"] - s["sl"]) / s["entry"] * 100.0
            if not (0.15 <= sp <= a.max_stop):
                continue
            r = run(H, L, C, s["i"], s["entry"], s["d"], s["sl"], s["tp"])
            if r is None:
                continue
            rr = abs(s["tp"] - s["entry"]) / abs(s["entry"] - s["sl"])
            # была ли дивергенция нужной стороны в окне 20 баров ДО входа
            _dv = 0
            if DIVB is not None:
                w0 = max(0, s["i"] - 20)
                arr = DIVB if s["d"] > 0 else DIVS
                _dv = int(bool(arr[w0:s["i"] + 1].any()))
            rows.append((sym, oos, int(years[s["i"]]), "LONG" if s["d"] > 0 else "SHORT",
                         s["kind"], sp, rr, r - a.cost, 0, _dv))
            # контроль: случайный бар, та же сторона, тот же стоп и то же RR
            q = int(rng.integers(300, len(C) - HOLD - 1))
            ec = float(C[q])
            slc = ec * (1 - s["d"] * sp / 100.0)
            tpc = ec * (1 + s["d"] * sp * rr / 100.0)
            rc = run(H, L, C, q, ec, s["d"], slc, tpc)
            if rc is not None:
                rows.append((sym, oos, int(years[q]), "LONG" if s["d"] > 0 else "SHORT",
                             s["kind"], sp, rr, rc - a.cost, 1, _dv))
        if k % 5 == 0:
            print(f"  ... {k}/{len(syms)} · строк {len(rows):,} · {time.time()-t0:.0f}с", flush=True)

    if not rows:
        print("🔴 сетапов нет")
        return 1
    R = pd.DataFrame(rows, columns=["sym", "oos", "year", "dir", "kind", "sp", "rr", "r",
                                    "ctrl", "div"])
    R.to_parquet(ROOT / "cache" / "egor_method.parquet")
    S_, K_ = R[R.ctrl == 0], R[R.ctrl == 1]
    print(f"\nсетапов {len(S_):,} · монет {S_.sym.nunique()} · {S_.year.min()}-{S_.year.max()} · "
          f"медиана RR {S_.rr.median():.2f} · медиана стопа {S_.sp.median():.2f}%\n")

    def st(x, nm, ind="   "):
        if len(x) < 40:
            print(f"{ind}{nm:26s} n={len(x)} — мало")
            return
        v = np.sort(x.r.values)
        cut = v[:max(1, int(len(v) * 0.9))]
        print(f"{ind}{nm:26s} n={len(x):>6,} медиана={np.median(v):>+7.3f}% среднее={v.mean():>+7.3f}% "
              f"WR={100*(v>0).mean():>4.1f}% безтоп10%={cut.mean():>+7.3f}% монет={x.sym.nunique():>3}")

    print("=" * 118)
    print("МЕТОД ПРОТИВ КОНТРОЛЯ")
    print("=" * 118)
    st(S_, "СИГНАЛ (все)")
    st(K_, "контроль (случайный)")
    print()
    for d in ("LONG", "SHORT"):
        st(S_[S_.dir == d], f"СИГНАЛ {d}")
        st(K_[K_.dir == d], f"контроль {d}")
    print()
    print("ПО ТИПУ СЛОМА:")
    for kd in S_.kind.unique():
        st(S_[S_.kind == kd], f"слом {kd}")
    print()
    print("ПО ГОДАМ:")
    for y in sorted(S_.year.unique()):
        st(S_[S_.year == y], f"год {y}")
    print()
    print("СЛЕПАЯ ПРОВЕРКА:")
    st(S_[~S_.oos], "IS (половина монет)")
    st(S_[S_.oos], "OOS (другая половина)")
    st(K_[K_.oos], "OOS контроль")
    print()
    print("🔑 ДИВЕРГЕНЦИЯ КАК ПОДТВЕРЖДЕНИЕ (окно 20 баров до входа):")
    st(S_[S_["div"] == 1], "СИГНАЛ + дивергенция")
    st(S_[S_["div"] == 0], "СИГНАЛ без дивергенции")
    st(K_[K_["div"] == 1], "контроль (те же сетапы)")
    for d in ("LONG", "SHORT"):
        st(S_[(S_["div"] == 1) & (S_.dir == d)], f"+ дивергенция {d}")
    print()
    print("ПО РАЗМЕРУ СТОПА:")
    for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 8), (8, 100)):
        st(S_[(S_.sp >= lo) & (S_.sp < hi)], f"стоп {lo}-{hi}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
