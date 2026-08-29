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
    # 🔴 28.08: до этого дня ВСЯ структурная семья считалась одним масштабом
    # (choch_length=50) — были признаки НАПРАВЛЕНИЯ и ни одного признака ТРИГГЕРА.
    "ДВЕ СТРУКТУРЫ": lambda c: c.startswith(("st5_", "st50_", "sc_")),
    # 🔴 28.08: ног (волн) в матрице не было ВООБЩЕ — слом это точка, нога отрезок
    "ВОЛНЫ": lambda c: c.startswith("leg_"),
    # 🔴 29.08: SMC как СОСТОЯНИЕ. Старые булевы SMC-флаги наполовину были константой 0
    # (Order Blocks помечали 4 бара из 19851) — [[smc_in_matrix_is_dead_weight]]
    "SMC-СОСТОЯНИЕ": lambda c: c.startswith("smc_") or c.startswith("in_smc_"),
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
            senior: list[str] | None = None,
            extra: Callable | None = None) -> pd.DataFrame:
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
                # MATRIX-FULL (28.08): семьи, которых в combinator_core нет — фандинг,
                # ширина вселенной, непрерывные дистанции и состояние осцилляторов.
                # Подключается ОДНОЙ точкой: `extra(df, tf, sym)` → DataFrame по тому же
                # индексу. Забыть расширение при прогоне так же невозможно, как семью.
                if extra is not None:
                    F = pd.concat([F, extra(df, tf, sym)], axis=1)
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
    """
    Колонки-признаки. Мета и НЕ-ЧИСЛОВЫЕ исключаются.

    🔴 28.08: раньше отсекался только `object`, и попавшая в набор колонка ВРЕМЕНИ
    (`entry_ts`, добавлена для среза «кластер») уезжала в отбор, где выполняется
    `IS[IS[f] > 0]` → `TypeError: Invalid comparison between datetime64 and int`,
    и прогон падал на последнем шаге, после часа счёта. Механика вправе возвращать
    любые служебные поля — фильтр обязан пропускать ТОЛЬКО то, что можно сравнивать
    с порогом.
    """
    meta = {"sym", "oos", "year", "side", "pnl"}
    out = []
    for c in R.columns:
        if c in meta:
            continue
        if not (pd.api.types.is_numeric_dtype(R[c]) or pd.api.types.is_bool_dtype(R[c])):
            continue          # object, datetime, timedelta, category — мимо
        out.append(c)
    return out


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

    🔴 ОГРАНИЧЕНИЕ (найдено 28.08): здесь признак проверяется ТОЛЬКО как `f > 0`.
    Для булевых это верно, для ЧИСЛОВЫХ — единственный порог «ноль». А числовых
    в матрице немало (`pivot_nearest_dist_*`, все дистанции и значения из
    `matrix_full`). То есть прошлые «0 из 446» получены при одном фиксированном
    пороге на каждый числовой признак. Для них — `blind_select_num()` ниже.
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
        # 🔴 28.08 ПОРОГ PF СДЕЛАН ОТНОСИТЕЛЬНЫМ. Было `st["pf"] > 1.2` — абсолютное
        # число, откалиброванное под базу с PF около 1.0. Когда сама база сильнее
        # (боевая механика на ранних годах даёт PF 1.91), критерий пропускал
        # подвыборки ХУЖЕ БАЗЫ, то есть отбирал шум.
        # Замер 28.08 (816 сделок, 429 булевых признаков, 12 перемешиваний pnl):
        #   абсолютный порог: реальных кандидатов 43, шум даёт медиану 38 → P=0.250
        #   относительный:    реальных кандидатов 41, шум даёт медиану 17 → P=0.000
        # То есть со старым порогом отбор на IS был практически НЕОТЛИЧИМ ОТ ШУМА.
        if (st["wr"] > b_is["wr"] and st["pf"] > b_is["pf"] * 1.15
                and keep >= min_keep_pct and st["bt"] > b_is["bt"]):
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


def _is_binary(v: pd.Series) -> bool:
    u = pd.unique(v.dropna())
    return len(u) <= 2


def _num_candidates(IS: pd.DataFrame, f: str, base: dict, *,
                    min_keep: float, max_keep: float) -> tuple | None:
    """
    Лучший ПОРОГ признака на IS: децили × две стороны (≥ и ≤).

    Возвращает (сторона, порог, статистика, охват потока) или None.
    Порог — ЗНАЧЕНИЕ, а не квантиль: на OOS применяем то же число, поэтому сдвиг
    распределения между выборками виден, а не замаскирован пересчётом квантиля.
    """
    v = IS[f]
    if v.notna().sum() < 60:
        return None
    qs = v.quantile([i / 10 for i in range(1, 10)]).dropna().unique()
    best = None
    for thr in qs:
        for side, mask in (("≥", v >= thr), ("≤", v <= thr)):
            sub = IS[mask.fillna(False)]
            st = stat(sub)
            if st is None:
                continue
            keep = st["n"] / max(base["n"], 1) * 100
            if keep < min_keep or keep > max_keep:
                continue
            # 🔴 28.08: порог PF обязан быть ОТНОСИТЕЛЬНЫМ. Абсолютные «pf > 1.2»
            # (как в булевой ветке) на базе с PF 1.28 пропускают подвыборки ХУЖЕ базы —
            # перестановочный контроль показал 136 «кандидатов» из 136 на шуме.
            if not (st["wr"] > base["wr"] and st["pf"] > base["pf"] * 1.15
                    and st["bt"] > base["bt"]):
                continue
            if best is None or st["pf"] > best[2]["pf"]:
                best = (side, float(thr), st, keep)
    return best


def blind_select_num(R: pd.DataFrame, *, is_years=(0, 2024), oos_years=(2025, 9999),
                     min_keep_pct: float = 25.0, max_keep_pct: float = 80.0,
                     top: int = 12, n_perm: int = 20, seed: int = 19) -> list[tuple]:
    """
    Слепой отбор ДЛЯ ЧИСЛОВЫХ признаков + перестановочный контроль.

    🔴 Зачем отдельно от `blind_select` (найдено 28.08.2026): тот проверяет любой
    признак как `f > 0`. Для булевых это верно, для ЧИСЛОВЫХ — единственный порог
    «ноль». А числовых в полной матрице больше сотни (все дистанции до магнитов,
    значения осцилляторов, z-оценки, `pivot_nearest_dist_*`). То есть прошлые
    «0 из 446» получены при одной фиксированной точке на каждый числовой признак.
    Здесь порог ищется по децилям в ОБЕ стороны.

    🔴 ПЕРЕСТАНОВОЧНЫЙ КОНТРОЛЬ ОБЯЗАТЕЛЕН. Перебор «признак × 9 децилей × 2 стороны»
    даёт тысячи проверок — часть пройдёт IS СЛУЧАЙНО. Поэтому тот же перебор
    гоняется по ПЕРЕМЕШАННОМУ pnl: сколько «находок» рождает чистый шум. Если
    настоящих кандидатов не больше, чем шумовых, — находок нет, сколько бы
    красивых чисел ни печаталось.
    """
    flags = feature_cols(R)
    num = [f for f in flags if not _is_binary(R[f])]
    IS = R[(~R.oos) & (R.year >= is_years[0]) & (R.year <= is_years[1])]
    OOS = R[R.oos & (R.year >= oos_years[0]) & (R.year <= oos_years[1])]
    b_is, b_oos = stat(IS), stat(OOS)
    print("\n" + "=" * 104)
    print(f"ЧИСЛОВОЙ СЛЕПОЙ ОТБОР · признаков числовых {len(num)} из {len(flags)} · "
          f"IS n={len(IS)} ({IS.sym.nunique()} монет) · OOS n={len(OOS)} ({OOS.sym.nunique()})")
    print("=" * 104)
    if b_is is None or b_oos is None:
        print("🔴 мало данных для протокола"); return []
    print(line(IS, "БАЗА IS")); print(line(OOS, "БАЗА OOS"))

    cands = []
    for f in num:
        got = _num_candidates(IS, f, b_is, min_keep=min_keep_pct, max_keep=max_keep_pct)
        if got:
            cands.append((f, *got))
    cands.sort(key=lambda x: -x[3]["pf"])
    print(f"\nШАГ 1 — прошло IS: {len(cands)} из {len(num)}")
    for f, side, thr, st, keep in cands[:top]:
        print(f"  {f:<44} {side} {thr:<12.5g} PF {st['pf']:5.2f}  WR {st['wr']:5.1f}%  "
              f"безтоп10% {st['bt']:+7.0f}  поток {keep:4.0f}%")

    def _oos_survivors(cand_list, OOSf, base_oos, verbose=False):
        """Применить пороги, выбранные на IS, к OOS. Порог — то же ЧИСЛО."""
        surv = []
        for f, side, thr, _, _ in cand_list[:top]:
            v = OOSf[f]
            sub = OOSf[(v >= thr).fillna(False)] if side == "≥" else OOSf[(v <= thr).fillna(False)]
            st = stat(sub)
            if st is None:
                if verbose:
                    print(f"  {f:<44} мало данных")
                continue
            ok = (st["pf"] > base_oos["pf"] * 1.15 and st["wr"] > base_oos["wr"]
                  and st["bt"] > base_oos["bt"])
            if verbose:
                print(f"  {f:<44} {side} {thr:<12.5g} PF {st['pf']:5.2f}  WR {st['wr']:5.1f}%  "
                      f"безтоп10% {st['bt']:+7.0f}  охват {st['cov']:4.0f}%{'  ✅' if ok else ''}")
            if ok:
                surv.append((f, side, thr))
        return surv

    print(f"\nШАГ 2 — OOS, открываем ОДИН раз (порог тот же ЧИСЛОМ):")
    survived = _oos_survivors(cands, OOS, b_oos, verbose=True)
    print(f"\nПЕРЕЖИЛО OOS: {len(survived)} из {min(len(cands), top)}")

    # ── 🎲 СКВОЗНОЙ ПЕРЕСТАНОВОЧНЫЙ КОНТРОЛЬ ────────────────────────────────
    # 🔴 Считать «сколько прошло IS» мало: перебор признак × 9 децилей × 2 стороны —
    # это тысячи проверок, и часть пройдёт СЛУЧАЙНО. Поэтому под нулевой гипотезой
    # гоняется ВЕСЬ конвейер: перемешали pnl → отобрали на IS → открыли OOS →
    # посчитали выживших. Сравниваем не с нулём, а с тем, что даёт чистый случай.
    rng = np.random.default_rng(seed)
    noise_surv, noise_best = [], []
    for _ in range(n_perm):
        perm = rng.permutation(R.pnl.values)
        Rp = R.copy(); Rp["pnl"] = perm
        ISp = Rp[(~Rp.oos) & (Rp.year >= is_years[0]) & (Rp.year <= is_years[1])]
        OOSp = Rp[Rp.oos & (Rp.year >= oos_years[0]) & (Rp.year <= oos_years[1])]
        bi, bo = stat(ISp), stat(OOSp)
        if bi is None or bo is None:
            continue
        cp = []
        for f in num:
            got = _num_candidates(ISp, f, bi, min_keep=min_keep_pct, max_keep=max_keep_pct)
            if got:
                cp.append((f, *got))
        cp.sort(key=lambda x: -x[3]["pf"])
        noise_best.append(cp[0][3]["pf"] if cp else 0.0)
        noise_surv.append(len(_oos_survivors(cp, OOSp, bo)))

    print(f"\n🎲 СКВОЗНОЙ ПЕРЕСТАНОВОЧНЫЙ КОНТРОЛЬ ({len(noise_surv)} перемешиваний "
          f"pnl, полный конвейер IS→OOS):")
    if not noise_surv:
        print("   🔴 контроль не отработал — выборка слишком мала")
        return survived
    ns = np.array(noise_surv); nb_ = np.array(noise_best)
    print(f"   ШУМ переживает OOS: медиана {np.median(ns):.1f} · "
          f"95-й перцентиль {np.quantile(ns, 0.95):.1f} · максимум {ns.max()}")
    print(f"   ШУМ, лучший PF на IS: медиана {np.median(nb_):.2f} · максимум {nb_.max():.2f}"
          f"   (наш лучший {cands[0][3]['pf']:.2f})" if cands else "")
    p_emp = float((ns >= len(survived)).mean())
    print(f"   наш результат {len(survived)} выживших · P(шум ≥ нашего) = {p_emp:.3f}")
    if len(survived) == 0:
        print("   🔴 находок нет — пороги не переносятся на отложенную выборку")
    elif p_emp > 0.10:
        print("   🔴 РЕЗУЛЬТАТ НЕ ОТЛИЧИМ ОТ ШУМА: случай даёт столько же выживших.")
        print("      Это НЕ находка, сколько бы красивых PF ни печаталось выше.")
    else:
        print("   ✅ выживших существенно больше, чем даёт случай — есть что проверять дальше")
    return survived


if __name__ == "__main__":
    print(__doc__)
    print("Это библиотека. Пример использования — в докстроке выше.")
    print(f"\nчёрный список не-причинных: {sorted(CAUSAL_BLACKLIST)}")
    print(f"семьи признаков: {list(FAMILIES)}")
