#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""СЛОЙ-2 МАТРИЦЫ OTE: вложенные зоны младших + ПОРЯДОК событий в зоне.

Задача Егора 06.10: «схема v4 + пивоты + WT — ищем SMC в зонах интереса, а не в
воздухе» и «мы уже строили эти системы ранее, ищи инфу». Нашлось: скелет матрицы
(`core/smc/ote_matrix.py`) построен 02.07 и живёт в бою, а конфлюэнция к зонам
НЕ подключена — записано как «следующий большой шаг» ([[mtf_confluence_matrix_vision]]).

🔴 ЧТО ОБНАРУЖЕНО ПО ДОРОГЕ. `coherent_structure` отдаёт младшим ТФ ногу старшего
ЦЕЛИКОМ, а их собственную структуру кладёт в `own` с пометкой «для entry-timing
(СЛОЙ-2)». Но `ote_matrix` поле `own` не читает — строит зону из унаследованной ноги.
Замер на 14 символах: зоны 4h, 1h и 15m совпадают у **100%**. Докстринг обещает
«OTE младших ВЛОЖЕНЫ в OTE старшего», фактически они ему РАВНЫ. Слой-2 не построен.

Здесь он строится в research-слое (боевой код не трогаем, пока не измерено):
  ZONE_HTF   — зона старшего из его ноги (как сейчас)
  ZONE_LTF   — зона младшего из ЕГО СОБСТВЕННОЙ ноги (`own`)
  NESTED     — зона младшего ВНУТРИ зоны старшего = конфлюэнция масштабов

🔑 И главное, что уже измерено 02–03.07 и что я сегодня чуть не переоткрыл заново:
    CHoCH младший      mean +0.462%   ← единственный явный эдж
    FVG                      +0.012%  ← ничего
    CHoCH И FVG вместе       −0.668%  ← пере-фильтр ВРЕДИТ
    FVG → CHoCH по ПОРЯДКУ   медиана +0.581 против −0.226 у совпадения
Поэтому считаем не СУММУ признаков, а ПОСЛЕДОВАТЕЛЬНОСТЬ событий в зоне.

Запуск:
    python scripts/ote_matrix_layer2.py --tf-htf 4h --tf-ltf 15m --coins 40
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                    # noqa: BLE001
    pass

from core.smc.ote_matrix import coherent_structure, _atr          # noqa: E402
from core.smc.smc_engine import build_ote, detect_structure_breaks, detect_fvg  # noqa: E402
from research_harness import load, core_universe, universe        # noqa: E402

COST = 0.35          # LIMIT, как в остальных замерах
TTL = 48             # баров держим
WIN = 6              # окно поиска триггера после тэга зоны


def zones_from(struct_entry) -> dict | None:
    """OTE-зона из ноги (экстремум → слом). None, если ноги нет."""
    if not struct_entry:
        return None
    trend, brk, ext = (struct_entry.get("trend"), struct_entry.get("break_level"),
                       struct_entry.get("extreme"))
    if not trend or brk is None or ext is None:
        return None
    ob = build_ote(ext, brk)
    lo, hi = ob["ote"]
    return {"direction": trend, "lo": lo, "hi": hi, "sl": brk,
            "t062": ob["levels"].get(-0.62)}


def ltf_events(d: pd.DataFrame) -> dict:
    """Причинные события младшего ТФ: индексы баров, на которых они СТАЛИ ИЗВЕСТНЫ.

    🔴 Лаг детектора — часть признака: `detect_structure_breaks` даёт событие на баре
    подтверждения, `detect_fvg` — поле f[4] (бар обнаружения), а НЕ f[0] (левый край
    бокса, i−2). Путаница f[0]/f[4] давала WR 96% против честных 44% — это записано
    в контрактах детекторов.
    """
    ev = {"choch_bull": set(), "choch_bear": set(),
          "brk_bull": set(), "brk_bear": set(),
          "fvg_bull": set(), "fvg_bear": set()}
    # 🔴 Контракты детекторов проверены прогоном, а не угаданы (первая версия угадала
    # и дала НОЛЬ событий молча):
    #   StructureBreak(ts, idx, price, kind, direction, has_volume, from_idx)
    #       kind = 'BOS' | 'CHoCH'   направление — в ОТДЕЛЬНОМ поле `direction`
    #   detect_fvg → кортеж (ts, top, bottom, 'bull'|'bear', ts_обнаружения, ts_конца)
    #       f[4] — ВРЕМЯ обнаружения, НЕ индекс бара; переводим через индекс ряда.
    pos = {ts: k for k, ts in enumerate(d.index)}
    try:
        for b in detect_structure_breaks(d, length=5):
            i = int(getattr(b, "idx", -1))
            if i < 0:
                continue
            bull = str(getattr(b, "direction", "")).lower().startswith("bull")
            ev["brk_bull" if bull else "brk_bear"].add(i)
            if "choch" in str(getattr(b, "kind", "")).lower():
                ev["choch_bull" if bull else "choch_bear"].add(i)
    except Exception as e:                           # noqa: BLE001
        print(f"    detect_structure_breaks: {type(e).__name__}: {str(e)[:60]}")
    try:
        for f in detect_fvg(d):
            if len(f) < 5 or f[4] is None:
                continue
            i = pos.get(f[4])                        # ts обнаружения → номер бара
            if i is None:
                continue
            ev["fvg_bull" if str(f[3]).lower().startswith(("bull", "up")) else "fvg_bear"].add(i)
    except Exception as e:                           # noqa: BLE001
        print(f"    detect_fvg: {type(e).__name__}: {str(e)[:60]}")
    return ev


def _near(idxs, i, win=WIN) -> bool:
    return any((i - win) <= x <= i for x in idxs)


def _order(first, second, i, win=WIN) -> bool:
    """ПОРЯДОК: событие `first` случилось РАНЬШЕ `second`, оба в окне."""
    a = [x for x in first if (i - win) <= x <= i]
    b = [x for x in second if (i - win) <= x <= i]
    return any(x < y for x in a for y in b)


def resolve(H, L, C, j, side, entry, sl, tp, ttl=TTL) -> float:
    end = min(j + ttl, len(C) - 1)
    for k in range(j, end + 1):
        if side == "long":
            if L[k] <= sl:
                return (sl - entry) / entry * 100
            if H[k] >= tp:
                return (tp - entry) / entry * 100
        else:
            if H[k] >= sl:
                return (entry - sl) / entry * 100
            if L[k] <= tp:
                return (entry - tp) / entry * 100
    return ((C[end] - entry) if side == "long" else (entry - C[end])) / entry * 100


def run_symbol(sym: str, tf_htf: str, tf_ltf: str) -> list[dict]:
    """Сделки по одному символу: тэг зоны + триггеры (одиночные и ПО ПОРЯДКУ)."""
    dh, dl = load(sym, tf_htf), load(sym, tf_ltf)
    if dh is None or dl is None or len(dh) < 400 or len(dl) < 2000:
        return []
    # структура считается ОДИН раз на всей истории — это даёт ноги; причинность
    # обеспечивается тем, что сделка открывается на баре ПОСЛЕ события (см. ниже).
    st = coherent_structure({tf_htf: dh, tf_ltf: dl})
    z_htf = zones_from(st.get(tf_htf))
    z_own = zones_from((st.get(tf_ltf) or {}).get("own"))
    if not z_htf:
        return []
    ev = ltf_events(dl)
    H, L, C = dl.high.values, dl.low.values, dl.close.values
    n = len(dl)
    side = "long" if z_htf["direction"] == "long" else "short"
    d = "bull" if side == "long" else "bear"

    # Вложенность = зоны ПЕРЕСЕКАЮТСЯ и смотрят в одну сторону. Строгое «внутри»
    # не годится: слом младшего почти совпадает со старшим (0.000972 против 0.0009727
    # на замере), и зона чуть шире границ старшей — формально «не внутри», по смыслу
    # та же область. Доля пересечения важнее факта вложения.
    nested = False
    overlap = 0.0
    if z_own and z_own["direction"] == z_htf["direction"]:
        lo = max(z_htf["lo"], z_own["lo"])
        hi = min(z_htf["hi"], z_own["hi"])
        w = z_htf["hi"] - z_htf["lo"]
        overlap = max(0.0, hi - lo) / w if w > 0 else 0.0
        nested = overlap > 0.5                       # больше половины старшей зоны

    out = []
    in_zone_prev = False
    for i in range(50, n - TTL - 2):
        px = C[i]
        in_zone = z_htf["lo"] <= px <= z_htf["hi"]
        tag = in_zone and not in_zone_prev            # СВЕЖИЙ тэг зоны
        in_zone_prev = in_zone
        if not tag:
            continue
        entry, sl = px, z_htf["sl"]
        risk = abs(entry - sl)
        if risk <= 0 or risk / entry * 100 > 25:
            continue
        tp = entry + risk if side == "long" else entry - risk    # TP = 1R, как в эталоне
        pnl = resolve(H, L, C, i, side, entry, sl, tp) - COST
        row = dict(sym=sym, i=i, side=side, pnl=pnl,
                   stop_pct=risk / entry * 100,
                   year=int(dl.index[i].year),
                   T0_base=1,
                   T1_choch=int(_near(ev[f"choch_{d}"], i)),
                   T3_fvg=int(_near(ev[f"fvg_{d}"], i)),
                   T5_choch_and_fvg=int(_near(ev[f"choch_{d}"], i) and _near(ev[f"fvg_{d}"], i)),
                   T6_fvg_then_choch=int(_order(ev[f"fvg_{d}"], ev[f"choch_{d}"], i)),
                   T7_choch_then_fvg=int(_order(ev[f"choch_{d}"], ev[f"fvg_{d}"], i)),
                   NESTED=int(nested),
                   ZONE_SAME=int(bool(z_own) and abs(z_own["lo"] - z_htf["lo"]) < 1e-12),
                   OVERLAP=round(overlap, 3))
        out.append(row)
    return out


def stat(v: pd.DataFrame) -> dict | None:
    if len(v) < 25:
        return None
    p = v["pnl"].values
    pos, neg = p[p > 0].sum(), -p[p < 0].sum()
    return dict(n=len(p), wr=(p > 0).mean() * 100, pf=pos / neg if neg > 0 else 9.99,
                mean=p.mean(), med=np.median(p), total=p.sum(),
                frail=np.sort(p)[:max(1, int(len(p) * 0.9))].sum(),
                cov=(v.groupby("sym")["pnl"].sum() > 0).mean() * 100)


def show(nm: str, s: dict | None, base: dict | None = None):
    if s is None:
        print(f"  {nm:<26} — мало сделок")
        return
    flow = f"{s['n'] / base['n'] * 100:>5.0f}%" if base else "  база"
    print(f"  {nm:<26}{flow}{s['n']:>6}{s['wr']:>7.1f}%{s['pf']:>7.2f}"
          f"{s['mean']:>+8.3f}{s['med']:>+8.3f}{s['total']:>+9.0f}"
          f"{s['frail']:>+10.0f}{s['cov']:>7.0f}%")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf-htf", default="4h")
    ap.add_argument("--tf-ltf", default="15m")
    ap.add_argument("--coins", type=int, default=40)
    ap.add_argument("--core", action="store_true")
    a = ap.parse_args()

    syms = (core_universe(a.tf_htf, n=a.coins) if a.core
            else universe(a.tf_htf, n=a.coins))
    print(f"СЛОЙ-2 МАТРИЦЫ: зона {a.tf_htf} · триггеры {a.tf_ltf} · TP 1R · TTL {TTL} · "
          f"косты {COST}% · монет {len(syms)}")
    print("Считаем ПОРЯДОК событий, а не их сумму (02.07: совпадение вредит, порядок работает)\n")

    rows = []
    for k, s in enumerate(syms, 1):
        try:
            rows += run_symbol(s, a.tf_htf, a.tf_ltf)
        except Exception as e:                       # noqa: BLE001
            print(f"  [{s}] {type(e).__name__}: {str(e)[:60]}")
        if k % 10 == 0:
            print(f"  ... {k}/{len(syms)} · сделок {len(rows)}", flush=True)
    if not rows:
        print("🔴 НОЛЬ сделок — это отказ, а не вывод.")
        return 1
    R = pd.DataFrame(rows)
    print(f"\nсобрано: {len(R)} сделок · {R.sym.nunique()} монет · "
          f"годы {sorted(R.year.unique())}")
    print(f"ВЛОЖЕННОСТЬ: зона младшего внутри старшей у {R.NESTED.mean()*100:.0f}% · "
          f"зоны СОВПАДАЮТ (слой-2 не работает) у {R.ZONE_SAME.mean()*100:.0f}%")

    base = stat(R)
    print(f"\n{'триггер':<26}{'поток':>6}{'n':>6}{'WR':>8}{'PF':>7}"
          f"{'средн':>8}{'медиана':>8}{'сумма':>9}{'безтоп10%':>10}{'монет+':>7}")
    show("T0 база (сырой тэг)", base)
    for t in ("T1_choch", "T3_fvg", "T5_choch_and_fvg",
              "T6_fvg_then_choch", "T7_choch_then_fvg"):
        show(t, stat(R[R[t] > 0]), base)

    print("\nПО СТОРОНАМ:")
    for side in ("long", "short"):
        S = R[R.side == side]
        b = stat(S)
        if b is None:
            continue
        print(f"  ── {side} ──")
        show("база", b)
        for t in ("T1_choch", "T6_fvg_then_choch"):
            show(t, stat(S[S[t] > 0]), b)

    print("\nПО ГОДАМ (T6 порядок против базы):")
    for y, g in R.groupby("year"):
        b, w = stat(g), stat(g[g.T6_fvg_then_choch > 0])
        if b is None:
            continue
        bs = f"PF {b['pf']:.2f} сум {b['total']:+.0f}"
        ws = f"PF {w['pf']:.2f} сум {w['total']:+.0f}" if w else "мало"
        print(f"  {int(y)}  n={b['n']:>5}  база {bs:<22} | порядок {ws}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
