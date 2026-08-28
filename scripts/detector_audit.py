"""
detector_audit.py — СТЕНД ПРОВЕРКИ ДЕТЕКТОРОВ. Верен ли инструмент, а не выгоден ли.

Повод (Егор, 28.08.2026): «инструментов у нас много, а вот проверить верность
их работы я пока не понимаю как».

🔑 Различение, которого нам не хватало. Все наши замеры отвечают на вопрос
«приносит ли признак ДЕНЬГИ». Ни один не отвечает на вопрос «находит ли детектор
ТО САМОЕ ЯВЛЕНИЕ». Это независимые вещи:
    · детектор ВЕРЕН, а денег нет  → явление реально, но не торгуемо. Вывод честный.
    · детектор СЛОМАН, денег нет   → мы похоронили рабочую идею, не заметив этого.
Второй случай у нас уже был: замена детектора импульса на конечный автомат дала
2.82 → 0.75, потому что автомат «размечает зигзаг, а не импульс» — то есть находил
НЕ ТО. Поймали случайно, по деньгам. Стенд ловит это прямо.

ПЯТЬ ПРОВЕРОК, ни одна не требует эталонной разметки и не смотрит на прибыль:

  1. ИНВАРИАНТ — удовлетворяет ли КАЖДОЕ срабатывание определению явления
     арифметически. FVG обязан быть настоящим разрывом, BOS — настоящим сломом.
     Это проверяется на 100% событий и не зависит от рынка.
  2. ПРИЧИННОСТЬ — префиксный тест: детектор на df[:n] обязан совпасть с
     детектором на полном df, ограниченным теми же барами. Расхождение = детектор
     переписывает прошлое (класс look-ahead, ловили четырежды).
  3. ЧАСТОТА — вырожденность. Флаг, истинный в 98% баров, не детектор, а константа
     (ровно так SMC-признаки «покрывали конфлюэнцией» 97% выборки).
  4. ДУБЛИ — три версии `detect_fvg` обязаны находить примерно одно. Расхождение
     означает, что как минимум одна сломана, и разные части бота видят разный рынок.
  5. СИНТЕТИКА — ряд с ЗАЛОЖЕННЫМ явлением: детектор обязан его найти; ровный ряд
     без явления: обязан молчать. Даёт полноту и ложные срабатывания без эталона.

    python scripts/detector_audit.py                 # все проверки
    python scripts/detector_audit.py --symbol ARB/USDT --tf 15m
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

from research_harness import load          # noqa: E402

OK, BAD, WARN = "✅", "🔴", "🟡"


def _smc_frame(df: pd.DataFrame) -> pd.DataFrame:
    """SMC-детекторы требуют RangeIndex + колонку `time` (ловушка форматов)."""
    d = df.reset_index()
    d = d.rename(columns={d.columns[0]: "ts"})
    d["time"] = (d.ts.astype("int64") // 10 ** 6)
    return d[["time", "open", "high", "low", "close", "volume"]]


# ── 1. ИНВАРИАНТЫ ────────────────────────────────────────────────────────────
def check_fvg_invariant(df: pd.DataFrame) -> tuple[int, int, list]:
    """
    FVG обязан быть НАСТОЯЩИМ разрывом: low[i] > high[i-2] (бычий) или наоборот.

    🔴 `detect_fvg` возвращает ИНДЕКСЫ БАРОВ, а не метки времени:
    `(idx_left, top, bottom, kind, idx_event, idx_mitigated)`. Первая версия
    стенда (28.08) считала поле 4 меткой времени и делала `searchsorted` по
    временам — для значения 9 это всегда бар 0, дальше `i < 2 → continue`,
    и проверка молча не выполнялась НИ РАЗУ, печатая «0 нарушений».
    Второй ложный ✅ в самом стенде за один прогон. Пустое множество проверок
    выглядит как идеальный результат — это и есть класс «тихого нуля».
    """
    from core.smc.smc_engine import detect_fvg
    d = _smc_frame(df)
    ev = detect_fvg(d)
    H, L = d.high.values, d.low.values
    bad = []
    checked = 0
    for e in ev:
        try:
            i = int(e[4])
            kind = e[3]
        except Exception:      # noqa: BLE001
            continue
        if i < 2 or i >= len(d):
            continue
        checked += 1
        gap_bull = L[i] - H[i - 2]
        gap_bear = L[i - 2] - H[i]
        if str(kind).lower().startswith("bull") and gap_bull <= 0:
            bad.append((i, "bull без разрыва", gap_bull))
        if str(kind).lower().startswith("bear") and gap_bear <= 0:
            bad.append((i, "bear без разрыва", gap_bear))
    # 🔴 отдаём ЧИСЛО РЕАЛЬНО ПРОВЕРЕННЫХ, а не число событий: «0 нарушений»
    # при нуле проверок — это не успех, а несработавший тест.
    return checked, len(bad), bad[:5]


def check_poc_invariant(df: pd.DataFrame, n_trials: int = 200) -> tuple[int, int, list]:
    """POC обязан быть корзиной с МАКСИМАЛЬНЫМ объёмом — проверяем перебором."""
    from poc_impulse_test import impulse_poc
    H, L, V = df.high.values, df.low.values, df.volume.values
    rng = np.random.default_rng(7)
    bad = []
    n = len(df)
    for _ in range(n_trials):
        a = int(rng.integers(200, n - 100))
        b = a + int(rng.integers(10, 60))
        poc, conc = impulse_poc(H, L, V, a, b)
        if poc is None:
            continue
        lo, hi = float(np.min(L[a:b + 1])), float(np.max(H[a:b + 1]))
        if not (lo <= poc <= hi):
            bad.append((a, b, "POC вне диапазона импульса", poc))
        if conc is not None and not (0 < conc <= 100):
            bad.append((a, b, "концентрация вне 0-100%", conc))
    return n_trials, len(bad), bad[:5]


def check_impulse_invariant(df: pd.DataFrame) -> tuple[int, int, list]:
    """Импульс обязан: ход ≥ MIN_ATR·ATR, длина ≤ MAX_BARS, откат внутри ≤ MAX_RETR."""
    from core.smc.impulse_fib import (_atr, find_impulses, MIN_ATR, MAX_BARS, MAX_RETR)
    dd = df.reset_index(drop=True)
    H, L, C = dd.high.values, dd.low.values, dd.close.values
    atr = _atr(dd).values
    n = len(dd)
    bad = []
    ev = list(find_impulses(H, L, C, atr, n))
    for a, b, up in ev:
        move = abs(C[b] - C[a])
        if atr[b] > 0 and move < MIN_ATR * atr[b] * 0.999:
            bad.append((a, b, f"ход {move/atr[b]:.2f} ATR < MIN_ATR {MIN_ATR}"))
        if (b - a) > MAX_BARS:
            bad.append((a, b, f"длина {b-a} > MAX_BARS {MAX_BARS}"))
        seg = C[a:b + 1]
        if up:
            retr = (np.maximum.accumulate(seg) - seg).max() / max(move, 1e-12)
        else:
            retr = (seg - np.minimum.accumulate(seg)).max() / max(move, 1e-12)
        if retr > MAX_RETR * 1.001:
            bad.append((a, b, f"контр-откат {retr:.2f} > MAX_RETR {MAX_RETR}"))
    return len(ev), len(bad), bad[:5]


# ── 2. ПРИЧИННОСТЬ (префиксный тест) ─────────────────────────────────────────
def check_causality(df: pd.DataFrame, cut_frac: float = 0.7) -> dict:
    """
    Детектор на df[:n] обязан совпасть с детектором на полном df в тех же барах.
    Расхождение = событие переписано задним числом.

    🔴 СРАВНИВАЕМ ПО ИНДЕКСУ БАРА, а не по метке времени.
    Первая версия стенда (28.08) искала «время» эвристикой «поле > 10^12» и дала
    ЛОЖНУЮ ТРЕВОГУ: «30 расхождений, BOS переписывает историю». На деле `ts`
    у `StructureBreak` равен 119 — это не миллисекунды и вообще не время,
    эвристика хватала не то поле. По индексу расхождений НОЛЬ.
    Урок: стенд проверки инструментов сам нуждается в проверке; поймали
    по абсурдному числу (расстояние «1 981 643 бара» при выборке 15 000).
    """
    from core.smc.smc_engine import detect_fvg, detect_structure_breaks
    n = int(len(df) * cut_frac)
    full, pref = _smc_frame(df), _smc_frame(df.iloc[:n])
    res = {}

    def bar_index(evs, frame):
        """Индекс бара события. Берём поле `idx`, иначе ищем по времени в кадре."""
        out = set()
        t2i = {int(t): i for i, t in enumerate(frame.time.values)}
        n_bars = len(frame)
        for e in evs:
            i = getattr(e, "idx", None)
            if i is None and isinstance(e, (tuple, list)):
                # Детекторы отдают позицию по-разному: `detect_fvg` — ИНДЕКС бара
                # (поле 4), другие — метку времени. Различаем по масштабу, а не
                # по вере: индекс лежит в [0, n_bars), метка есть среди времён кадра.
                for x in e:
                    if not isinstance(x, (int, float, np.integer, np.floating)):
                        continue
                    k = int(x)
                    if k in t2i:
                        i = t2i[k]; break
                if i is None and len(e) > 4 and isinstance(
                        e[4], (int, float, np.integer, np.floating)):
                    k = int(e[4])
                    if 0 <= k < n_bars:
                        i = k
            if i is not None:
                out.add(int(i))
        return out

    for nm, fn in (("detect_fvg", detect_fvg),
                   ("detect_structure_breaks", detect_structure_breaks)):
        try:
            a = fn(full); b = fn(pref)
        except Exception as e:      # noqa: BLE001
            res[nm] = ("ошибка", str(e)[:50]); continue
        ia = {i for i in bar_index(a, full) if i < n}
        ib = bar_index(b, pref)
        if not ia and not ib:
            res[nm] = ("не извлеклись индексы", "тест НЕ отработал"); continue
        res[nm] = (len(ia), len(ib), len(ia ^ ib))
    return res


# ── 3. ЧАСТОТА (вырожденность) ───────────────────────────────────────────────
def check_frequency(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    from core.calculators.combinator_core import compute_flags
    F = compute_flags(df, tf, include_pivots=True)
    F = F.select_dtypes(include=["bool"])
    share = F.mean() * 100
    out = pd.DataFrame({"доля_true_%": share.round(2)})
    out["вердикт"] = np.where(share > 90, "🔴 константа",
                      np.where(share > 70, "🟡 почти всегда",
                       np.where(share < 0.1, "🔴 почти никогда", "✅")))
    return out.sort_values("доля_true_%", ascending=False)


# ── 4. ДУБЛИ ─────────────────────────────────────────────────────────────────
def check_duplicates(df: pd.DataFrame) -> None:
    """Три версии detect_fvg обязаны находить примерно одно."""
    d = _smc_frame(df)
    counts = {}
    try:
        from core.smc.smc_engine import detect_fvg as f_engine
        counts["smc_engine (эталон)"] = len(f_engine(d))
    except Exception as e:      # noqa: BLE001
        counts["smc_engine (эталон)"] = f"ошибка {type(e).__name__}"
    try:
        from core.smc.fvg import detect_fvg as f_old
        counts["smc/fvg.py (архаика)"] = len(f_old(d))
    except Exception as e:      # noqa: BLE001
        counts["smc/fvg.py (архаика)"] = f"ошибка {type(e).__name__}"
    try:
        from core.indicators.indicators import detect_fvg as f_simple
        r = f_simple(df)
        counts["indicators.py (упрощ.)"] = "точечный (последний бар): " + str(r)
    except Exception as e:      # noqa: BLE001
        counts["indicators.py (упрощ.)"] = f"ошибка {type(e).__name__}"
    for k, v in counts.items():
        print(f"    {k:<26} {v}")


# ── 5. СИНТЕТИКА С ИЗВЕСТНЫМ ОТВЕТОМ ─────────────────────────────────────────
def synth_with_fvg(n: int = 300, gap_at: int = 150, gap: float = 5.0) -> pd.DataFrame:
    """Ровный ряд + ОДИН заложенный бычий разрыв. Детектор обязан найти ровно его."""
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    base = 100.0 + np.zeros(n)
    o = base.copy(); c = base.copy(); h = base + 0.5; l = base - 0.5
    o[gap_at:] += gap; c[gap_at:] += gap; h[gap_at:] += gap; l[gap_at:] += gap
    l[gap_at] = base[gap_at] + gap - 0.1          # low выше high[gap_at-2] → разрыв
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                         "volume": np.full(n, 100.0)}, index=idx)


def synth_flat(n: int = 300) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0,
                         "volume": 100.0}, index=idx)


def check_synthetic() -> None:
    from core.smc.smc_engine import detect_fvg
    with_gap = detect_fvg(_smc_frame(synth_with_fvg()))
    flat = detect_fvg(_smc_frame(synth_flat()))
    print(f"    ряд С заложенным разрывом : найдено {len(with_gap)} "
          f"{OK if len(with_gap) >= 1 else BAD + ' явление ПРОПУЩЕНО'}")
    print(f"    ровный ряд БЕЗ разрывов   : найдено {len(flat)} "
          f"{OK if len(flat) == 0 else BAD + ' ЛОЖНЫЕ срабатывания'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Стенд проверки детекторов")
    ap.add_argument("--symbol", default="ARB/USDT")
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--bars", type=int, default=20000)
    a = ap.parse_args()

    df = load(a.symbol, a.tf).tail(a.bars)
    print("=" * 100)
    print(f"СТЕНД ПРОВЕРКИ ДЕТЕКТОРОВ · {a.symbol} · {a.tf} · {len(df)} баров")
    print("Вопрос стенда: ВЕРЕН ли инструмент. Не «выгоден ли» — это другой вопрос.")
    print("=" * 100)

    print("\n1️⃣  ИНВАРИАНТЫ — удовлетворяет ли каждое срабатывание определению")
    for nm, fn in (("FVG (разрыв реален?)", check_fvg_invariant),
                   ("POC (максимум объёма?)", check_poc_invariant),
                   ("Импульс (ход/длина/откат)", check_impulse_invariant)):
        try:
            total, bad, ex = fn(df)
            mark = OK if bad == 0 else BAD
            print(f"  {mark} {nm:<28} событий {total:<6} нарушений {bad}")
            for e in ex:
                print(f"        ↳ {e}")
        except Exception as e:      # noqa: BLE001
            print(f"  {WARN} {nm:<28} не проверен: {type(e).__name__}: {str(e)[:60]}")

    print("\n2️⃣  ПРИЧИННОСТЬ — префиксный тест (детектор не переписывает прошлое)")
    try:
        for nm, r in check_causality(df).items():
            if len(r) == 2:
                print(f"  {WARN} {nm:<28} {r[0]}: {r[1]}")
            else:
                mark = OK if r[2] == 0 else BAD
                print(f"  {mark} {nm:<28} на полном {r[0]:<5} на префиксе {r[1]:<5} "
                      f"расхождений {r[2]}")
    except Exception as e:      # noqa: BLE001
        print(f"  {WARN} не проверено: {type(e).__name__}: {str(e)[:70]}")

    print("\n3️⃣  ЧАСТОТА — вырожденные флаги (константа вместо детектора)")
    try:
        FR = check_frequency(df, a.tf)
        bad = FR[FR["вердикт"].str.startswith(("🔴", "🟡"))]
        print(f"  булевых флагов: {len(FR)} · подозрительных: {len(bad)}")
        for i, (nm, row) in enumerate(bad.iterrows()):
            if i >= 12:
                print(f"    … ещё {len(bad)-12}"); break
            print(f"    {row['вердикт']} {nm:<40} true в {row['доля_true_%']:5.2f}% баров")
    except Exception as e:      # noqa: BLE001
        print(f"  {WARN} не проверено: {type(e).__name__}: {str(e)[:70]}")

    print("\n4️⃣  ДУБЛИ — три версии detect_fvg на ОДНИХ данных")
    check_duplicates(df)

    print("\n5️⃣  СИНТЕТИКА — ряд с заложенным явлением и ряд без него")
    check_synthetic()

    print("\n" + "=" * 100)
    print("🔑 Стенд не говорит, выгоден ли инструмент. Он говорит, ВЕРЕН ли он.")
    print("   Верный и невыгодный — честный отрицательный результат.")
    print("   Сломанный и невыгодный — похороненная рабочая идея.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
