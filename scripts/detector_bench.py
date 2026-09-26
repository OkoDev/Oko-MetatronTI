"""
detector_bench.py — БОЛЬШАЯ ТАБЛИЦА ДЕТЕКТОРОВ И ИХ ПРОВЕРОК.

Развитие `detector_audit.py` (Егор 28.08: «давай большую таблицу детекторов
и их проверки на стенде»). Отличие: детекторы объявлены РЕЕСТРОМ, проверки
применяются ко всем автоматически. Новый детектор добавляется ОДНОЙ записью.

Каждый детектор проходит четыре проверки, ни одна не смотрит на прибыль:

  СОБЫТИЯ   сколько нашёл · на скольких барах · частота (вырожденность)
  ИНВАРИАНТ удовлетворяет ли КАЖДОЕ срабатывание определению явления
  ПРИЧИННОСТЬ детектор на df[:n] обязан совпасть с детектором на полном df
  СИНТЕТИКА  ряд с ЗАЛОЖЕННЫМ явлением → обязан найти;
             ровный ряд → обязан молчать

🔴 ГЛАВНОЕ ПРАВИЛО СТЕНДА (выучено кровью 28.08): «0 нарушений» при НУЛЕ
проверенных — это не успех, а несработавший тест. Поэтому каждая проверка
возвращает ЧИСЛО РЕАЛЬНО ПРОВЕРЕННЫХ, и стенд печатает «н/д», а не ✅,
когда проверить не удалось. Пустое множество выглядит как идеальный результат —
на этом стенд уже дважды обманул сам себя.

    python scripts/detector_bench.py
    python scripts/detector_bench.py --symbol BTC/USDT --tf 1h --bars 20000
    python scripts/detector_bench.py --export   # → cache/detector_bench.json для графиков
"""
from __future__ import annotations

import argparse
import json
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


def smc_frame(df: pd.DataFrame) -> pd.DataFrame:
    """SMC-детекторы требуют RangeIndex + колонку `time` (ловушка форматов)."""
    d = df.reset_index()
    d = d.rename(columns={d.columns[0]: "ts"})
    d["time"] = d.ts.astype("int64") // 10 ** 6
    return d[["time", "open", "high", "low", "close", "volume"]]


# ═══════════════ СИНТЕТИЧЕСКИЕ РЯДЫ С ИЗВЕСТНЫМ ОТВЕТОМ ═══════════════════════
def synth_flat(n: int = 400) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0,
                         "volume": 100.0}, index=idx)


def synth_gap(n: int = 400, at: int = 200, gap: float = 5.0) -> pd.DataFrame:
    d = synth_flat(n).copy()
    for c in ("open", "high", "low", "close"):
        d.iloc[at:, d.columns.get_loc(c)] += gap
    d.iloc[at, d.columns.get_loc("low")] = 100.2 + 0.1     # low выше high[at-2]
    return d


def synth_impulse(n: int = 500, start: int = 200, length: int = 30,
                  amp: float = 25.0) -> pd.DataFrame:
    """Ровный ряд + ОДИН чистый ход вверх без откатов."""
    d = synth_flat(n).copy()
    ramp = np.linspace(0, amp, length)
    for i, k in enumerate(range(start, start + length)):
        for c in ("open", "high", "low", "close"):
            d.iloc[k, d.columns.get_loc(c)] += ramp[i]
    for k in range(start + length, n):
        for c in ("open", "high", "low", "close"):
            d.iloc[k, d.columns.get_loc(c)] += amp
    return d


def synth_break(n: int = 500, at: int = 300) -> pd.DataFrame:
    """Диапазон, затем чистый пробой вверх — обязан дать слом структуры."""
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    base = 100 + 2 * np.sin(np.arange(n) / 7.0)
    base[at:] += 12.0
    return pd.DataFrame({"open": base, "high": base + 0.4, "low": base - 0.4,
                         "close": base, "volume": 100.0}, index=idx)


# ═══════════════ ИНВАРИАНТЫ ═══════════════════════════════════════════════════
def inv_fvg(df, d, ev):
    """Разрыв обязан быть настоящим: low[i] > high[i-2] или high[i] < low[i-2]."""
    H, L = d.high.values, d.low.values
    checked, bad = 0, []
    for e in ev:
        i = int(e[4]); kind = str(e[3]).lower()
        if i < 2 or i >= len(d):
            continue
        checked += 1
        if kind.startswith("bull") and (L[i] - H[i - 2]) <= 0:
            bad.append((i, "bull без разрыва"))
        if kind.startswith("bear") and (L[i - 2] - H[i]) <= 0:
            bad.append((i, "bear без разрыва"))
    return checked, bad


def inv_breaks(df, d, ev):
    """Слом обязан РЕАЛЬНО пробить экстремум прошлого: цена за уровнем."""
    H, L, C = d.high.values, d.low.values, d.close.values
    checked, bad = 0, []
    for e in ev:
        i = int(getattr(e, "idx", -1))
        px = float(getattr(e, "price", np.nan))
        dr = str(getattr(e, "direction", "")).lower()
        if i <= 0 or i >= len(d) or not np.isfinite(px):
            continue
        checked += 1
        if dr in ("up", "bull", "bullish") and H[i] < px:
            bad.append((i, f"слом вверх, но high {H[i]:.6g} < уровня {px:.6g}"))
        if dr in ("down", "bear", "bearish") and L[i] > px:
            bad.append((i, f"слом вниз, но low {L[i]:.6g} > уровня {px:.6g}"))
    return checked, bad


def inv_impulse(df, d, ev):
    from core.smc.impulse_fib import MIN_ATR, MAX_BARS, MAX_RETR, _atr
    dd = df.reset_index(drop=True)
    C = dd.close.values
    atr = _atr(dd).values
    checked, bad = 0, []
    for a, b, up in ev:
        checked += 1
        move = abs(C[b] - C[a])
        if atr[b] > 0 and move < MIN_ATR * atr[b] * 0.999:
            bad.append((b, f"ход {move/atr[b]:.2f} ATR < {MIN_ATR}"))
        if (b - a) > MAX_BARS:
            bad.append((b, f"длина {b-a} > {MAX_BARS}"))
        seg = C[a:b + 1]
        retr = ((np.maximum.accumulate(seg) - seg).max() if up
                else (seg - np.minimum.accumulate(seg)).max()) / max(move, 1e-12)
        if retr > MAX_RETR * 1.001:
            bad.append((b, f"откат {retr:.2f} > {MAX_RETR}"))
    return checked, bad


def inv_ob(df, d, ev):
    """Order block обязан лежать в пределах реального ценового диапазона."""
    lo, hi = float(d.low.min()), float(d.high.max())
    checked, bad = 0, []
    for e in ev:
        top = getattr(e, "top", None) or getattr(e, "high", None)
        btm = getattr(e, "bottom", None) or getattr(e, "low", None)
        if top is None or btm is None:
            continue
        checked += 1
        if not (lo <= float(btm) <= float(top) <= hi):
            bad.append((getattr(e, "idx", -1), f"зона [{btm}, {top}] вне диапазона"))
    return checked, bad


def inv_equal(df, d, ev):
    """EQH/EQL — пара уровней, которые обязаны быть БЛИЗКИ друг к другу.

    🔴 ФИКС 04.09.2026. Раньше брались «два последних ЧИСЛОВЫХ поля» кортежа — но
    контракт детектора `(ts1, p1, ts2, p2, lab)`, и при числовом индексе DataFrame
    метки времени проходят проверку `isinstance(..., int|float)` наравне с ценами.
    В результате сравнивались timestamp с ценой → 134/134 «нарушений», расхождение
    99.98%. Детектор был исправен: `smc_engine.py:441` сравнивает именно цены
    (`abs(p2 - p1) < threshold*ATR`).

    Это цена «умного» разбора вместо контракта: инвариант должен читать ПОЗИЦИИ
    полей, а не угадывать их по типу. Класс ошибки — прибор врал, не механизм
    (см. [[law_no_finding_means_no_feature]] и историю с EQH, где вердикт менялся
    четырежды, и один раз именно из-за инструмента сравнения).
    """
    checked, bad = 0, []
    for e in ev:
        if not isinstance(e, (tuple, list)) or len(e) < 4:
            continue
        try:
            a, b = float(e[1]), float(e[3])      # позиции цен по контракту
        except (TypeError, ValueError):
            continue
        if not (a > 0 and b > 0):
            continue
        checked += 1
        if abs(a - b) / a > 0.02:
            bad.append((None, f"уровни расходятся на {abs(a-b)/a*100:.2f}% (>2%)"))
    return checked, bad


# ═══════════════ РЕЕСТР ДЕТЕКТОРОВ ════════════════════════════════════════════
def _pos_tuple_idx4(ev, n):
    return {int(e[4]) for e in ev if isinstance(e, (tuple, list)) and len(e) > 4
            and 0 <= int(e[4]) < n}


def _pos_attr_idx(ev, n):
    out = set()
    for e in ev:
        i = getattr(e, "idx", None)
        if i is not None and 0 <= int(i) < n:
            out.add(int(i))
    return out


def _pos_impulse(ev, n):
    return {int(b) for _, b, _ in ev if 0 <= int(b) < n}


DETECTORS = [
    dict(name="detect_fvg", group="SMC", need="smc",
         call=lambda d: __import__("core.smc.smc_engine", fromlist=["x"]).detect_fvg(d),
         pos=_pos_tuple_idx4, inv=inv_fvg,
         synth=[("разрыв", synth_gap, 1, None), ("ровный", synth_flat, 0, 0)]),
    dict(name="detect_structure_breaks", group="SMC", need="smc",
         call=lambda d: __import__("core.smc.smc_engine", fromlist=["x"]).detect_structure_breaks(d),
         pos=_pos_attr_idx, inv=inv_breaks,
         synth=[("пробой", synth_break, 1, None), ("ровный", synth_flat, 0, 0)]),
    dict(name="detect_order_blocks", group="SMC", need="smc_breaks",
         call=None, pos=_pos_attr_idx, inv=inv_ob,
         synth=[("пробой", synth_break, 0, None), ("ровный", synth_flat, 0, 0)]),
    dict(name="detect_equal_levels", group="SMC", need="smc",
         call=lambda d: __import__("core.smc.smc_engine", fromlist=["x"]).detect_equal_levels(d),
         pos=None, inv=inv_equal,
         synth=[("ровный", synth_flat, 0, None)]),
    dict(name="detect_fvg_overlap", group="SMC", need="smc",
         call=lambda d: __import__("core.smc.smc_engine", fromlist=["x"]).detect_fvg_overlap(d),
         pos=None, inv=None,
         synth=[("ровный", synth_flat, 0, 0)]),
    dict(name="detect_inducement", group="SMC-ext", need="smc",
         call=lambda d: __import__("core.smc.smc_extensions", fromlist=["x"]).detect_inducement(d),
         pos=None, inv=None, synth=[("ровный", synth_flat, 0, 0)]),
    dict(name="detect_liquidity_void", group="SMC-ext", need="smc",
         call=lambda d: __import__("core.smc.smc_extensions", fromlist=["x"]).detect_liquidity_void(d),
         pos=None, inv=None, synth=[("разрыв", synth_gap, 0, None), ("ровный", synth_flat, 0, 0)]),
    dict(name="detect_breaker_block", group="SMC-ext", need="smc",
         call=lambda d: __import__("core.smc.smc_extensions", fromlist=["x"]).detect_breaker_block(d),
         pos=None, inv=None, synth=[("ровный", synth_flat, 0, 0)]),
    dict(name="find_impulses (impulse_fib)", group="механика", need="raw",
         call=None, pos=_pos_impulse, inv=inv_impulse,
         synth=[("импульс", synth_impulse, 1, None), ("ровный", synth_flat, 0, 0)]),
]


def call_detector(spec, df, d):
    """Единая точка вызова: детекторы принимают разные кадры и разные аргументы."""
    if spec["name"] == "detect_order_blocks":
        m = __import__("core.smc.smc_engine", fromlist=["x"])
        return m.detect_order_blocks(d, m.detect_structure_breaks(d))
    if spec["name"].startswith("find_impulses"):
        from core.smc.impulse_fib import _atr, find_impulses
        dd = df.reset_index(drop=True)
        return list(find_impulses(dd.high.values, dd.low.values, dd.close.values,
                                  _atr(dd).values, len(dd)))
    return spec["call"](d)


def run_one(spec, df):
    d = smc_frame(df)
    n = len(df)
    row = dict(name=spec["name"], group=spec["group"])
    # ── события и частота ──
    try:
        ev = call_detector(spec, df, d)
        row["n_ev"] = len(ev)
    except Exception as e:      # noqa: BLE001
        row["n_ev"] = None; row["err"] = f"{type(e).__name__}: {str(e)[:40]}"
        return row, None
    pos = spec["pos"](ev, n) if spec["pos"] else None
    row["n_bars"] = len(pos) if pos is not None else None
    row["freq_pct"] = round(len(pos) / n * 100, 3) if pos is not None else None
    # ── инвариант ──
    if spec["inv"]:
        try:
            checked, bad = spec["inv"](df, d, ev)
            row["inv_checked"], row["inv_bad"] = checked, len(bad)
            row["inv_ex"] = bad[:2]
        except Exception as e:      # noqa: BLE001
            row["inv_checked"], row["inv_bad"] = 0, None
            row["inv_ex"] = [f"{type(e).__name__}: {str(e)[:34]}"]
    # ── причинность ──
    if spec["pos"]:
        try:
            cut = int(n * 0.7)
            evp = call_detector(spec, df.iloc[:cut], smc_frame(df.iloc[:cut]))
            a = {i for i in spec["pos"](ev, n) if i < cut}
            b = spec["pos"](evp, cut)
            row["cau_full"], row["cau_pref"] = len(a), len(b)
            row["cau_diff"] = len(a ^ b) if (a or b) else None
        except Exception as e:      # noqa: BLE001
            row["cau_diff"] = None
            row["cau_err"] = f"{type(e).__name__}"
    # ── синтетика ──
    marks = []
    for nm, builder, lo, hi in spec.get("synth", []):
        try:
            sdf = builder()
            sev = call_detector(spec, sdf, smc_frame(sdf))
            k = len(sev)
            ok = (k >= lo) and (hi is None or k <= hi)
            marks.append(f"{nm}:{k}{'✅' if ok else '🔴'}")
        except Exception as e:      # noqa: BLE001
            marks.append(f"{nm}:{type(e).__name__}")
    row["synth"] = " ".join(marks)
    return row, (ev, pos)


def verdict(row) -> str:
    if row.get("n_ev") is None:
        return "🔴 НЕ ЗАПУСКАЕТСЯ"
    bads = []
    if row.get("inv_bad"):
        bads.append("инвариант")
    if row.get("inv_bad") is None and "inv_checked" in row:
        bads.append("инвариант н/д")
    if row.get("inv_checked") == 0 and "inv_checked" in row:
        bads.append("инвариант НЕ отработал")
    if row.get("cau_diff"):
        bads.append("причинность")
    if row.get("freq_pct") is not None and row["freq_pct"] > 60:
        bads.append("вырожден")
    if "🔴" in (row.get("synth") or ""):
        bads.append("синтетика")
    return "✅ чист" if not bads else "🔴 " + ", ".join(bads)


def main() -> int:
    ap = argparse.ArgumentParser(description="Большая таблица детекторов")
    ap.add_argument("--symbol", default="ARB/USDT")
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--bars", type=int, default=15000)
    ap.add_argument("--export", action="store_true", help="сохранить события для графиков")
    a = ap.parse_args()

    df = load(a.symbol, a.tf).tail(a.bars)
    print("=" * 132)
    print(f"БОЛЬШАЯ ТАБЛИЦА ДЕТЕКТОРОВ · {a.symbol} · {a.tf} · {len(df)} баров")
    print("Вопрос: ВЕРЕН ли инструмент. Не «выгоден ли» — это другой вопрос.")
    print("=" * 132)
    hdr = (f"{'детектор':<30}{'группа':<10}{'событий':>8}{'баров':>7}{'частота%':>9}"
           f"{'инв.пров':>9}{'наруш':>7}{'прич.расх':>10}  {'синтетика':<22}вердикт")
    print(hdr); print("-" * 132)

    rows, payload = [], {}
    for spec in DETECTORS:
        row, got = run_one(spec, df)
        rows.append(row)
        if a.export and got and got[1]:
            payload[spec["name"]] = sorted(got[1])[:400]
        f = lambda k, d="—": ("—" if row.get(k) is None else row.get(k))   # noqa: E731
        print(f"{row['name']:<30}{row['group']:<10}{str(f('n_ev')):>8}{str(f('n_bars')):>7}"
              f"{str(f('freq_pct')):>9}{str(f('inv_checked')):>9}{str(f('inv_bad')):>7}"
              f"{str(f('cau_diff')):>10}  {(row.get('synth') or '—'):<22}{verdict(row)}")
        for ex in (row.get("inv_ex") or [])[:2]:
            print(f"{'':>30}↳ {ex}")
        if row.get("err"):
            print(f"{'':>30}↳ {row['err']}")

    print("-" * 132)
    clean = sum(1 for r in rows if verdict(r).startswith("✅"))
    print(f"ИТОГО: {len(rows)} детекторов · чистых {clean} · с замечаниями {len(rows)-clean}")
    print("\n🔑 «0 нарушений» при НУЛЕ проверенных — это НЕ успех, а несработавший тест.")
    print("   Столбец «инв.пров» показывает, сколько событий реально проверено.")

    if a.export:
        out = ROOT / "cache" / "detector_bench.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"symbol": a.symbol, "tf": a.tf,
                                   "events": payload}, ensure_ascii=False), encoding="utf-8")
        print(f"\nсобытия для графиков → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
