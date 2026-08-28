"""
poc_impulse_test.py — ГИПОТЕЗА ЕГОРА (28.08.2026): «профиль объёма на импульсе даёт
уровень POC, к которому цена стремится вернуться (там проторгован самый большой объём)».

Прямая проверка против нашего боевого входа. Механика `impulse_fib` уже размечает
импульс от бара `a` до бара `b` — на этом же отрезке строим НАСТОЯЩИЙ профиль
объёма (гистограмма по ценовым корзинам, объём каждого бара размазан по его
диапазону), берём POC и сравниваем ДВА входа с ОДИНАКОВОЙ геометрией стопа и цели:

    ФИБО  — лимит на откате 0.382 от хода (боевой)
    POC   — лимит на уровне максимального проторгованного объёма импульса

🔴 Причинность: профиль считается ТОЛЬКО по барам импульса (a..b). POC известен
в момент завершения импульса, то есть ДО входа. Ни один бар после `b` не участвует.

    python scripts/poc_impulse_test.py --tf 15m --symbols 40
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

from research_harness import universe, load, stat, line     # noqa: E402

GEOM = {"1h": dict(wait=12, hold=96), "15m": dict(wait=48, hold=384)}
COST = 0.35
NBINS = 50


def impulse_poc(H, L, V, a, b, nbins=NBINS):
    """
    Профиль объёма отрезка [a, b] → POC.

    Объём КАЖДОГО бара размазывается равномерно по корзинам, которые накрывает его
    диапазон [low, high] — это ближе к правде, чем «весь объём по цене закрытия»,
    и не требует ленты сделок. Возвращает цену центра самой объёмной корзины.
    """
    lo, hi = float(np.min(L[a:b + 1])), float(np.max(H[a:b + 1]))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return None, None
    edges = np.linspace(lo, hi, nbins + 1)
    prof = np.zeros(nbins)
    for i in range(a, b + 1):
        blo, bhi = L[i], H[i]
        if not np.isfinite(blo) or not np.isfinite(bhi) or bhi < blo:
            continue
        i0 = max(0, min(nbins - 1, int((blo - lo) / (hi - lo) * nbins)))
        i1 = max(0, min(nbins - 1, int((bhi - lo) / (hi - lo) * nbins)))
        k = i1 - i0 + 1
        prof[i0:i1 + 1] += V[i] / k
    j = int(np.argmax(prof))
    poc = (edges[j] + edges[j + 1]) / 2
    conc = prof[j] / prof.sum() * 100 if prof.sum() > 0 else np.nan
    return poc, conc


def run(tf: str, n_symbols: int) -> pd.DataFrame:
    from core.smc.impulse_fib import _atr, find_impulses
    g = GEOM[tf]
    rows = []
    syms = universe(tf, n=n_symbols)
    print(f"вселенная: {len(syms)} монет · ТФ {tf}")
    for i, sym in enumerate(syms, 1):
        df = load(sym, tf)
        if len(df) < 12000:
            continue
        dd = df.reset_index(drop=True)
        H, L, C, V = dd.high.values, dd.low.values, dd.close.values, dd.volume.values
        n = len(dd)
        aa = _atr(dd); atr = aa.values
        rgv = (aa / aa.rolling(100).mean()).values
        ema = dd.close.ewm(span=200, adjust=False).mean().values
        vm = pd.Series(V).rolling(120).mean().values
        for a, b, up in find_impulses(H, L, C, atr, n):
            if b < 400 or b >= n - g["hold"] - g["wait"] - 2:
                continue
            x_ = float(C[b]); amp = abs(x_ - float(C[a]))
            if amp <= 0 or not vm[b] or vm[b] <= 0:
                continue
            vr = float(V[a:b + 1].sum() / (b - a + 1) / vm[b])
            r_ = float(rgv[b]) if not np.isnan(rgv[b]) else 1.0
            trend_ok = (C[b] > ema[b]) if up else (C[b] < ema[b])
            if not (1.0 <= vr < 1.5 and trend_ok and r_ >= 1.1):
                continue
            poc, conc = impulse_poc(H, L, V, a, b)
            if poc is None:
                continue
            d = 1.0 if up else -1.0
            fib = x_ - d * 0.382 * amp
            # глубина POC в долях хода: 0 = у конца импульса, 1 = у начала
            depth = abs(x_ - poc) / amp
            base = dict(sym=sym, year=int(df.index[b].year), side="long" if up else "short",
                        amp_pct=amp / x_ * 100, vratio=vr, regime=r_,
                        poc_depth=depth, poc_conc=conc,
                        poc_vs_fib_pct=(poc - fib) / fib * 100,
                        age=b - a)
            for nm, e in (("fib", fib), ("poc", poc)):
                sl = e - d * 2.5 * atr[b]
                tp = x_ + d * 1.618 * amp
                if (sl >= e) if up else (sl <= e):
                    base[f"{nm}_pnl"] = np.nan; base[f"{nm}_fill"] = 0
                    continue
                sp = abs(e - sl) / e * 100
                w = range(b + 1, min(b + 1 + g["wait"], n))
                jf = next((q for q in w if (L[q] <= e if up else H[q] >= e)), None)
                base[f"{nm}_stop_pct"] = sp
                if jf is None:
                    base[f"{nm}_pnl"] = np.nan; base[f"{nm}_fill"] = 0
                    continue
                base[f"{nm}_fill"] = 1
                end = min(jf + g["hold"], n - 1)
                fh, fl = H[jf + 1:end + 1], L[jf + 1:end + 1]
                if len(fh) == 0:
                    base[f"{nm}_pnl"] = np.nan; continue
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
                base[f"{nm}_pnl"] = r - COST
            rows.append(base)
        if i % 5 == 0:
            print(f"  ... {i}/{len(syms)} · {len(rows)}", flush=True)
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="15m", choices=["15m", "1h"])
    ap.add_argument("--symbols", type=int, default=40)
    a = ap.parse_args()
    R = run(a.tf, a.symbols)
    if R.empty:
        print("🔴 ноль сетапов — это отказ, а не вывод"); return 1
    print(f"\nсетапов: {len(R)} · монет {R.sym.nunique()}")

    print("\n" + "=" * 104)
    print("1. ГДЕ ЛЕЖИТ POC ИМПУЛЬСА ОТНОСИТЕЛЬНО ФИБО-ВХОДА")
    print("=" * 104)
    print(f"  глубина POC в долях хода: медиана {R.poc_depth.median():.3f} · "
          f"p10 {R.poc_depth.quantile(.1):.3f} · p90 {R.poc_depth.quantile(.9):.3f}")
    print(f"  (наш фибо-вход = 0.382; >0.382 значит POC ГЛУБЖЕ, ждать дольше)")
    print(f"  POC глубже фибо: {(R.poc_depth > 0.382).mean()*100:.1f}% случаев")
    print(f"  концентрация объёма в POC-корзине: медиана {R.poc_conc.median():.1f}% (из 50 корзин)")

    print("\n" + "=" * 104)
    print("2. ДОХОДИТ ЛИ ЦЕНА ДО УРОВНЯ (доля филлов в окне ожидания)")
    print("=" * 104)
    print(f"  ФИБО 0.382: {R.fib_fill.mean()*100:5.1f}%")
    print(f"  POC:        {R.poc_fill.mean()*100:5.1f}%")

    print("\n" + "=" * 104)
    print("3. РЕЗУЛЬТАТ ВХОДА — % net с костами, одинаковая геометрия SL/TP")
    print("=" * 104)
    for nm, lbl in (("fib", "ФИБО 0.382 (боевой)"), ("poc", "POC импульса (гипотеза)")):
        v = R[R[f"{nm}_pnl"].notna()].rename(columns={f"{nm}_pnl": "pnl"})
        print(line(v, f"  {lbl}"))
    print("\n  по СТОРОНЕ:")
    for side in ("long", "short"):
        for nm, lbl in (("fib", "фибо"), ("poc", "POC ")):
            v = R[(R.side == side) & R[f"{nm}_pnl"].notna()].rename(columns={f"{nm}_pnl": "pnl"})
            print(line(v, f"    {side} · {lbl}"))
    print("\n  по ГОДУ:")
    for y in sorted(R.year.unique()):
        for nm, lbl in (("fib", "фибо"), ("poc", "POC ")):
            v = R[(R.year == y) & R[f"{nm}_pnl"].notna()].rename(columns={f"{nm}_pnl": "pnl"})
            print(line(v, f"    {y} · {lbl}"))

    print("\n" + "=" * 104)
    print("4. ПАРНОЕ СРАВНЕНИЕ на сетапах, где ЗАЛИЛИСЬ ОБА входа")
    print("=" * 104)
    B = R[(R.fib_fill == 1) & (R.poc_fill == 1) & R.fib_pnl.notna() & R.poc_pnl.notna()]
    print(f"  таких сетапов: {len(B)}")
    if len(B) >= 30:
        d = B.poc_pnl - B.fib_pnl
        print(f"  POC лучше фибо в {(d > 0).mean()*100:.1f}% случаев · "
              f"медиана разницы {d.median():+.3f} п.п. · среднее {d.mean():+.3f} п.п.")
        print(f"  сумма фибо {B.fib_pnl.sum():+.0f}% · сумма POC {B.poc_pnl.sum():+.0f}%")
        print(f"  средний стоп: фибо {B.fib_stop_pct.median():.2f}% · POC {B.poc_stop_pct.median():.2f}%")

    # ── 5. ПЕРЕФОРМУЛИРОВКА (Егор 28.08): POC — не вход, а МАГНИТ ────────────
    # «цена стремится ВЕРНУТЬСЯ к POC». POC глубже нашего фибо-входа в 62% случаев,
    # значит возврат к нему ПРОХОДИТ наш вход насквозь и идёт против позиции.
    # Тогда POC — не альтернативный вход, а ФИЛЬТР РИСКА для боевого входа:
    # чем дальше магнит ЗА входом, тем больше шансов, что цена не остановится.
    print("\n" + "=" * 104)
    print("5. 🔑 POC КАК ФИЛЬТР БОЕВОГО ВХОДА (а не как альтернативный вход)")
    print("=" * 104)
    F = R[R.fib_fill == 1].copy()
    F = F[F.fib_pnl.notna()].rename(columns={"fib_pnl": "pnl"})
    if len(F) >= 100:
        # запас: насколько POC ГЛУБЖЕ входа, в долях хода (0.382 = сам вход)
        F["poc_beyond"] = F.poc_depth - 0.382
        print("  запас магнита = насколько POC глубже фибо-входа (в долях хода):")
        for lo, hi, nm in ((-9, -0.15, "POC ПЕРЕД входом (мельче −0.15)"),
                           (-0.15, 0.0, "POC почти на входе (−0.15…0)"),
                           (0.0, 0.15, "POC чуть глубже (0…+0.15)"),
                           (0.15, 0.35, "POC заметно глубже (+0.15…+0.35)"),
                           (0.35, 9, "POC ДАЛЕКО за входом (>+0.35)")):
            print(line(F[(F.poc_beyond >= lo) & (F.poc_beyond < hi)], f"    {nm}"))
        print("\n  то же по СТОРОНЕ (полярность переворачивала вывод трижды):")
        for side in ("long", "short"):
            for lo, hi, nm in ((-9, 0.0, "магнит ДО входа"), (0.0, 9, "магнит ЗА входом")):
                v = F[(F.side == side) & (F.poc_beyond >= lo) & (F.poc_beyond < hi)]
                print(line(v, f"    {side} · {nm}"))
        print("\n  концентрация объёма в POC (сильный уровень против размазанного):")
        for lo, hi, nm in ((0, 4, "размазан (<4%)"), (4, 6, "средний (4-6%)"),
                           (6, 100, "острый (>6%)")):
            print(line(F[(F.poc_conc >= lo) & (F.poc_conc < hi)], f"    {nm}"))

    # ── 6. МЫСЛЬ ЕГОРА: импульс LTF ≈ одна свеча старшего ТФ ─────────────────
    print("\n" + "=" * 104)
    print("6. СОВПАДАЕТ ЛИ ИМПУЛЬС СО СТАРШЕЙ СВЕЧОЙ (объём 4h = объём импульса LTF)")
    print("=" * 104)
    bars_in_4h = {"15m": 16, "1h": 4}[a.tf]
    print(f"  длина импульса в барах {a.tf}: медиана {R.age.median():.0f} · "
          f"p10 {R.age.quantile(.1):.0f} · p90 {R.age.quantile(.9):.0f}")
    print(f"  в одной свече 4h укладывается {bars_in_4h} баров {a.tf}")
    print(f"  импульсов короче 4h-свечи: {(R.age <= bars_in_4h).mean()*100:.1f}%")
    print(f"  импульсов длиннее суток (96 баров 15m): {(R.age > 96).mean()*100:.1f}%"
          if a.tf == "15m" else "")
    print("  🔑 если импульс короче старшей свечи — POC этой свечи И ЕСТЬ POC импульса,")
    print("     и оба подхода дают один уровень (замечание Егора 28.08).")
    try:
        out = ROOT / "cache" / f"poc_impulse_{a.tf}.parquet"
        R.to_parquet(out)
        print(f"\nсырые сетапы → {out}")
    except Exception as e:                     # noqa: BLE001
        print(f"\n(parquet не сохранён: {e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
