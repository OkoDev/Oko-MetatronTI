# -*- coding: utf-8 -*-
"""ЖУРНАЛ ОБЩЕГО СОСТОЯНИЯ СФЕР НА ИСТОРИИ (Егор 07.10: «искать нужно не отдельно в WT, SMC или
пивотах, а вместе… при WT OS есть ли SMC-наборы интересные, что в состояниях пивотов и где мы в волне
или OTE… всё должно быть связано со всем»).

В живой шине это состояние ЕСТЬ, но не пишется ([[joint_state_on_bus_not_journaled]]). Здесь — то же
самое на истории: КАЖДЫЙ закрытый час КАЖДОЙ монеты, все сферы в одной строке, плюс исходы вперёд.
Это полный поток, а не сделки одной механики — на нём любой триггер проверяется на «набор победителей».

Строка = закрытый 1h-бар `ts` (время ОТКРЫТИЯ, UTC). Всё известно к его ЗАКРЫТИЮ `ts + 1h`;
вход — по open следующего бара.
  · матрица харнесса `mtf_flags(1h)`: SMC · пивоты · WT-флаги · дивергенции · ATR-тренд · две структуры ·
    ноги — на 1h и со старших 4h/1d (старший только с ЗАКРЫТОГО бара, `shift(1)`)
  · WT значения: wt1/wt2 на 1h · 4h · 1d (старшие — с закрытого бара)
  · ВОЛНА ЯДРА (4h из тех же 1h, боевые WaveParams, причинно на закрытом баре): какая пятёрка видна —
    сторона сетапа, core/core_full, глубина, импульс, возраст, ОТКАТ цены от пятой к началу импульса
    (0 — у пятой, 1 — у начала; 0.618–0.79 = OTE волны), путь к цели волны 4
  · режим: дрейф вселенной 30/90 дн, доля растущих, BTC 90 дн — значение ПРОШЛОГО дня
  · позиционирование Binance: long/short розницы и топов, агрессор, ΔOI 4h/24h — строго ДО закрытия бара
  · оборот (медиана 30 дн, без текущего бара), ATR% 1h
  · ИСХОДЫ (валовые, % для лонга; шорт = минус): fwd_4/24/72 ч, mfe_24/mae_24

Запуск:  python scripts/joint_state_journal.py run [процессов]
         python scripts/joint_state_journal.py check [монет]   — префиксный тест причинности
             🔴 на случайных часах: РЕДКИЕ флаги он не ловит (07.10 пропустил hh/ll/elliott/inducement,
             которые дали +5…+8% и прошли всю статистику) → матрицу проверять
             `scripts/matrix_causality_scan.py` (прицельно, на барах где флаг =1)
         python scripts/joint_state_journal.py stat            — инвентаризация
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
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

OUT = Path("G:/oko_lab/joint/1h")
MET = Path("C:/oko_data/history/metrics")
MIN_BARS = 2000                            # ~3 месяца 1h: новые листинги тоже в потоке
DRIFT = Path("G:/oko_lab/out/universe_drift_daily.pkl")
T0 = pd.Timestamp("2023-01-01")
HORIZONS = (4, 24, 72)
WAVE_MAX_AGE = pd.Timedelta(days=10)       # как wave_phase_context: не старше 60 баров 4h


def _key(sym: str) -> str:
    return sym.replace("/", "").replace(":USDT", "")


def _wt_block(df: pd.DataFrame) -> pd.DataFrame:
    from core.indicators.indicators import calculate_wt
    out = {}
    w = calculate_wt(df.reset_index(drop=True).copy())
    out["wt1_1h"], out["wt2_1h"] = w["wt1"].values, w["wt2"].values
    for tf, rule in (("4h", "4h"), ("1d", "1D")):
        agg = df.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                     "close": "last", "volume": "sum"}).dropna()
        ww = calculate_wt(agg.reset_index(drop=True).copy())
        s = pd.DataFrame({"a": ww["wt1"].values, "b": ww["wt2"].values}, index=agg.index)
        s = s.shift(1).reindex(df.index, method="ffill")          # только ЗАКРЫТЫЙ старший бар
        out[f"wt1_{tf}"], out[f"wt2_{tf}"] = s["a"].values, s["b"].values
    return pd.DataFrame(out, index=df.index)


def _wave_ctx(df: pd.DataFrame) -> pd.DataFrame:
    """Какую пятёрку ядро видит на каждом закрытом 4h-баре — логика `wave_phase_context` (21.09),
    но 4h собирается из ТЕХ ЖЕ 1h, что и матрица: один источник, полная вселенная, и префиксный тест
    журнала проверяет волны вместе со всем остальным. Параметры — боевые (`WaveParams()` = тень)."""
    from core.waves.wave5_core import WaveParams, _setups_at
    from core.smc.oko_sm_engine import run_structure, pivot_points
    from core.indicators.indicators import calculate_wt
    p = WaveParams()
    dh = df.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                "close": "last", "volume": "sum"}).dropna()
    dh.index = dh.index.tz_convert(None)
    if len(dh) < 6 * p.sw + 60:
        return pd.DataFrame()
    idx_h = dh.index
    hh, lh = dh.high.values.astype(float), dh.low.values.astype(float)
    dhr = dh.reset_index(drop=True)
    st = run_structure(dhr[["open", "high", "low", "close"]], swing_len=p.sw, internal_len=p.il)
    swings, swings_i = pivot_points(dhr["high"], dhr["low"], p.sw), pivot_points(dhr["high"], dhr["low"], p.il)
    wt1_h = calculate_wt(dhr.copy())["wt1"].values.astype(float)
    start = max(6 * p.sw + 50, int(np.searchsorted(idx_h, (T0 - WAVE_MAX_AGE - pd.Timedelta("4h")).to_datetime64())))
    rows = []
    for tt in range(start, len(dhr)):
        try:
            out = _setups_at(tt, dh, idx_h, hh, lh, st, swings, swings_i, wt1_h, [], [],
                             np.array([np.nan]), 240, idx_h[tt] + pd.Timedelta(hours=4), p, "4h")
        except Exception:                                # noqa: BLE001
            continue
        for s in out:
            rows.append({"tt": tt, "time": idx_h[tt], "side": s["side"], "p0": s["p0"], "p5": s["p5"],
                         "p4": s["p4_target"], "top_time": s["top_time"], "core": s["core"],
                         "core_full": s["core_full"], "depth5": s["depth5"], "imp_pct": s["imp_pct"]})
    return pd.DataFrame(rows)


def _wave_block(sym: str, df: pd.DataFrame) -> pd.DataFrame:
    cols = ["w_side", "w_core", "w_core_full", "w_depth5", "w_imp_pct", "w_age_h", "w_retr", "w_to_p4"]
    empty = pd.DataFrame(np.nan, index=df.index, columns=cols)
    W = _wave_ctx(df)
    if W.empty:
        return empty
    # на одном 4h-баре ядро может видеть несколько пятёрок → берём самую свежую (полное ядро вперёд)
    W = (W.assign(cf=W.core_full.astype(int))
          .sort_values(["tt", "top_time", "cf"]).groupby("tt").tail(1))
    W = W.assign(visible=pd.to_datetime(W.time) + pd.Timedelta("4h")).sort_values("visible")
    L = pd.DataFrame({"tc": df.index.tz_convert(None) + pd.Timedelta("1h"), "close": df.close.values})
    M = pd.merge_asof(L, W, left_on="tc", right_on="visible", direction="backward",
                      tolerance=WAVE_MAX_AGE)
    side = np.where(M.side == "LONG", 1.0, np.where(M.side == "SHORT", -1.0, np.nan))
    span = (M.p0 - M.p5).values
    out = pd.DataFrame({
        "w_side": side,
        "w_core": M.core.astype(float).values,
        "w_core_full": M.core_full.astype(float).values,
        "w_depth5": M.depth5.values, "w_imp_pct": M.imp_pct.values,
        "w_age_h": (M.tc - pd.to_datetime(M.top_time)).dt.total_seconds().values / 3600,
        # откат от пятой к началу импульса: 0 — у пятой, 1 — у начала (знак учитывает направление)
        "w_retr": np.where(span != 0, (M.close.values - M.p5.values) / span, np.nan),
        "w_to_p4": np.where((M.p4 - M.p5).values != 0,
                            (M.close.values - M.p5.values) / (M.p4 - M.p5).values, np.nan),
    }, index=df.index)
    return out


def _regime_block(df: pd.DataFrame) -> pd.DataFrame:
    D = pd.read_pickle(DRIFT)
    D.index = pd.to_datetime(D.index)
    D = D.add_prefix("mkt_")
    D["avail"] = D.index + pd.Timedelta(days=1)      # значение дня D известно с начала D+1
    L = pd.DataFrame({"tc": df.index.tz_convert(None) + pd.Timedelta("1h")})
    M = pd.merge_asof(L, D.sort_values("avail"), left_on="tc", right_on="avail", direction="backward")
    return pd.DataFrame({c: M[c].values for c in D.columns if c.startswith("mkt_")}, index=df.index)


def _positioning_block(sym: str, df: pd.DataFrame) -> pd.DataFrame:
    cols = ["pos_retail_ls", "pos_top_ls", "pos_taker", "pos_doi_4h", "pos_doi_24h"]
    f = MET / f"{_key(sym)}.parquet"
    if not f.exists():
        return pd.DataFrame(np.nan, index=df.index, columns=cols)
    m = pd.read_parquet(f).sort_values("time").reset_index(drop=True)
    m["mt"] = pd.to_datetime(m.time, unit="ms")
    oi = m.sum_open_interest.astype(float)
    m["pos_doi_4h"] = (oi / oi.shift(48) - 1) * 100
    m["pos_doi_24h"] = (oi / oi.shift(288) - 1) * 100
    m = m.rename(columns={"count_long_short_ratio": "pos_retail_ls",
                          "count_toptrader_long_short_ratio": "pos_top_ls",
                          "sum_taker_long_short_vol_ratio": "pos_taker"})
    L = pd.DataFrame({"tc": df.index.tz_convert(None) + pd.Timedelta("1h")})
    M = pd.merge_asof(L, m[["mt"] + cols], left_on="tc", right_on="mt", direction="backward",
                      allow_exact_matches=False, tolerance=pd.Timedelta("30min"))   # СТРОГО до закрытия
    return pd.DataFrame({c: M[c].values for c in cols}, index=df.index)


def _misc_block(df: pd.DataFrame) -> pd.DataFrame:
    h, l, c, o = df.high, df.low, df.close, df.open
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    turn = (c * df.volume).rolling(720, min_periods=240).median().shift(1)
    e = o.shift(-1)                                   # вход: open следующего бара
    out = {"close": c.values, "atr_pct": (atr / c * 100).values, "liq": turn.values}
    for H in HORIZONS:
        out[f"fwd_{H}"] = ((c.shift(-H) - e) / e * 100).values
    hi24 = h[::-1].rolling(24, min_periods=24).max()[::-1].shift(-1)
    lo24 = l[::-1].rolling(24, min_periods=24).min()[::-1].shift(-1)
    out["mfe_24"] = ((hi24 - e) / e * 100).values
    out["mae_24"] = ((lo24 - e) / e * 100).values
    return pd.DataFrame(out, index=df.index)


def build(sym: str, df: pd.DataFrame | None = None) -> pd.DataFrame:
    from research_harness import load, mtf_flags
    if df is None:
        df = load(sym, "1h")
    F = mtf_flags(df, "1h")
    J = pd.concat([F, _wt_block(df), _wave_block(sym, df), _regime_block(df),
                   _positioning_block(sym, df), _misc_block(df)], axis=1)
    J = J.loc[J.index >= T0.tz_localize("UTC")]
    num = J.select_dtypes(include=["number", "bool"]).columns
    J[num] = J[num].astype("float32")
    J.insert(0, "sym", sym)
    J.index = J.index.tz_convert(None)
    J.index.name = "ts"
    return J


def run_symbol(sym: str) -> str:
    out = OUT / f"{_key(sym)}.parquet"
    if out.exists():
        return f"{sym}: есть"
    import logging
    logging.disable(logging.CRITICAL)
    t0 = time.time()
    try:
        J = build(sym)
    except Exception as e:                               # noqa: BLE001
        return f"{sym}: 🔴 {type(e).__name__}: {str(e)[:80]}"
    J.to_parquet(out)
    return f"{sym}: {len(J)} строк · {J.shape[1]} колонок · {time.time() - t0:.0f} с"


def universe() -> list[str]:
    """Вся вселенная 1h-кэша с историей ≥2000 баров (~3 мес). Егор 07.10: «228 монет ?!» —
    первая версия брала только монеты с готовым волновым контекстом; теперь волны считаются здесь."""
    from research_harness import universe as U
    # в кэше есть дубли с префиксом биржи ('binance:HYPE/USDT', 'bingx:BTC/USDT:USDT') — 40 шт.,
    # монеты те же; двоеточие в имени файла на Windows — ещё и ловушка
    return [s for s in U("1h", min_bars=MIN_BARS, n=10_000) if ":" not in s.split("/")[0]]


def run(procs: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    syms = universe()
    print(f"монет: {len(syms)} (1h-кэш ∩ волновой контекст) · процессов {procs}", flush=True)
    t0 = time.time()
    with Pool(procs) as pool:
        for i, r in enumerate(pool.imap_unordered(run_symbol, syms), 1):
            if i % 10 == 0 or "🔴" in r:
                print(f"  [{i}/{len(syms)} · {time.time() - t0:.0f} с] {r}", flush=True)
    print(f"готово за {time.time() - t0:.0f} с", flush=True)


def check(n_coins: int = 3, cuts: int = 3) -> None:
    """Префиксный тест: журнал, собранный по истории, ОБРЕЗАННОЙ на баре t, обязан совпасть в строке t
    с журналом по полной истории — во ВСЕХ колонках признаков (исходы, естественно, исключены)."""
    from research_harness import load
    rng = np.random.default_rng(7)
    syms = universe()
    bad_total = {}
    for sym in rng.choice(syms, n_coins, replace=False):
        df = load(sym, "1h")
        full = build(sym, df)
        feats = [c for c in full.columns if c != "sym" and not c.startswith(("fwd_", "mfe_", "mae_"))]
        for cut in rng.integers(int(len(df) * 0.55), len(df) - 100, cuts):
            part = build(sym, df.iloc[:cut + 1])
            t = part.index[-1]
            # харнесс не строит старший блок, если старших баров <300 (короткая история) —
            # это отсутствие колонок, а не расхождение значений; считаем отдельно
            common = [f for f in feats if f in part.columns]
            a, b = part.loc[t, common].astype(float), full.loc[t, common].astype(float)
            diff = ~(np.isclose(a.values, b.values, rtol=1e-4, atol=1e-5, equal_nan=True))
            names = [f for f, d in zip(common, diff) if d]
            for nm in names:
                bad_total[nm] = bad_total.get(nm, 0) + 1
            print(f"  {sym} @ {t}: колонок {len(common)} · расходится {len(names)}"
                  + (f" · нет в обрезке {len(feats) - len(common)} (короткая история старшего ТФ)"
                     if len(common) < len(feats) else "")
                  + (f" → {names[:8]}" if names else ""), flush=True)
    print(f"\nИТОГ: расходящихся колонок {len(bad_total)}" + (f": {sorted(bad_total)[:30]}" if bad_total else " ✅"))


def stat() -> None:
    files = sorted(OUT.glob("*.parquet"))
    n, cols, first, last, cov = 0, None, None, None, {}
    for f in files:
        J = pd.read_parquet(f, columns=["sym", "w_side", "pos_retail_ls", "fwd_24", "mkt_drift30"])
        n += len(J)
        first = J.index.min() if first is None else min(first, J.index.min())
        last = J.index.max() if last is None else max(last, J.index.max())
        for c in ("w_side", "pos_retail_ls", "fwd_24", "mkt_drift30"):
            cov[c] = cov.get(c, 0) + J[c].notna().sum()
    if files:
        cols = pd.read_parquet(files[0]).shape[1]
    print(f"монет {len(files)} · строк {n:,} · колонок {cols} · {first} → {last}")
    for c, k in cov.items():
        print(f"  заполнено {c:<16} {k / max(n, 1) * 100:5.1f}%")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stat"
    if cmd == "run":
        run(int(sys.argv[2]) if len(sys.argv) > 2 else max(1, (os.cpu_count() or 2) - 4))
        stat()
    elif cmd == "check":
        check(int(sys.argv[2]) if len(sys.argv) > 2 else 3)
    else:
        stat()
