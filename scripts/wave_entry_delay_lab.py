# -*- coding: utf-8 -*-
"""СТОИМОСТЬ ОПОЗДАНИЯ ВХОДА В ЯДРО ВОЛН (Егор 07.10: «замер»).

Повод. Тень волн замечает сигнал с задержкой: «событие → очередь» медиана 24 мин,
p90 44.6, максимум 58.7, а исполнение (`waves_long_loop.MAX_AGE_MIN = 45`) отсекает всё
старше 45 мин — 1 из 6 записей уже потерян. Вопрос, решающий, надо ли это чинить
(и чем — частым опросом или событийной сетью): **сколько стоит опоздание в деньгах?**

Как меряем. Боевой код без переписывания:
  · детектор — `core.waves.mark_impulse` на каждом ЗАКРЫТОМ 4h-баре (как полный скан тени);
  · вход — `core.waves.ltf_status`: триггер (первый кросс WT / закрытие за линией 2-4) на 15m,
    вход по open следующего бара, стоп за пятой (известной к бару триггера), цель — конец волны 4,
    удержание 240 ч.
Потом на ОДНИХ И ТЕХ ЖЕ сетапах вход сдвигается на d баров 15m (0/15/30/45/60/120 мин), стоп
и цель — те же. Если к моменту опоздавшего входа цена уже за стопом или за целью — сделка
ПРОПУЩЕНА (так её отбил бы и бой: `waves_long_loop` проверяет «цель/стоп не с той стороны»).

Срезы: вся база · КЛЕТКА лонга (полное ядро ∧ стоп ≥6% цены) · коридор (стоп 30-50% импульса) ·
триггер (cross / line24) · сторона.

Запуск:  python scripts/wave_entry_delay_lab.py run [монет] [процессов]
         python scripts/wave_entry_delay_lab.py report
"""
from __future__ import annotations

import os
import pickle
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

OUT = Path("G:/oko_lab/out/wave_entry_delay")
DELAYS = (0, 1, 2, 3, 4, 8)          # баров 15m → 0 / 15 / 30 / 45 / 60 / 120 мин
HOLD_H = 240
COST = 0.35                           # линейка коста — та же, что во всех замерах сессии
WARMUP = 400
ROWS = os.environ.get("DELAY_ROWS", "rows.pkl")   # отдельный файл на прогон — не затирать прежний


def _walk(hi, lo, cl, lt, k0, side, e, sl, tp):
    """Исход от входа на баре k0: стоп раньше цели на одном баре, выход по времени HOLD_H."""
    long_ = side == "LONG"
    end_t = lt[k0] + np.timedelta64(HOLD_H * 60, "m")
    for k in range(k0, len(lt)):
        if (lo[k] <= sl) if long_ else (hi[k] >= sl):
            px = sl; break
        if (hi[k] >= tp) if long_ else (lo[k] <= tp):
            px = tp; break
        if lt[k] >= end_t:
            px = float(cl[k]); break
    else:
        px = float(cl[-1])
    return ((px - e) / e * 100.0) * (1 if long_ else -1) - COST


def run_symbol(sym: str) -> list[dict]:
    from research_harness import load
    from core.waves import mark_impulse, ltf_status, WaveParams
    P = WaveParams(sw=15, il=4, z=45.0, min_imp=3.0, max_imp=100.0, ctx_sw=10,
                   buf=0.0015, merge=False)                # боевые параметры тени (wave5_shadow.P)
    try:
        dh, dl = load(sym, "4h"), load(sym, "15m")
    except Exception:                                    # noqa: BLE001
        return []
    if dh is None or dl is None or len(dh) < WARMUP + 50 or len(dl) < 500:
        return []
    lt = dl.index.values.astype("datetime64[ns]")
    if dl.index.tz is not None:
        lt = dl.index.tz_convert(None).values.astype("datetime64[ns]")
    op, hi, lo, cl = (dl[c].values.astype(float) for c in ("open", "high", "low", "close"))
    seen, out = set(), []
    for t in range(WARMUP, len(dh)):
        now = dh.index[t] + pd.Timedelta("4h")            # момент ЗАКРЫТИЯ бара t — как NOW тени
        try:
            # окно 1000 баров 4h — ровно как тень (`fetch(ex, bx, "4h", 1000)`): и паритет с боем,
            # и линейное время вместо квадратичного
            setups = mark_impulse(dh.iloc[max(0, t - 999):t + 1], now, P, "4h")
        except Exception:                                # noqa: BLE001
            continue
        for st in setups:
            k = (st.get("key"), str(st.get("top_time")))
            if k in seen:
                continue
            seen.add(k)
            # окно 15m вокруг сетапа: 600 баров разогрева WT до вершины пятой + окно входа 96 ч
            # + удержание + запас. Весь ряд не нужен, а WT на 150 тыс. баров на каждый сетап — дорого
            tt = pd.Timestamp(st["top_time"])
            tt = tt.tz_convert(None) if tt.tzinfo else tt
            i_t = int(np.searchsorted(lt, np.datetime64(tt.to_datetime64())))
            i_e = int(np.searchsorted(lt, np.datetime64((tt + pd.Timedelta(hours=96 + HOLD_H + 24)).to_datetime64())))
            dsl = dl.iloc[max(0, i_t - 600):i_e]
            try:
                ls = ltf_status(st, dsl, P, after=now, entry_w_h=96.0, hold_h=float(HOLD_H))
            except Exception:                            # noqa: BLE001
                continue
            if ls.get("entry_time") is None:
                continue
            et = pd.Timestamp(ls["entry_time"])
            et = et.tz_convert(None) if et.tzinfo else et
            j1 = int(np.searchsorted(lt, np.datetime64(et.to_datetime64())))
            if j1 >= len(lt):
                continue
            side, sl, tp = st["side"], float(ls["stop"]), float(st["p4_target"])
            e0 = float(op[j1])
            stop_pct = abs(e0 - sl) / e0 * 100.0
            imp = float(st.get("imp_pct") or np.nan)
            rec = dict(sym=sym, side=side, top_time=str(st.get("top_time"))[:16],
                       entry_time=str(et)[:16], trigger=ls.get("trigger"),
                       core_full=bool(st.get("core_full")), core=bool(st.get("core")),
                       # 07.10: составные части ядра ПО ОТДЕЛЬНОСТИ — чтобы собрать клетку шорта
                       # «ядро БЕЗ порога глубины» (fractal ∧ altern ∧ count_ok), которая записана
                       # живой, а не core_full (с depth5 ≥ 0.5), которую 06.10 ошибочно взяли в бой
                       fractal=bool(st.get("fractal")), altern_type=bool(st.get("altern_type")),
                       altern_form=bool(st.get("altern_form")), count_ok=bool(st.get("count_ok")),
                       depth5=float(st.get("depth5")) if st.get("depth5") is not None else np.nan,
                       stop_pct=round(stop_pct, 3), imp_pct=imp,
                       stop_rel=(stop_pct / imp) if imp and imp == imp and imp > 0 else np.nan)
            for d in DELAYS:
                k0 = j1 + d
                if k0 >= len(lt):
                    rec[f"pnl_{d}"] = np.nan
                    rec[f"skip_{d}"] = True
                    continue
                e = float(op[k0])
                bad = (not (sl < e < tp)) if side == "LONG" else (not (tp < e < sl))
                # 🔴 если цена уже прошла стоп ИЛИ цель до опоздавшего входа — сделки нет
                passed = (lo[j1:k0].min() <= sl or hi[j1:k0].max() >= tp) if (side == "LONG" and d) else \
                         (hi[j1:k0].max() >= sl or lo[j1:k0].min() <= tp) if d else False
                if bad or passed:
                    rec[f"pnl_{d}"] = np.nan
                    rec[f"skip_{d}"] = True
                else:
                    rec[f"pnl_{d}"] = _walk(hi, lo, cl, lt, k0, side, e, sl, tp)
                    rec[f"skip_{d}"] = False
            out.append(rec)
    return out


def run(n_coins: int, procs: int) -> None:
    from research_harness import universe
    OUT.mkdir(parents=True, exist_ok=True)
    syms = universe("4h", n=n_coins)
    print(f"монет {len(syms)} · процессов {procs} · задержки {[d * 15 for d in DELAYS]} мин", flush=True)
    t0, rows = time.time(), []
    with Pool(procs) as pool:
        for i, r in enumerate(pool.imap_unordered(run_symbol, syms), 1):
            rows += r
            if i % 10 == 0:
                print(f"  ... {i}/{len(syms)} монет · сетапов с входом {len(rows)} · "
                      f"{time.time() - t0:.0f} с", flush=True)
    pickle.dump(rows, open(OUT / ROWS, "wb"))
    print(f"готово: {len(rows)} сетапов · {time.time() - t0:.0f} с", flush=True)


def report() -> None:
    R = pd.DataFrame(pickle.load(open(OUT / ROWS, "rb")))
    R["year"] = pd.to_datetime(R.entry_time).dt.year
    print(f"сетапов с входом: {len(R)} · монет {R.sym.nunique()} · годы {sorted(R.year.unique())}")
    cell = R.core_full & (R.stop_pct >= 6.0)
    corr = (R.stop_rel >= 0.30) & (R.stop_rel < 0.50)

    def block(nm, S):
        if len(S) < 25:
            print(f"\n{nm}: мало ({len(S)})")
            return
        print(f"\n{'=' * 98}\n{nm} · n={len(S)}\n{'=' * 98}")
        print(f"  {'опоздание':<11}{'вошли':>7}{'пропущено':>11}{'WR':>7}{'PF':>7}{'средн':>8}"
              f"{'медиана':>9}{'безтоп10%':>10}{'Δ к 0 мин (те же)':>20}")
        base = S["pnl_0"]
        for d in DELAYS:
            v = S[f"pnl_{d}"].dropna()
            if len(v) < 15:
                continue
            pos, neg = v[v > 0].sum(), -v[v < 0].sum()
            frail = float(np.sort(v.values)[:max(1, int(len(v) * 0.9))].sum())
            # НА ОДНИХ И ТЕХ ЖЕ сделках; при d=0 сравнивать столбец сам с собой нельзя
            # (двойное имя колонки даёт DataFrame вместо Series)
            if d == 0:
                dd = 0.0
            else:
                both = S[[f"pnl_{d}", "pnl_0"]].dropna()
                dd = float((both[f"pnl_{d}"] - both["pnl_0"]).mean()) if len(both) else np.nan
            print(f"  {d * 15:>4} мин   {len(v):>7}{S[f'skip_{d}'].mean() * 100:>10.0f}%"
                  f"{(v > 0).mean() * 100:>6.1f}%{pos / neg if neg > 0 else 9.99:>7.2f}"
                  f"{v.mean():>+8.3f}{v.median():>+9.3f}{frail:>+10.0f}{dd:>+20.3f}")
        _ = base

    block("ВСЯ БАЗА (обе стороны)", R)
    block("LONG", R[R.side == "LONG"])
    block("SHORT", R[R.side == "SHORT"])
    block("🔑 КЛЕТКА LONG: полное ядро ∧ стоп ≥6%", R[cell & (R.side == "LONG")])
    block("КЛЕТКА SHORT: полное ядро ∧ стоп ≥6%", R[cell & (R.side == "SHORT")])
    block("КОРИДОР LONG: стоп 30-50% импульса", R[corr & (R.side == "LONG")])
    for tr in ("cross", "line24"):
        block(f"триггер {tr} · LONG", R[(R.trigger == tr) & (R.side == "LONG")])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "run":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 120
        p = int(sys.argv[3]) if len(sys.argv) > 3 else max(1, (os.cpu_count() or 2) - 2)
        run(n, p)
    report()
