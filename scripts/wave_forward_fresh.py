# -*- coding: utf-8 -*-
"""ФОРВАРД ЗА ВЕЧЕР: доказанный лонг ядра волн на данных, которых замер НЕ видел.

Егор 07.10: «2-3 недели — долго». Замер, на котором доказана зона лонга
(`scripts/wave_entry_delay_lab.py`), шёл по исследовательскому кэшу, который кончается
22.08.2026. Всё, что после, — данные вне выборки. Хранилище бота (`market_store`)
отдаёт 4h с марта и 15m с 05.08, то есть 23.08 → сегодня можно прогнать ТОТ ЖЕ боевой
сетап: детектор `mark_impulse` (окно 1000 баров 4h, как тень), вход `ltf_status`,
стоп за пятой, цель — конец волны 4, удержание 240 ч, кост 0.35.

⚠️ Это повтор истории, а не живое исполнение: проскальзывание и реальные филлы
он не проверяет — их покажут живые сделки. Сделки, не закрывшиеся к последнему бару,
считаются ОТКРЫТЫМИ по последней цене и выводятся отдельно (иначе выживание:
быстрые стопы закрываются раньше и перекосили бы результат).

Запуск:  python scripts/wave_forward_fresh.py [процессов]
"""
from __future__ import annotations

import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

T0 = pd.Timestamp("2026-08-23", tz="UTC")               # первый день вне выборки замера
HOLD_H, COST, PROVEN = 240, 0.35, 6.0


def _walk(hi, lo, cl, lt, k0, side, e, sl, tp):
    """(pnl, исход). Исход: stop / target / time / open (данные кончились раньше)."""
    long_ = side == "LONG"
    end_t = lt[k0] + np.timedelta64(HOLD_H * 60, "m")
    for k in range(k0, len(lt)):
        if (lo[k] <= sl) if long_ else (hi[k] >= sl):
            px, how = sl, "stop"; break
        if (hi[k] >= tp) if long_ else (lo[k] <= tp):
            px, how = tp, "target"; break
        if lt[k] >= end_t:
            px, how = float(cl[k]), "time"; break
    else:
        px, how = float(cl[-1]), "open"
    return ((px - e) / e * 100.0) * (1 if long_ else -1) - COST, how


def run_symbol(sym: str) -> list[dict]:
    from core.infra.market_store import closed_bars
    from core.waves import mark_impulse, ltf_status, WaveParams
    P = WaveParams(sw=15, il=4, z=45.0, min_imp=3.0, max_imp=100.0, ctx_sw=10,
                   buf=0.0015, merge=False)                 # боевые параметры тени
    try:
        dh, dl = closed_bars(sym, "4h", 1300), closed_bars(sym, "15m", 6000)
    except Exception:                                    # noqa: BLE001
        return []
    if dh is None or dl is None or len(dh) < 450 or len(dl) < 1000:
        return []
    lt = dl.index.tz_convert(None).values.astype("datetime64[ns]")
    op, hi, lo, cl = (dl[c].values.astype(float) for c in ("open", "high", "low", "close"))
    seen, out = set(), []
    for t in range(400, len(dh)):
        now = dh.index[t] + pd.Timedelta("4h")
        if now < T0:
            continue
        try:
            setups = mark_impulse(dh.iloc[max(0, t - 999):t + 1], now, P, "4h")
        except Exception:                                # noqa: BLE001
            continue
        for st in setups:
            key = (st.get("key"), str(st.get("top_time")))
            if key in seen:
                continue
            seen.add(key)
            try:
                ls = ltf_status(st, dl, P, after=now, entry_w_h=96.0, hold_h=float(HOLD_H))
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
            if not ((sl < e0 < tp) if side == "LONG" else (tp < e0 < sl)):
                continue
            pnl, how = _walk(hi, lo, cl, lt, j1, side, e0, sl, tp)
            stop_pct = abs(e0 - sl) / e0 * 100.0
            imp = float(st.get("imp_pct") or np.nan)
            rel = stop_pct / imp if imp and imp == imp and imp > 0 else np.nan
            proven = side == "LONG" and (stop_pct >= PROVEN or (0.30 <= rel < 0.50))
            out.append(dict(sym=sym, side=side, entry_time=str(et)[:16], stop_pct=round(stop_pct, 2),
                            proven=bool(proven), pnl=pnl, how=how))
    return out


def main() -> int:
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else max(1, (os.cpu_count() or 2) - 2)
    import ccxt
    mk = ccxt.bingx().load_markets()
    syms = sorted(s for s, m in mk.items()
                  if m.get("swap") and m.get("quote") == "USDT" and m.get("active"))
    print(f"вне выборки: {T0:%Y-%m-%d} → сейчас · монет {len(syms)} · процессов {procs}", flush=True)
    t0, rows = time.time(), []
    with Pool(procs) as pool:
        for i, r in enumerate(pool.imap_unordered(run_symbol, syms), 1):
            rows += r
            if i % 100 == 0:
                print(f"  ... {i}/{len(syms)} · сделок {len(rows)} · {time.time() - t0:.0f} с", flush=True)
    R = pd.DataFrame(rows)
    R.to_pickle(Path("G:/oko_lab/out/wave_entry_delay") / "forward_fresh.pkl")
    print(f"готово: {len(R)} сделок · {time.time() - t0:.0f} с\n")
    if R.empty:
        print("🔴 сделок нет — отказ, а не вывод")
        return 1

    def block(nm, S):
        C = S[S.how != "open"]
        O = S[S.how == "open"]
        if len(S) == 0:
            print(f"  {nm:<34} — нет сделок"); return
        p = C.pnl.values
        if len(p):
            pos, neg = p[p > 0].sum(), -p[p < 0].sum()
            pf = pos / neg if neg > 0 else float("inf")
            print(f"  {nm:<34}закрыто {len(C):>4} · прибыльных {(p > 0).mean()*100:4.0f}% · PF {pf:5.2f} · "
                  f"в среднем {p.mean():+6.2f}% · медиана {np.median(p):+6.2f}% · сумма {p.sum():+7.1f}%")
        if len(O):
            print(f"  {'':<34}ещё открыто {len(O):>3} · по последней цене в среднем {O.pnl.mean():+6.2f}%")

    print("ДОКАЗАННЫЙ СЕТАП НА ДАННЫХ ВНЕ ВЫБОРКИ (23.08 → сегодня)")
    block("🔑 ЛОНГ в доказанной зоне", R[R.proven])
    block("лонг вне зоны", R[(R.side == "LONG") & ~R.proven])
    block("шорт (все)", R[R.side == "SHORT"])
    print("\nпо неделям входа — лонг в доказанной зоне (закрытые):")
    P_ = R[R.proven & (R.how != "open")].copy()
    if len(P_):
        P_["wk"] = pd.to_datetime(P_.entry_time).dt.strftime("%m-%d")
        P_["wk"] = pd.to_datetime(P_.entry_time).dt.to_period("W").astype(str)
        for w, g in P_.groupby("wk"):
            print(f"  {w}: сделок {len(g):>3} · прибыльных {(g.pnl > 0).mean()*100:4.0f}% · "
                  f"в среднем {g.pnl.mean():+6.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
