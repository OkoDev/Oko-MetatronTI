"""
research_harness.py — ЕДИНАЯ ТОЧКА ВХОДА ДЛЯ ПРОВЕРКИ ГИПОТЕЗ.

Повод (Егор, 21.08.2026): «мне постоянно приходится напоминать про детекторы и
семейства признаков». Справедливо: каждый замер собирался руками, признаки брались
те, что вспомнились. Пивоты, WT, ATR-тренд и дивергенции регулярно выпадали —
хотя матрица с ними лежит в `combinator_core.compute_flags` и содержит 151 признак.

Здесь всё прописано НА ВХОДЕ. Забыть семью технически невозможно: матрица
подтягивается целиком, чёрный список не-причинных зашит, обязательные срезы
печатаются всегда — не по желанию исследователя.

    from scripts.research_harness import collect, blind_select, report

    R = collect(mechanic_impulse_fib, tf="15m", side="long", n_symbols=25)
    report(R)                       # обязательные срезы, всегда
    blind_select(R)                 # IS → OOS, защита от множественного тестирования

Законы проекта, зашитые в код (не опции):
  · % net с костами, НЕ R ([[principle_measure_pct_not_r_LAW]]);
  · хрупкость = сумма без верхних 10% — печатается в КАЖДОЙ строке;
  · охват монет печатается в КАЖДОЙ строке («плюс на 4 из 10» — не эдж);
  · порог/признак выбирается ТОЛЬКО на IS, OOS открывается один раз;
  · признак-фильтр обязан быть известен В МОМЕНТ ВХОДА.

🔴 ФОРМАТЫ (три тихих нуля 21.08 — см. feedback_get_ohlcv_format_trap):
  · `compute_flags` требует DatetimeIndex (ресемплит пивоты);
  · SMC-детекторы требуют RangeIndex + колонку `time`;
  · символы в кэше БЕЗ суффикса: '0G/USDT', не '0G/USDT:USDT'.
"""
from __future__ import annotations

import hashlib
import random
import sqlite3
import sys
import warnings
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

DB = str(ROOT / "ohlcv_cache.db")
COST_LIMIT = 0.35          # круг лимитом
COST_MARKET = 0.79         # круг по рынку

# 🔴 НЕ ПРИЧИННЫЕ — переписываются задним числом. Проверено префиксным аудитом
# 21.08: 150 из 151 флага чисты, этот единственный расходится.
CAUSAL_BLACKLIST = {"bear_fvg_overlap_held", "bull_fvg_overlap_held"}

# Семьи признаков — для отчёта «что вообще проверено»
FAMILIES = {
    "пивоты":      lambda c: "pivot" in c,
    "WT":          lambda c: c.startswith("wt_") and "div" not in c,
    "дивергенции": lambda c: "div" in c,
    "ATR-тренд":   lambda c: c.startswith("atr_"),
    "SMC":         lambda c: any(k in c for k in ("bos", "choch", "fvg", "ob_", "eqh", "eql", "ote")),
    "СО СТАРШИХ ТФ": lambda c: "__from_" in c,
}


# 🔴 22.08 ПОРОГ ИСТОРИИ ЗАВИСИТ ОТ ТФ. Раньше здесь стояло 12000 баров для любого ТФ —
# значение из эпохи 15m. На 4h столько НЕ БЫВАЕТ: всё окно кэша (2022-01→2026-07, 4.6 года)
# это максимум ~10 038 баров, и запрос возвращал НОЛЬ символов молча, без ошибки.
# Ровно класс «трёх тихих нулей» ([[feedback_get_ohlcv_format_trap]]): пустой результат
# вместо отказа. Пороги = примерно 2.5-3 года истории на каждом ТФ.
MIN_BARS_TF = {"5m": 20000, "15m": 12000, "1h": 8000, "4h": 4000, "1d": 600, "3m": 20000}


def universe(tf: str, min_bars: int | None = None, n: int = 25, seed: int = 19) -> list[str]:
    """Вселенная из кэша. Тот же seed → те же монеты, что в прошлых замерах."""
    if min_bars is None:
        min_bars = MIN_BARS_TF.get(tf, 12000)
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as c:
        rows = c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? "
                         "GROUP BY symbol HAVING n>? ORDER BY n DESC", (tf, min_bars)).fetchall()
    if not rows:
        raise RuntimeError(
            f"universe({tf}): НОЛЬ символов с историей > {min_bars} баров. "
            f"Молчаливый пустой замер запрещён — проверьте порог MIN_BARS_TF и кэш.")
    from core.smc.impulse_fib import is_junk
    syms = [s for s, _ in rows if not is_junk(s)]
    random.Random(seed).shuffle(syms)
    return syms[:n]


def load(sym: str, tf: str) -> pd.DataFrame:
    """OHLCV с DatetimeIndex. Для SMC-детекторов делайте .reset_index(drop=True)."""
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as c:
        d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                        "WHERE symbol=? AND timeframe=? ORDER BY time", c, params=(sym, tf))
    if d.empty:
        return d
    d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
    return d.set_index("ts")[["open", "high", "low", "close", "volume"]]


def mtf_flags(df: pd.DataFrame, tf: str, senior: list[str] | None = None) -> pd.DataFrame:
    """
    Матрица признаков МЛАДШЕГО ТФ + признаки СТАРШИХ, приведённые к его сетке.

    Зачем: вся наша механика стоит на MTF — контекст ноги 1h для 15m, вложенность
    как основа Куба. Односейный замер систематически недооценивает механику.

    🔴 ПРИЧИННОСТЬ СТАРШЕГО ТФ — главная ловушка (класс-3 look-ahead из наших законов):
    старший бар закрывается ПОЗЖЕ младшего. Берём значение старшего ТФ только
    с ЗАКРЫТОГО бара: ресемпл → shift(1) → reindex по младшей сетке с ffill.
    Без shift(1) младший бар 10:15 «узнает» часовой бар 10:00-11:00 до его закрытия.

    senior=None → авто: 15m→[1h,4h] · 1h→[4h,1d] · 5m→[15m,1h] · 4h→[1d]
    """
    from core.calculators.combinator_core import compute_flags
    AUTO = {"5m": ["15m", "1h"], "15m": ["1h", "4h"], "1h": ["4h", "1d"], "4h": ["1d"]}
    RULE = {"15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}
    senior = AUTO.get(tf, []) if senior is None else senior

    base = compute_flags(df, tf, include_pivots=True)
    base = base.drop(columns=[c for c in base.columns
                              if any(b in c for b in CAUSAL_BLACKLIST)], errors="ignore")
    base = base.select_dtypes(include=["number", "bool"])
    out = [base]
    for stf in senior:
        rule = RULE.get(stf)
        if rule is None: continue
        agg = df.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                     "close": "last", "volume": "sum"}).dropna()
        if len(agg) < 300: continue
        try:
            F = compute_flags(agg, stf, include_pivots=True)
        except Exception:                                    # noqa: BLE001
            continue
        F = F.drop(columns=[c for c in F.columns
                            if any(b in c for b in CAUSAL_BLACKLIST)], errors="ignore")
        F = F.select_dtypes(include=["number", "bool"])
        # 🔴 shift(1) = берём только ЗАКРЫТЫЙ старший бар
        F = F.shift(1).reindex(df.index, method="ffill")
        F.columns = [f"{c}__from_{stf}" for c in F.columns]
        out.append(F)
    return pd.concat(out, axis=1)


def collect(mechanic: Callable, *, tf: str = "15m", n_symbols: int = 25,
            with_flags: bool = True, cost: float = COST_LIMIT,
            senior: list[str] | None = None) -> pd.DataFrame:
    """
    Прогоняет механику по вселенной и приклеивает ВСЮ матрицу признаков
    на баре ВХОДА (не импульса!).

    `mechanic(df, tf) -> list[dict]`, каждый dict обязан содержать:
        entry_bar (индекс бара ВХОДА), pnl_pct (БЕЗ костов), side.
    Косты вычитаются здесь — единообразно, по закону №1.
    """
    out = []
    syms = universe(tf, n=n_symbols)
    print(f"вселенная: {len(syms)} монет, ТФ {tf}, косты {cost}%")
    min_bars = MIN_BARS_TF.get(tf, 12000)
    skipped = 0
    for i, sym in enumerate(syms, 1):
        df = load(sym, tf)
        if len(df) < min_bars:          # 🔴 порог по ТФ, а не зашитые 6000 (см. MIN_BARS_TF)
            skipped += 1
            continue
        try:
            trades = mechanic(df, tf)
        except Exception as e:  # noqa: BLE001
            print(f"  [{sym}] механика упала: {type(e).__name__}: {str(e)[:60]}")
            continue
        if not trades:
            continue
        F = None
        if with_flags:
            try:
                # MTF: младший ТФ + старшие с ЗАКРЫТОГО бара (shift(1))
                F = mtf_flags(df, tf, senior)
            except Exception as e:  # noqa: BLE001
                print(f"  [{sym}] флаги упали: {type(e).__name__}: {str(e)[:60]}")
        oos = int(hashlib.md5(sym.encode()).hexdigest(), 16) % 2 == 1
        for t in trades:
            jf = int(t["entry_bar"])
            row = {"sym": sym, "oos": oos, "year": int(df.index[jf].year),
                   "side": t.get("side", "?"), "pnl": float(t["pnl_pct"]) - cost}
            row.update({k: v for k, v in t.items()
                        if k not in ("entry_bar", "pnl_pct", "side")})
            if F is not None and jf < len(F):
                row.update({c: F[c].values[jf] for c in F.columns})
            out.append(row)
        if i % 5 == 0:
            print(f"  ... {i}/{len(syms)} · {len(out)}", flush=True)
    R = pd.DataFrame(out)
    if skipped:
        print(f"  пропущено по короткой истории (<{min_bars} баров): {skipped} из {len(syms)}")
    if R.empty:
        raise RuntimeError(
            f"collect({tf}): НОЛЬ сделок. Пустой результат — это отказ, а не вывод. "
            f"Проверьте: порог истории · формат индекса · саму механику.")
    if not R.empty:
        flags = feature_cols(R)
        print(f"\nсобрано: {len(R)} сделок · {R.sym.nunique()} монет · признаков {len(flags)}")
        for name, pred in FAMILIES.items():
            k = sum(1 for c in flags if pred(c))
            if k: print(f"    {name:<14} {k}")
    return R


def feature_cols(R: pd.DataFrame) -> list[str]:
    meta = {"sym", "oos", "year", "side", "pnl"}
    return [c for c in R.columns if c not in meta and R[c].dtype != object]


def stat(v: pd.DataFrame) -> dict | None:
    """Метрики по закону: % net, хрупкость и охват ОБЯЗАТЕЛЬНЫ."""
    p = v.pnl.values
    if len(p) < 30:
        return None
    w = p[p > 0]; gl = -p[p <= 0].sum(); s = np.sort(p)[::-1]
    per = v.groupby("sym").pnl.sum()
    return dict(n=len(p), wr=len(w) / len(p) * 100, pf=(w.sum() / gl if gl else 0.0),
                avg=p.mean(), bt=s[int(len(s) * 0.1):].sum(), cov=(per > 0).mean() * 100,
                coins=v.sym.nunique())


def line(v: pd.DataFrame, nm: str) -> str:
    st = stat(v)
    if st is None:
        return f"  {nm:<32} n={len(v)} — мало"
    return (f"  {nm:<32} n={st['n']:<6} WR {st['wr']:5.1f}%  PF {st['pf']:5.2f}  "
            f"ср {st['avg']:+6.2f}%  безтоп10% {st['bt']:+8.0f}  охват {st['cov']:4.0f}%")


def report(R: pd.DataFrame) -> None:
    """ОБЯЗАТЕЛЬНЫЕ СРЕЗЫ. Печатаются всегда — это закон, а не опция."""
    if R.empty:
        print("🔴 пусто"); return
    print("\n" + "=" * 104)
    print(f"ОБЯЗАТЕЛЬНЫЕ СРЕЗЫ · {R.sym.nunique()} монет · {len(R)} сделок")
    print("=" * 104)
    print(line(R, "ВСЁ"))
    if R.side.nunique() > 1:
        print("\nСТОРОНА:")
        for s in sorted(R.side.unique()):
            print(line(R[R.side == s], f"  {s}"))
    print("\nГОД:")
    for y in sorted(R.year.unique()):
        print(line(R[R.year == y], f"  {y}"))
    if "stop_pct" in R.columns:
        print("\nРАЗМЕР СТОПА:")
        for lo, hi in ((0, 2), (2, 4), (4, 8), (8, 100)):
            print(line(R[(R.stop_pct >= lo) & (R.stop_pct < hi)], f"  {lo}-{hi}%"))
    print("\n🔑 НЕ проверено в этом отчёте — назвать явно: режим года · кластер · ликвидность,")
    print("   если соответствующие колонки не собраны механикой.")


def blind_select(R: pd.DataFrame, *, is_years=(0, 2024), oos_years=(2025, 9999),
                 min_keep_pct: float = 25.0, top: int = 12) -> list[str]:
    """
    Слепой отбор признаков. IS = чётные монеты × ранние годы, OOS = нечётные × поздние.
    Пересечение монет НУЛЕВОЕ. OOS открывается ОДИН раз, выбор не пересматривается.

    🔴 Без этого протокола перебор сотни признаков ГАРАНТИРОВАННО даст «грааль»
    случайно — за сессию так сгорело три вердикта подряд.
    """
    flags = feature_cols(R)
    IS = R[(~R.oos) & (R.year >= is_years[0]) & (R.year <= is_years[1])]
    OOS = R[R.oos & (R.year >= oos_years[0]) & (R.year <= oos_years[1])]
    b_is, b_oos = stat(IS), stat(OOS)
    print("\n" + "=" * 104)
    print(f"СЛЕПОЙ ОТБОР · IS n={len(IS)} ({IS.sym.nunique()} монет) · "
          f"OOS n={len(OOS)} ({OOS.sym.nunique()} монет) · "
          f"пересечение {len(set(IS.sym) & set(OOS.sym))}")
    print("=" * 104)
    if b_is is None or b_oos is None:
        print("🔴 мало данных для протокола"); return []
    print(line(IS, "БАЗА IS")); print(line(OOS, "БАЗА OOS"))

    cands = []
    for f in flags:
        v = IS[IS[f] > 0]
        st = stat(v)
        if st is None: continue
        keep = st["n"] / max(b_is["n"], 1) * 100
        # 🔴 21.08: флаг, срабатывающий почти ВСЕГДА, ничего не различает.
        # SMC-признаки давали OB в 98% входов, FVG в 99% — «конфлюэнция»
        # покрывала 97% выборки, то есть фильтровала воздух. Отсекаем.
        if keep > 80:
            continue
        if (st["wr"] > b_is["wr"] and st["pf"] > 1.2 and keep >= min_keep_pct
                and st["bt"] > b_is["bt"]):
            cands.append((f, st, keep))
    cands.sort(key=lambda x: -x[1]["wr"])
    print(f"\nШАГ 1 — кандидатов на IS: {len(cands)} из {len(flags)}")
    for f, st, keep in cands[:top]:
        print(f"  {f:<40} WR {st['wr']:5.1f}%  PF {st['pf']:5.2f}  "
              f"безтоп10% {st['bt']:+7.0f}  поток {keep:4.0f}%")
    if not cands:
        print("🔴 ни один признак не прошёл даже IS")
        return []

    print(f"\nШАГ 2 — OOS, открываем ОДИН раз:")
    survived = []
    for f, _, _ in cands[:top]:
        v = OOS[OOS[f] > 0]
        st = stat(v)
        if st is None:
            print(f"  {f:<40} мало данных"); continue
        ok = (st["pf"] > b_oos["pf"] * 1.15 and st["wr"] > b_oos["wr"]
              and st["bt"] > b_oos["bt"])
        print(f"  {f:<40} WR {st['wr']:5.1f}%  PF {st['pf']:5.2f}  "
              f"безтоп10% {st['bt']:+7.0f}  охват {st['cov']:4.0f}%{'  ✅' if ok else ''}")
        if ok: survived.append(f)
    print(f"\nПЕРЕЖИЛО OOS: {len(survived)} из {min(len(cands), top)}")
    if not survived:
        print("🔴 отбор на IS был подгонкой — признаки не переносятся")
    return survived


if __name__ == "__main__":
    print(__doc__)
    print("Это библиотека. Пример использования — в докстроке выше.")
    print(f"\nчёрный список не-причинных: {sorted(CAUSAL_BLACKLIST)}")
    print(f"семьи признаков: {list(FAMILIES)}")
