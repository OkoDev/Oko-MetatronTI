"""
elliott_canon_remeasure.py — ПЕРЕМЕР НА КАНОНИЧНОЙ РАЗМЕТКЕ (29.08.2026).

Исправление собственной ошибки. 29.08 я классифицировал волны как UP/DOWN/FLAT по
САМОДЕЛЬНОЙ метке — терцилю `leg_speed_atr` — и на ней построил вывод «находки живут
во FLAT» ([[wave_type_flat_modulates_findings]]). При этом в проекте уже был канон:
`detect_elliott_mtf` (масштабы ZigZag 3/5/8, три железных правила, фибо-соотношения,
extension волны 5) и полный справочник `obsidian/Concepts/Elliott-Wave-Labeling.md`.

Егор поймал: «на чём основываясь ты мне выводы давал?». Замеры были верны, но ВЫБОР
того, что мерить, сделан без опоры на существующую разметку. Здесь тот же вопрос
задаётся заново — каноничными метками.

🔴 ПРИЧИННОСТЬ — главная ловушка этого замера. `detect_elliott_impulse` РАСШИРЯЕТ волну 5
вперёд по ряду («тянем точку 5 до последнего low/high»), то есть последняя точка импульса
известна только ПОСЛЕ его завершения. Поэтому импульс засчитывается сделке ТОЛЬКО если
время его последней волны СТРОГО РАНЬШЕ бара входа. Иначе это look-ahead вида 1.

Каноничная замена моей «FLAT»: отсутствие свежего завершённого импульса на всех масштабах
= рынок НЕ в импульсной фазе (коррекция/боковик), что по Эллиотту и есть зона плоскостей
и треугольников.

    python scripts/elliott_canon_remeasure.py --symbols 40
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:      # noqa: BLE001
    pass

from research_harness import load, line, stat        # noqa: E402

PQ = ROOT / "cache" / "matrix_run_15m.parquet"
FRESH_BARS = 96 * 3          # «свежий» импульс — не старше 3 суток на 15m


def canon_marks(sym: str, ts: pd.Series) -> pd.DataFrame:
    """Каноничные волновые метки на моменты сделок. Только ЗАВЕРШЁННЫЕ импульсы."""
    from core.smc.smc_engine import detect_elliott_mtf
    try:
        d = load(sym, "15m")
    except Exception:                       # noqa: BLE001
        return pd.DataFrame()
    if d is None or len(d) < 5000:
        return pd.DataFrame()
    try:
        imps = detect_elliott_mtf(d)
    except Exception:                       # noqa: BLE001
        return pd.DataFrame()
    if not imps:
        return pd.DataFrame()

    rows = []
    for im in imps:
        w = im["waves"]
        t_end = pd.Timestamp(w[-1][0])
        if t_end.tzinfo is None:
            t_end = t_end.tz_localize("UTC")
        p0, p5 = float(w[0][1]), float(w[-1][1])
        rows.append(dict(t_end=t_end, direction=im["direction"], scale=float(im["scale"]),
                         textbook=bool(im["textbook"]), w3_ext=float(im["w3_ext"]),
                         w2_retr=float(im["w2_retr"]), w4_retr=float(im["w4_retr"]),
                         span=abs(p5 - p0), p5=p5))
    E = pd.DataFrame(rows).sort_values("t_end")
    left = pd.DataFrame({"_ts": pd.to_datetime(ts.values, utc=True)}).sort_values("_ts")
    # 🔴 strictly backward: импульс должен ЗАВЕРШИТЬСЯ до бара входа
    E2 = E.copy(); E2["imp_end"] = E2["t_end"]
    j = pd.merge_asof(left, E2.rename(columns={"t_end": "_ts"}), on="_ts",
                      direction="backward", allow_exact_matches=False)
    j["age_h"] = (j["_ts"] - j["imp_end"]).dt.total_seconds() / 3600
    return j.drop(columns=["imp_end"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=40)
    a = ap.parse_args()

    R = pd.read_parquet(PQ)
    R["_ts"] = pd.to_datetime(R.entry_ts, utc=True, errors="coerce")
    R = R[R._ts.notna()].copy()

    parts = []
    for sym, g in R.groupby("sym"):
        g = g.sort_values("_ts")
        M = canon_marks(sym, g._ts)
        if M.empty:
            continue
        M = M.drop(columns=["_ts"]).reset_index(drop=True)
        g = g.reset_index(drop=True)
        parts.append(pd.concat([g, M], axis=1))
    if not parts:
        print("каноничная разметка не построилась ни на одном символе")
        return 1
    R = pd.concat(parts, ignore_index=True)

    # 🔴 ПОПРАВКА К ПЕРВОЙ ВЕРСИИ: «есть завершённый импульс когда-либо в прошлом» —
    # метка-пустышка, она верна для 100% сделок (на трёх масштабах всегда что-то найдётся).
    # Каноничная импульсная ФАЗА = импульс завершился НЕДАВНО; иначе рынок давно в коррекции.
    fresh_h = FRESH_BARS * 0.25          # бары 15m → часы
    has = R.direction.notna() & (R.age_h <= fresh_h)
    print(f"\n🔑 «свежесть» импульса: не старше {fresh_h:.0f} ч "
          f"(медиана возраста {R.age_h.median():.0f} ч)")
    print("=" * 104)
    print("ПЕРЕМЕР НА КАНОНИЧНОЙ РАЗМЕТКЕ ЭЛЛИОТТА (detect_elliott_mtf)")
    print("=" * 104)
    print(f"сделок {len(R)} · с завершённым импульсом до входа: {has.sum()} "
          f"({has.mean()*100:.0f}%) · монет {R.sym.nunique()}")
    print(f"масштабы: " + " · ".join(
        f"{s}: {(R.scale == s).sum()}" for s in sorted(R.scale.dropna().unique())))
    print(f"textbook-импульсов: {R.textbook.fillna(False).mean()*100:.0f}%")

    sp = R.leg_speed_atr_15m
    my_flat = sp <= sp.quantile(1 / 3)                # МОЯ самодельная метка
    churn = R.st5_count20_15m >= 2
    gate = R.mkt_drift_slope > 0

    print("\n" + "=" * 104)
    print("1. СОВПАДАЕТ ЛИ МОЯ «FLAT» С КАНОНОМ (нет завершённого импульса = не импульсная фаза)")
    print("=" * 104)
    canon_flat = ~has
    inter = (my_flat & canon_flat).sum(); union = (my_flat | canon_flat).sum()
    print(f"  моя FLAT {my_flat.mean()*100:.0f}% сделок · каноничная «не импульс» {canon_flat.mean()*100:.0f}%")
    print(f"  Жаккар {inter/union if union else 0:.3f} · "
          f"r = {my_flat.astype(float).corr(canon_flat.astype(float)):+.3f}")
    print("  🔑 низкое совпадение = мои выводы про FLAT были про ДРУГОЕ явление")

    print("\n" + "=" * 104)
    print("2. ТО ЖЕ ИССЛЕДОВАНИЕ, НО КАНОНИЧНЫМИ МЕТКАМИ")
    print("=" * 104)
    groups = {
        "импульс ЕСТЬ (завершён)": has,
        "импульса НЕТ (коррекция)": ~has,
        "impulse textbook": R.textbook.fillna(False),
        "impulse НЕ textbook": has & ~R.textbook.fillna(False),
    }
    for nm, m in groups.items():
        s = stat(R[m])
        if s:
            print(line(R[m], f"  {nm:<26}"))

    print("\n  churn ВНУТРИ каждой каноничной группы:")
    for nm, m in groups.items():
        aa, bb = stat(R[m & churn]), stat(R[m & ~churn])
        if aa and bb and bb["pf"]:
            print(f"    {nm:<26} churn {aa['pf']:5.2f} (n={aa['n']:>4}) против "
                  f"{bb['pf']:5.2f} (n={bb['n']:>4})  ×{aa['pf']/bb['pf']:.2f}")

    print("\n" + "=" * 104)
    print("3. ПО ГОДАМ — держится ли каноничный разрез там, где сыпались мои метки")
    print("=" * 104)
    for nm, m in (("импульс ЕСТЬ", has), ("импульса НЕТ", ~has)):
        row = []
        for y in sorted(R.year.unique()):
            g = R[R.year == y]
            aa, bb = stat(g[m[g.index]]), stat(g[~m[g.index]])
            row.append(f"{y} ×{aa['pf']/bb['pf']:5.2f}" if (aa and bb and bb["pf"]) else f"{y} мало ")
        print(f"  {nm:<16} " + " | ".join(row))

    print("\n" + "=" * 104)
    print("4. ПОВЕРХ БОЕВОГО ГЕЙТА · и НАПРАВЛЕНИЕ ИМПУЛЬСА против СТОРОНЫ")
    print("=" * 104)
    print(line(R[gate], "  гейт"))
    for nm, m in groups.items():
        if stat(R[gate & m]):
            print(line(R[gate & m], f"  гейт + {nm[:24]}"))
    print()
    for dr in ("up", "down"):
        for side in ("long", "short"):
            m = gate & (R.direction == dr) & (R.side == side)
            tag = "ПО импульсу" if ((dr == "up") == (side == "long")) else "ПРОТИВ импульса"
            if stat(R[m]):
                print(line(R[m], f"  гейт + импульс {dr:<5} + {side:<6} ({tag})"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
