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
UNIVERSE_DB = ROOT / "oko_feed" / "universe.db"            # живой дрейф (задача universe-drift)
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
                         "core_full": s["core_full"], "depth5": s["depth5"], "imp_pct": s["imp_pct"],
                         "t0": idx_h[int(s["a"])]})          # начало импульса — якорь ноги старшей степени
    return pd.DataFrame(rows)


def _degree_legs(df: pd.DataFrame, W: pd.DataFrame) -> pd.DataFrame:
    """НОГА СТАРШЕЙ СТЕПЕНИ для каждой пятёрки (08.10, Егор: «будем видеть одну ногу в другой?» — да).
    Та же постановка, что разбор и тень: дневная нога, которую корректирует 4h-импульс — свинг ДО начала
    импульса (t0) и ЗА экстремумом пятой (p5), конец ноги — до вершины пятой. Считается ОДИН раз на пятёрку,
    в момент, когда ядро её впервые увидело (only закрытые дни/4h к этому моменту) — без заглядывания.
    Текущая нога (`_leg_block`, как шина) — младшая степень: при видимой пятёрке она обычно та, на вершине
    которой начался сам импульс, и её глубина ~1 почти по определению (SKR 08.10: 1.09 против 0.66)."""
    from core.waves.wave_analyst import daily_leg
    d = df.copy()
    d.index = d.index.tz_convert(None)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    d4, dd = d.resample("4h").agg(agg).dropna(), d.resample("1D").agg(agg).dropna()
    first = W.sort_values("visible").drop_duplicates(["t0", "top_time", "side"], keep="first")
    rows = []
    for _, s in first.iterrows():
        now = s.visible
        ddc, d4c = dd[dd.index + pd.Timedelta(days=1) <= now], d4[d4.index + pd.Timedelta("4h") <= now]
        L = None
        if len(ddc) >= 40 and not d4c.empty:
            try:
                L = daily_leg(d4c, pd.Timestamp(s.t0), s.side == "SHORT", float(s.p5),
                              pd.Timestamp(s.top_time), now, dd=ddc)
            except Exception:                            # noqa: BLE001
                L = None
        rows.append({"t0": s.t0, "top_time": s.top_time, "side": s.side,
                     "leg_o": L["origin"] if L else np.nan, "leg_e": L["ext"] if L else np.nan,
                     "leg_d5": L["depth"] if L else np.nan})
    return pd.DataFrame(rows)


def _wave_block(sym: str, df: pd.DataFrame) -> pd.DataFrame:
    cols = ["w_side", "w_core", "w_core_full", "w_depth5", "w_imp_pct", "w_age_h", "w_retr", "w_to_p4",
            "w_retr_band", "w_in_ote", "w_leg_origin", "w_leg_ext", "w_leg_depth5", "w_leg_band", "w_leg_in_ote",
            "w_leg_depth_now"]
    empty = pd.DataFrame(np.nan, index=df.index, columns=cols)
    W = _wave_ctx(df)
    if W.empty:
        return empty
    # на одном 4h-баре ядро может видеть несколько пятёрок → берём самую свежую (полное ядро вперёд)
    W = (W.assign(cf=W.core_full.astype(int))
          .sort_values(["tt", "top_time", "cf"]).groupby("tt").tail(1))
    W = W.assign(visible=pd.to_datetime(W.time) + pd.Timedelta("4h")).sort_values("visible")
    G = _degree_legs(df, W)
    W = W.merge(G, on=["t0", "top_time", "side"], how="left").sort_values("visible")
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
    # канон OTE на откате волны: корзина 0..4 как у дневной ноги; −1 — цена ЗА пятой (откат ещё не начался)
    from core.smc.fibonacci import ote_band_code, in_ote
    r = out.w_retr.values
    out["w_retr_band"] = np.array([np.nan if not np.isfinite(x) else (-1.0 if x < 0 else ote_band_code(x)) for x in r])
    out["w_in_ote"] = np.array([np.nan if not np.isfinite(x) else float(in_ote(x)) for x in r])
    # нога СТАРШЕЙ степени: где закончилась пятая (фиксировано на пятёрку) и где цена сейчас
    o, e = M.leg_o.values.astype(float), M.leg_e.values.astype(float)
    d5 = M.leg_d5.values.astype(float)
    sp = np.abs(o - e)
    out["w_leg_origin"], out["w_leg_ext"], out["w_leg_depth5"] = o, e, d5
    out["w_leg_band"] = np.array([np.nan if not np.isfinite(x) else ote_band_code(x) for x in d5])
    out["w_leg_in_ote"] = np.array([np.nan if not np.isfinite(x) else float(in_ote(x)) for x in d5])
    out["w_leg_depth_now"] = np.where(sp > 0, np.abs(M.close.values - e) / sp, np.nan)
    return out


def _leg_block(df: pd.DataFrame) -> pd.DataFrame:
    """ДНЕВНАЯ НОГА + КАНОН OTE (v2, Егор 07.10: «где мы в волне или OTE»). Та же функция, что поля шины
    `wave_leg_up/dn` (`core.waves.wave_analyst.daily_leg`), и канон корзин `core.smc.fibonacci.ote_band_code`
    (0 мелкая <0.5 · 1 0.5–0.62 · 2 OTE 0.62–0.79 · 3 глубокая 0.79–1.0 · 4 за пределами).
    up — нога вверх (откат вниз = контекст ЛОНГА), dn — нога вниз (откат вверх = контекст ШОРТА).
    🔴 Отличие от бота: нога берётся на закрытии ДНЯ (бот обновляет на каждом закрытом 4h), глубина цены в ноге —
    каждый час. Причинно: только закрытые дни и 4h до `now`."""
    from core.waves.wave_analyst import daily_leg
    from core.smc.fibonacci import ote_band_code, in_ote
    cols = [f"leg{d}_{k}" for d in ("up", "dn") for k in ("depth", "band", "in_ote", "span_pct")]
    d = df.copy()
    d.index = d.index.tz_convert(None)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    d4 = d.resample("4h").agg(agg).dropna()
    dd = d.resample("1D").agg(agg).dropna()
    rows = []
    for D in dd.index[dd.index >= T0 - pd.Timedelta(days=2)]:
        now = D + pd.Timedelta(days=1)
        ddc, d4c = dd[dd.index + pd.Timedelta(days=1) <= now], d4[d4.index + pd.Timedelta("4h") <= now]
        if len(ddc) < 40 or d4c.empty:
            continue
        px = float(d4c.close.iloc[-1])
        r = {"now": now}
        for key, want_top in (("up", False), ("dn", True)):
            try:
                L = daily_leg(d4c, now, want_top, px, now, now, dd=ddc)
            except Exception:                            # noqa: BLE001
                L = None
            r[f"{key}_o"], r[f"{key}_e"] = (L["origin"], L["ext"]) if L else (np.nan, np.nan)
        rows.append(r)
    if not rows:
        return pd.DataFrame(np.nan, index=df.index, columns=cols)
    R = pd.DataFrame(rows).sort_values("now")
    Lh = pd.DataFrame({"tc": d.index + pd.Timedelta("1h"), "close": d.close.values})
    M = pd.merge_asof(Lh, R, left_on="tc", right_on="now", direction="backward")
    out = {}
    for key in ("up", "dn"):
        o, e, c = M[f"{key}_o"].values, M[f"{key}_e"].values, M.close.values
        span = np.abs(o - e)
        dep = np.where(span > 0, np.abs(c - e) / span, np.nan)
        out[f"leg{key}_depth"] = dep
        out[f"leg{key}_band"] = np.array([ote_band_code(x) if np.isfinite(x) else np.nan for x in dep])
        out[f"leg{key}_in_ote"] = np.array([float(in_ote(x)) if np.isfinite(x) else np.nan for x in dep])
        out[f"leg{key}_span_pct"] = np.where(np.isfinite(e) & (e > 0), span / e * 100, np.nan)
    return pd.DataFrame(out, index=df.index)[cols]


def _drift_daily() -> pd.DataFrame:
    """Дрейф вселенной по дням: история — `universe_drift_daily.pkl` (2022→15.09.2026), дальше — живая база
    задачи universe-drift (`oko_feed/universe.db`, обновляется ежечасно). Определение одно: на 245 общих днях
    корр drift30 = 1.0, средняя разница 0.27 п.п. (состав вселенной 470 против 437). share_up90/btc90 есть только
    в истории — для новых дней пусто, а не протянуто."""
    D = pd.read_pickle(DRIFT)
    D.index = pd.to_datetime(D.index)
    try:
        import sqlite3
        with sqlite3.connect(f"file:{UNIVERSE_DB.as_posix()}?mode=ro", uri=True) as c:
            U = pd.read_sql("SELECT day, drift30, drift90, n_coins AS n FROM universe_drift", c, index_col="day")
        U.index = pd.to_datetime(U.index)
        D = pd.concat([D, U[U.index > D.index.max()]])
    except Exception:                                    # noqa: BLE001
        pass
    return D


def _regime_block(df: pd.DataFrame) -> pd.DataFrame:
    D = _drift_daily().add_prefix("mkt_")
    D["avail"] = D.index + pd.Timedelta(days=1)      # значение дня D известно с начала D+1
    L = pd.DataFrame({"tc": df.index.tz_convert(None) + pd.Timedelta("1h")})
    # 🔴 08.10: без допуска значение 15.09 тихо тянулось на недели вперёд — устаревший режим = пусто
    M = pd.merge_asof(L, D.sort_values("avail"), left_on="tc", right_on="avail", direction="backward",
                      tolerance=pd.Timedelta(days=3))
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


GEO = {"tight": (1.5, 3.0), "wide": (4.0, 8.0)}   # стоп и цель в ATR(1h,14); горизонт GEO_H
GEO_H = 72


def _geo_block(df: pd.DataFrame) -> pd.DataFrame:
    """ИСХОД ПО СТОПУ И ЦЕЛИ (v2, Егор 07.10: «что даст?» → деньги, близкие к торговле). Фиксированный
    горизонт масштабирует доход волатильностью — на этом держалась «капитуляция». Здесь: вход по open
    следующего бара, стоп/цель = k·ATR от входа, первое касание; стоп и цель на одном баре → СТОП
    (худший случай); не коснулось за GEO_H ч → выход по close. Валовые %, отдельно лонг и шорт."""
    h, l, c = df.high.values, df.low.values, df.close.values
    tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(),
                    (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().values
    n = len(df)
    e = np.r_[df.open.values[1:], np.nan]                 # вход: open следующего бара
    out = {}
    for nm, (ks, kt) in GEO.items():
        for side, sg in (("long", 1.0), ("short", -1.0)):
            stop, tgt = e - sg * ks * atr, e + sg * kt * atr
            res = np.full(n, np.nan)
            done = np.zeros(n, bool)
            for k in range(1, GEO_H + 1):
                j = np.arange(n) + k
                ok = (j < n) & ~done & np.isfinite(e) & np.isfinite(atr)
                if not ok.any():
                    break
                jj = np.minimum(j, n - 1)
                hit_s = ok & ((l[jj] <= stop) if sg > 0 else (h[jj] >= stop))
                hit_t = ok & ~hit_s & ((h[jj] >= tgt) if sg > 0 else (l[jj] <= tgt))
                res[hit_s] = sg * (stop[hit_s] - e[hit_s]) / e[hit_s] * 100
                res[hit_t] = sg * (tgt[hit_t] - e[hit_t]) / e[hit_t] * 100
                done |= hit_s | hit_t
                if k == GEO_H:
                    tm = ok & ~done
                    res[tm] = sg * (c[jj][tm] - e[tm]) / e[tm] * 100
            out[f"geo_{nm}_{side}"] = res
    return pd.DataFrame(out, index=df.index)


def _ltf_block(df: pd.DataFrame, d15: pd.DataFrame | None) -> pd.DataFrame:
    """LTF 15m ВНУТРИ ЧАСА (v2, Егор 07.10: «а LTF мы не собираем?»). На закрытии часа t+1h закрыт и
    последний 15m-бар часа (открытие t+45m) → его WT/ATR-тренд причинны. Плюс события ЗА час:
    кросс wt1×wt2 вверх/вниз, вход в OS/OB. Только бары 15m, закрывшиеся до конца последнего часа df."""
    cols = ["wt1_15m", "wt2_15m", "wt_os_15m_now", "wt_ob_15m_now", "atr_trend_15m",
            "wt_cross_up_15m_in_h", "wt_cross_dn_15m_in_h", "wt_enter_os_15m_in_h", "wt_enter_ob_15m_in_h"]
    if d15 is None or d15.empty:
        return pd.DataFrame(np.nan, index=df.index, columns=cols)
    from core.indicators.indicators import calculate_wt, calculate_trend
    end = df.index[-1] + pd.Timedelta("1h")
    d15 = d15[d15.index + pd.Timedelta("15min") <= end]
    w = calculate_trend(calculate_wt(d15.reset_index(drop=True).copy()), atr_period=43, factor=1.25)
    w1, w2, tr = w["wt1"].values, w["wt2"].values, w["trend"].values
    up = np.r_[False, (w1[1:] > w2[1:]) & (w1[:-1] <= w2[:-1])]
    dn = np.r_[False, (w1[1:] < w2[1:]) & (w1[:-1] >= w2[:-1])]
    eos = np.r_[False, (w1[1:] < -60) & (w1[:-1] >= -60)]
    eob = np.r_[False, (w1[1:] > 60) & (w1[:-1] <= 60)]
    s = pd.DataFrame({"wt1_15m": w1, "wt2_15m": w2, "wt_os_15m_now": (w1 < -60).astype(float),
                      "wt_ob_15m_now": (w1 > 60).astype(float), "atr_trend_15m": tr,
                      "up": up, "dn": dn, "eos": eos, "eob": eob}, index=d15.index)
    hour = s.index.floor("1h")
    last = s.groupby(hour)[["wt1_15m", "wt2_15m", "wt_os_15m_now", "wt_ob_15m_now", "atr_trend_15m"]].last()
    ev = s.groupby(hour)[["up", "dn", "eos", "eob"]].max().astype(float)
    ev.columns = ["wt_cross_up_15m_in_h", "wt_cross_dn_15m_in_h", "wt_enter_os_15m_in_h", "wt_enter_ob_15m_in_h"]
    full = pd.concat([last, ev], axis=1)
    # час неполный (нет 4 баров 15m) — значения «последнего» бара не на закрытии часа → NaN
    cnt = s.groupby(hour).size()
    full[cnt.reindex(full.index) < 4] = np.nan
    return full.reindex(df.index)[cols]


def build(sym: str, df: pd.DataFrame | None = None, d15: pd.DataFrame | None = None) -> pd.DataFrame:
    from research_harness import load, mtf_flags
    if df is None:
        df = load(sym, "1h")
    if d15 is None:
        try:
            d15 = load(sym, "15m")
        except Exception:                                # noqa: BLE001
            d15 = None
    F = mtf_flags(df, "1h")
    J = pd.concat([F, _wt_block(df), _ltf_block(df, d15), _wave_block(sym, df), _leg_block(df), _regime_block(df),
                   _positioning_block(sym, df), _misc_block(df), _geo_block(df)], axis=1)
    J = J.loc[J.index >= T0.tz_localize("UTC")]
    num = J.select_dtypes(include=["number", "bool"]).columns
    J[num] = J[num].astype("float32")
    J.insert(0, "sym", sym)
    J.index = J.index.tz_convert(None)
    J.index.name = "ts"
    return J


def run_symbol(sym: str, force: bool = False) -> str:
    out = OUT / f"{_key(sym)}.parquet"
    if out.exists() and not force:
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


def run(procs: int, force: bool = False) -> None:
    """force=True — пересобрать всё (ежедневный прогон после докачки: журнал причинен, полная пересборка
    даёт то же, что дописывание, без логики стыков)."""
    from functools import partial
    OUT.mkdir(parents=True, exist_ok=True)
    syms = universe()
    print(f"монет: {len(syms)} · процессов {procs} · {'ПЕРЕСБОРКА' if force else 'только новые'}", flush=True)
    t0 = time.time()
    with Pool(procs) as pool:
        for i, r in enumerate(pool.imap_unordered(partial(run_symbol, force=force), syms), 1):
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
        feats = [c for c in full.columns if c != "sym" and not c.startswith(("fwd_", "mfe_", "mae_", "geo_"))]
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
        args = [a for a in sys.argv[2:] if a != "--force"]
        run(int(args[0]) if args else max(1, (os.cpu_count() or 2) - 4), force="--force" in sys.argv)
        stat()
    elif cmd == "check":
        check(int(sys.argv[2]) if len(sys.argv) > 2 else 3)
    else:
        stat()
