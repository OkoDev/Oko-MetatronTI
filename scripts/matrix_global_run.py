"""
matrix_global_run.py — ГЛОБАЛЬНЫЙ ПРОГОН ПО ПОЛНОЙ МАТРИЦЕ (MATRIX-FULL, 28.08.2026).

Что здесь нового против всех прошлых прогонов:
  1. матрица ПОЛНАЯ: `combinator_core` (435 с MTF) + `matrix_full` (фандинг · ширина
     вселенной · непрерывные дистанции до магнитов · состояние осцилляторов);
  2. числовые признаки проверяются ПОРОГАМИ ПО ДЕЦИЛЯМ в обе стороны, а не
     единственной точкой `f > 0` — это ограничение прошлых «0 из 446»;
  3. ПЕРЕСТАНОВОЧНЫЙ КОНТРОЛЬ: тот же перебор по перемешанному pnl показывает,
     сколько «находок» рождает чистый шум.

🔴 ЗАКОН: механика — БОЕВАЯ конфигурация `impulse_fib`, а не удобная для поиска
([[law_reproduce_live_config_first]]). Геометрия взята из живого инстанса:
вход лимитом на 0.382 отката, стоп 2.5·ATR, цель −1.618, три гейта, зона стопа.

    python scripts/matrix_global_run.py                 # 15m, 40 монет
    python scripts/matrix_global_run.py --tf 1h --symbols 60
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:      # noqa: BLE001
    pass

from research_harness import (collect, report, blind_select, blind_select_num,  # noqa: E402
                              feature_cols, stat, line)
from matrix_full import extra_flags, market_context                             # noqa: E402

# Боевая геометрия impulse_fib. 1h — база модуля; 15m — ×4 по барам (та же длительность).
GEOM = {"1h":  dict(wait=12, hold=96,  lo=1.5, hi=3.234),
        "15m": dict(wait=48, hold=384, lo=1.5, hi=3.234),
        # 4h: та же КАЛЕНДАРНАЯ длительность, что 1h (12 ч ожидания, 4 суток удержания).
        # 🔴 константа в БАРАХ между ТФ не переносится — см. twins_15m_stabilized_by_measure
        "4h":  dict(wait=3,  hold=24,  lo=1.5, hi=3.234)}
PEN = 0.15          # лимит ставится глубже на эту долю — как в боевом луте


def make_mechanic(tf: str, sides: set[str]):
    g = GEOM[tf]

    def mechanic(df: pd.DataFrame, _tf: str) -> list[dict]:
        from core.smc.impulse_fib import _atr, find_impulses
        dd = df.reset_index(drop=True)
        H, L, C, V = dd.high.values, dd.low.values, dd.close.values, dd.volume.values
        n = len(dd)
        aa = _atr(dd); atr = aa.values
        rgv = (aa / aa.rolling(100).mean()).values
        ema = dd.close.ewm(span=200, adjust=False).mean().values
        vm = pd.Series(V).rolling(120).mean().values
        out = []
        for a, b, up in find_impulses(H, L, C, atr, n):
            side = "long" if up else "short"
            if side not in sides:
                continue
            if b < 400 or b >= n - g["hold"] - g["wait"] - 2:
                continue
            x_ = float(C[b]); amp = abs(x_ - float(C[a]))
            if amp <= 0 or not vm[b] or vm[b] <= 0:
                continue
            vr = float(V[a:b + 1].sum() / (b - a + 1) / vm[b])
            r_ = float(rgv[b]) if not np.isnan(rgv[b]) else 1.0
            # три боевых гейта: объёмный режим · сторона EMA200 · расширение волатильности
            trend_ok = (C[b] > ema[b]) if up else (C[b] < ema[b])
            if not (1.0 <= vr < 1.5 and trend_ok and r_ >= 1.1):
                continue
            d = 1.0 if up else -1.0
            e = x_ - d * 0.382 * amp
            tp = x_ + d * 1.618 * amp
            sl = e - d * 2.5 * atr[b]
            if (sl >= e) if up else (sl <= e):
                continue
            sp = abs(e - sl) / e * 100
            if not (g["lo"] <= sp <= g["hi"]):
                continue
            deep = e * (1 - d * PEN / 100)
            w = range(b + 1, min(b + 1 + g["wait"], n))
            jf = next((q for q in w if (L[q] <= e if up else H[q] >= e)), None)
            jd = next((q for q in w if (L[q] <= deep if up else H[q] >= deep)), None)
            if jf is None or jd is None:
                continue
            end = min(jf + g["hold"], n - 1)
            fh, fl = H[jf + 1:end + 1], L[jf + 1:end + 1]
            if len(fh) == 0:
                continue
            if up:
                jt = next((k for k in range(len(fh)) if fh[k] >= tp), 10 ** 9)
                js = next((k for k in range(len(fl)) if fl[k] <= sl), 10 ** 9)
            else:
                jt = next((k for k in range(len(fl)) if fl[k] <= tp), 10 ** 9)
                js = next((k for k in range(len(fh)) if fh[k] >= sl), 10 ** 9)
            if js <= jt and js < 10 ** 9:
                r = d * (sl - e) / e * 100
            elif jt < 10 ** 9:
                r = d * (tp - e) / e * 100
            else:
                r = d * (float(C[end]) - e) / e * 100
            # entry_ts нужен для среза КЛАСТЕР (сколько наших сетапов в тот же день).
            # Без него срез посчитать нечем, а подставлять суррогат запрещено —
            # `matrix_run_slices.py` в этом случае честно печатает «НЕ ПРОВЕРЕНО».
            out.append({"entry_bar": jf, "signal_bar": b, "pnl_pct": r, "side": side,
                        "entry_ts": df.index[jf], "stop_pct": sp,
                        "amp_pct": amp / e * 100, "vratio": vr,
                        "regime": r_, "age": b - a})
        return out

    return mechanic


def main() -> int:
    ap = argparse.ArgumentParser(description="Глобальный прогон по ПОЛНОЙ матрице")
    ap.add_argument("--tf", default="15m", choices=["15m", "1h", "4h"])
    ap.add_argument("--symbols", type=int, default=40)
    ap.add_argument("--stop-lo", type=float, default=None,
                    help="нижняя граница зоны стопа, %%. Боевая 1.5. Расширить = снять ВШИТЫЙ гейт")
    ap.add_argument("--stop-hi", type=float, default=None,
                    help="верхняя граница зоны стопа, %%. Боевая 3.234")
    ap.add_argument("--tag", default="", help="суффикс имени выходного файла")
    ap.add_argument("--core", action="store_true",
                    help="БАЛАНСИРОВАННАЯ ПАНЕЛЬ: только монеты с полным покрытием окна. Состав фиксирован → годы сравнимы напрямую, без поправки на состав (15m: 97 монет)")
    ap.add_argument("--sides", default="long,short")
    ap.add_argument("--perm", type=int, default=20, help="перестановок для контроля шума")
    a = ap.parse_args()
    sides = set(s.strip() for s in a.sides.split(",") if s.strip())
    # 🔴 зона стопа — ВШИТЫЙ гейт: она отсеивает сетапы при ГЕНЕРАЦИИ, а не фильтрует
    # готовую выборку. Пока она узкая, в матрице нет контрпримеров и измерить её нельзя.
    if a.stop_lo is not None or a.stop_hi is not None:
        g = GEOM[a.tf]
        old = (g['lo'], g['hi'])
        if a.stop_lo is not None: g['lo'] = a.stop_lo
        if a.stop_hi is not None: g['hi'] = a.stop_hi
        print(f"🔴 ЗОНА СТОПА РАСШИРЕНА: {old[0]}-{old[1]}% → {g['lo']}-{g['hi']}% "
              f"— это СНЯТИЕ вшитого гейта, выборка будет ДРУГОЙ")

    print("=" * 104)
    print(f"ГЛОБАЛЬНЫЙ ПРОГОН · ПОЛНАЯ МАТРИЦА · ТФ {a.tf} · стороны {sorted(sides)}")
    print("=" * 104)
    # 🔴🔴 ПРАВИЛО ЕГОРА (28.08.2026): «стороны обязательно обе, иначе ищем инструменты
    # односторонние, а это неверно». Признак, отобранный только на шорте, — это не
    # признак рынка, а описание текущего режима: он ломается, когда сторона кочует
    # по годам ([[target_by_regime_not_side]] — закон подтверждён трижды).
    # Односторонний прогон допустим только как ПРОВЕРКА уже найденного, не как поиск.
    if sides != {"long", "short"}:
        print("🔴🔴 ВНИМАНИЕ: прогон ОДНОСТОРОННИЙ (%s)." % ", ".join(sorted(sides)))
        print("   Найденное здесь — свойство ЭТОЙ стороны, а не инструмент рынка.")
        print("   Для поиска признаков нужны ОБЕ стороны (правило Егора 28.08).")
        print("   Продолжаю, но вердикт по такому прогону выносить НЕЛЬЗЯ.")
    M = market_context()
    print(f"рыночный контекст: {M.shape[0]} дней × {M.shape[1]} признаков "
          f"({M.index[0].date()} → {M.index[-1].date()})")

    R = collect(make_mechanic(a.tf, sides), tf=a.tf,
                n_symbols=0 if a.core else a.symbols, core=a.core,
                extra=lambda df, tf, sym: extra_flags(df, tf, sym, M=M))

    flags = feature_cols(R)
    from research_harness import _is_binary
    nb = [f for f in flags if not _is_binary(R[f])]
    print(f"\n🧮 ПОЛНАЯ МАТРИЦА В ЭТОМ ПРОГОНЕ: {len(flags)} признаков · "
          f"булевых {len(flags)-len(nb)} · ЧИСЛОВЫХ {len(nb)}")

    report(R)
    print("\n" + "=" * 104)
    print("A. БУЛЕВЫ ПРИЗНАКИ (как раньше: f > 0)")
    print("=" * 104)
    blind_select(R)
    print("\n" + "=" * 104)
    print("B. ЧИСЛОВЫЕ ПРИЗНАКИ (пороги по децилям + контроль шумом) — НОВОЕ")
    print("=" * 104)
    blind_select_num(R, n_perm=a.perm)

    # ядро пишется отдельным файлом — сравнивать с обычным прогоном можно только
    # так, а перезапись затёрла бы базу, на которой стоят прошлые выводы
    base = f"matrix_core_{a.tf}" if a.core else f"matrix_run_{a.tf}"
    out = ROOT / "cache" / f"{base}{a.tag}.parquet"
    try:
        R.to_parquet(out)
        print(f"\nсырые сделки с признаками → {out}")
    except Exception as e:                      # noqa: BLE001
        print(f"\n(не сохранил parquet: {e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
