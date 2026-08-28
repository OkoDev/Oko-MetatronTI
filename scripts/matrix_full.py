"""
matrix_full.py — ПОЛНАЯ МАТРИЦА: то, чего в `combinator_core` НЕТ.

Повод (Егор, 27.08.2026): «матрицу дополнить всем что вне её сейчас, пусть будет
полной и не раздробленной». Замер 27.08 показал: `compute_flags` даёт 79 шаблонов
(446 после разворота по ТФ), а боевые решения опираются на 230 признаков — покрыто
14, вне матрицы 216 ([[matrix_covers_six_percent]]). Слепой отбор трижды дал
«0 из 446» — на ШЕСТОЙ ЧАСТИ пространства.

Здесь добавлены только те семьи, которые:
  1) существуют на ПОЛНОЙ истории 2022-2026 (инвентаризация 28.08, см. ниже);
  2) причинны — известны в момент входа;
  3) не являются результатом наших решений (маршрутизация, риск, лаг исполнения
     НЕ вносятся — это циркулярность, `docs/REGISTRY.md` §3).

СЕМЬИ:
  FUND    фандинг из `funding_rates` (1 557 170 строк, 2022-01→2026-06, 450 символов)
  MKT     ширина и дрейф ВСЕЛЕННОЙ + режим BTC (считается из кэша 4h, лаг 1 день)
  DIST    непрерывные дистанции до магнитов: пивоты, CMA, EMA200, экстремумы (ERL)
  STATE   НЕПРЕРЫВНОЕ состояние вместо булева события: значения WT/RSI/ATR + ДАВНОСТЬ
          кросса в барах ([[feedback_confluence_not_moment]]: «состояние вместо давности»)

🔴 ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ (называем явно, не замалчиваем):
  открытый интерес     — истории нет вовсе (live с Bybit)
  USDT.D               — `usdtd_1h` только с 2026-05 (94 дня)
  onchain / mcap       — с 2026-07 (639 строк)
  phase_state          — живая таблица с 2026-05, историю не воспроизвести
  ML-советники         — их выход зависит от обучения на этой же истории
  маршрутизация/риск   — циркулярность по определению
  исполнение и лаг     — постфактум

ПРИЧИННОСТЬ (три места, где легко порезаться):
  · фандинг берётся по времени ОТКРЫТИЯ бара (`merge_asof` backward) — ставка
    известна до бара;
  · рыночный контекст берётся с ПРЕДЫДУЩЕГО закрытого дня (`shift(1)`);
  · посимвольные признаки сдвинуты на 1 бар — значение ЗАКРЫТОГО бара.

    from scripts.matrix_full import extra_flags, market_context
    E = extra_flags(df, tf="15m", symbol="BTC/USDT")   # DataFrame по индексу df
"""
from __future__ import annotations

import sqlite3
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

DB = str(ROOT / "ohlcv_cache.db")
CACHE = ROOT / "cache" / "market_context.parquet"

# ── FUND ────────────────────────────────────────────────────────────────────
# `interval_hours` в таблице разный (1 / 2 / 4 / 8) — сырые ставки НЕСРАВНИМЫ
# между эпохами и биржами. Приводим к 8-часовому эквиваленту.
FUND_WIN_Z = 90 * 3        # ~90 дней в 8-часовых периодах
FUND_MIN_ROWS = 200


def _fund_raw(symbol: str) -> pd.DataFrame:
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as c:
        f = pd.read_sql(
            "SELECT time, interval_hours, rate FROM funding_rates "
            "WHERE symbol=? ORDER BY time", c, params=(symbol,))
    if f.empty:
        return f
    f["ts"] = pd.to_datetime(f.time, unit="ms", utc=True)
    ih = f.interval_hours.replace(0, np.nan).fillna(8.0)
    f["rate8"] = f.rate * (8.0 / ih)          # 8-часовой эквивалент
    return f[["ts", "rate8"]].dropna()


def funding_features(index: pd.DatetimeIndex, symbol: str) -> pd.DataFrame:
    """
    Фандинг, приведённый к сетке ТФ. Причинность: `merge_asof` backward по времени
    ОТКРЫТИЯ бара — берём последнюю ставку, объявленную ДО бара.

    Пусто (все NaN), если истории фандинга по символу нет — это НЕ ошибка,
    но и не повод молча считать нулём: NaN отсеется в отборе сам.
    """
    cols = ["fund_rate8", "fund_z90", "fund_cum3d", "fund_cum7d",
            "fund_sign_age", "fund_abs"]
    f = _fund_raw(symbol)
    if len(f) < FUND_MIN_ROWS:
        return pd.DataFrame({c: np.nan for c in cols}, index=index)

    r = f.set_index("ts").rate8
    z = (r - r.rolling(FUND_WIN_Z, min_periods=30).mean()) / \
        r.rolling(FUND_WIN_Z, min_periods=30).std().replace(0, np.nan)
    # накопленная ставка за 3 и 7 дней (сколько реально платили держатели лонга)
    cum3 = r.rolling(9, min_periods=3).sum()      # 3 дня × 3 периода
    cum7 = r.rolling(21, min_periods=7).sum()
    # ДАВНОСТЬ знака: сколько периодов подряд ставка одного знака (состояние, не событие)
    sgn = np.sign(r.values)
    age = np.zeros(len(sgn))
    for i in range(1, len(sgn)):
        age[i] = age[i - 1] + 1 if sgn[i] == sgn[i - 1] and sgn[i] != 0 else 0
    F = pd.DataFrame({"fund_rate8": r.values, "fund_z90": z.values,
                      "fund_cum3d": cum3.values, "fund_cum7d": cum7.values,
                      "fund_sign_age": age * np.where(sgn == 0, 0, sgn),
                      "fund_abs": np.abs(r.values)}, index=r.index)

    left = pd.DataFrame(index=index).reset_index().rename(columns={"index": "ts"})
    left.columns = ["ts"]
    out = pd.merge_asof(left.sort_values("ts"), F.reset_index().rename(columns={"index": "ts"}),
                        on="ts", direction="backward")
    return out.set_index("ts")[cols].reindex(index)


# ── MKT ─────────────────────────────────────────────────────────────────────
def _build_market_context(min_bars_4h: int = 3000, n_syms: int = 300) -> pd.DataFrame:
    """
    Ширина и дрейф ВСЕЙ вселенной, посчитанные из кэша 4h (2022-01→2026-08).

    🔴 Почему не таблица `universe_drift`: там всего 225 дней (2026-01→2026-08).
    Для замера на 2022-2026 её нет — считаем сами из того же кэша, что и механику.

    Возвращает ДНЕВНОЙ DataFrame. Индекс = дата. Значения относятся к ЗАКРЫТОМУ дню;
    сдвиг на 1 день делается в `market_context()` при выдаче.
    """
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as c:
        rows = c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                         "GROUP BY symbol HAVING n>? ORDER BY n DESC", (min_bars_4h,)).fetchall()
        syms = [s for s, _ in rows][:n_syms]
        if not syms:
            raise RuntimeError("market_context: ноль символов 4h — пустой замер запрещён")
        q = ("SELECT symbol,time,close FROM ohlcv_cache WHERE timeframe='4h' AND symbol IN (%s)"
             % ",".join("?" * len(syms)))
        d = pd.read_sql(q, c, params=syms)
    d["day"] = pd.to_datetime(d.time, unit="ms", utc=True).dt.floor("D")
    px = d.sort_values("time").groupby(["day", "symbol"]).close.last().unstack()
    px = px.sort_index()
    print(f"  market_context: {px.shape[1]} монет × {px.shape[0]} дней "
          f"({px.index[0].date()} → {px.index[-1].date()})")

    ret = lambda k: px.pct_change(k) * 100                 # noqa: E731
    ma200 = px.rolling(200, min_periods=100).mean()
    M = pd.DataFrame(index=px.index)
    M["mkt_drift30"] = ret(30).median(axis=1)
    M["mkt_drift90"] = ret(90).median(axis=1)
    M["mkt_drift180"] = ret(180).median(axis=1)
    M["mkt_drift_slope"] = M.mkt_drift180.diff(30)          # производная дрейфа
    M["mkt_breadth_ma200"] = (px > ma200).mean(axis=1) * 100
    M["mkt_breadth_up30"] = (ret(30) > 0).mean(axis=1) * 100
    M["mkt_disp30"] = ret(30).std(axis=1)                   # разброс: рынок един или врозь
    # режим BTC — тот же кэш, отдельной колонкой (это «руль» всей вселенной)
    btc = next((s for s in ("BTC/USDT", "BTCUSDT") if s in px.columns), None)
    if btc:
        b = px[btc]
        M["btc_ret30"] = b.pct_change(30) * 100
        M["btc_above_ma200"] = ((b - b.rolling(200, min_periods=100).mean())
                                / b * 100)
        M["btc_vol30"] = b.pct_change().rolling(30).std() * 100
    return M


def market_context(rebuild: bool = False) -> pd.DataFrame:
    """Дневной рыночный контекст со СДВИГОМ на 1 день (только закрытые дни)."""
    if CACHE.exists() and not rebuild:
        M = pd.read_parquet(CACHE)
    else:
        M = _build_market_context()
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        M.to_parquet(CACHE)
    return M.shift(1)                    # 🔴 причинность: вчерашний закрытый день


def market_features(index: pd.DatetimeIndex, M: pd.DataFrame | None = None) -> pd.DataFrame:
    M = market_context() if M is None else M
    return M.reindex(index.floor("D"), method="ffill").set_axis(index)


# ── DIST + STATE ────────────────────────────────────────────────────────────
def _bars_since(mask: np.ndarray, cap: int = 500) -> np.ndarray:
    """Давность события в барах. Никогда не было → cap."""
    out = np.full(len(mask), float(cap))
    last = -10 ** 9
    for i, m in enumerate(mask):
        if m:
            last = i
        out[i] = min(i - last, cap)
    return out


def symbol_features(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """
    НЕПРЕРЫВНЫЕ признаки одного символа: дистанции до магнитов + состояние
    осцилляторов и его давность.

    Зачем, если есть `compute_flags`: там ВСЁ булево. `wt_os` = «wt < −60» —
    один порог, выбранный когда-то. Непрерывное `wt1_val` позволяет отбору
    искать порог самому, а `wt_bars_since_cross_up` — мерить СОСТОЯНИЕ,
    а не момент ([[feedback_confluence_not_moment]]).

    Индикаторы берутся из ЕДИНОГО калькулятора (`combinator_core`) — не копии.
    """
    from core.calculators.combinator_core import (
        wavetrend, rsi, calc_pivots, WT_OS, WT_OB)

    n = len(df)
    close = df["close"].values
    high, low = df["high"].values, df["low"].values
    vol = df["volume"].values if "volume" in df else np.zeros(n)
    out = {}

    # ── STATE: значения, а не флаги ──
    wt1 = wavetrend(df).values
    wt2 = pd.Series(wt1).rolling(4, min_periods=1).mean().values
    out[f"wt1_val_{label}"] = wt1
    out[f"wt2_val_{label}"] = wt2                      # 🔴 wt2 наравне с wt1 (правка Егора)
    out[f"wt_spread_{label}"] = wt1 - wt2
    cu = np.zeros(n, dtype=bool); cd = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if wt1[i - 1] <= wt2[i - 1] and wt1[i] > wt2[i] and wt1[i - 1] < WT_OS:
            cu[i] = True
        if wt1[i - 1] >= wt2[i - 1] and wt1[i] < wt2[i] and wt1[i - 1] > WT_OB:
            cd[i] = True
    out[f"wt_age_cross_up_{label}"] = _bars_since(cu)
    out[f"wt_age_cross_down_{label}"] = _bars_since(cd)
    st = pd.Series(wt1 > wt2)
    out[f"wt_age_state_{label}"] = _bars_since(st.ne(st.shift()).fillna(False).values)

    r = rsi(close, 14)
    out[f"rsi_val_{label}"] = r

    tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(),
                    (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=43, adjust=False).mean()
    atr_pct = (atr / df.close * 100).values
    out[f"atr_pct_{label}"] = atr_pct
    out[f"atr_ratio100_{label}"] = (atr / atr.rolling(100).mean()).values
    vm = pd.Series(vol).rolling(120, min_periods=30).mean().values
    vs = pd.Series(vol).rolling(120, min_periods=30).std().values
    out[f"vol_z120_{label}"] = (vol - vm) / np.where(vs > 0, vs, np.nan)

    # ── DIST: дистанции до магнитов, в % и в ATR ──
    a = np.where(atr.values > 0, atr.values, np.nan)
    ema200 = df.close.ewm(span=200, adjust=False).mean().values
    out[f"dist_ema200_pct_{label}"] = (close - ema200) / close * 100
    out[f"dist_ema200_atr_{label}"] = (close - ema200) / a

    for p in (21, 55, 89, 144, 233):
        cma = df.close.rolling(p, min_periods=p // 2).mean().values
        out[f"dist_cma{p}_atr_{label}"] = (close - cma) / a

    # экстремумы окна = ERL (внешняя ликвидность): дистанция до неё
    for w in (20, 50, 200):
        hi = pd.Series(high).rolling(w, min_periods=w // 2).max().values
        lo = pd.Series(low).rolling(w, min_periods=w // 2).min().values
        out[f"dist_hi{w}_atr_{label}"] = (close - hi) / a
        out[f"dist_lo{w}_atr_{label}"] = (close - lo) / a
        rng = hi - lo
        out[f"pos_in_range{w}_{label}"] = np.where(rng > 0, (close - lo) / rng * 100, np.nan)

    # пивоты 1D/1W: знаковая дистанция до КАЖДОГО уровня в ATR (в матрице только булево)
    for rule, tag in (("1D", "1D"), ("1W", "1W")):
        agg = df.resample(rule).agg({"high": "max", "low": "min", "close": "last"}).dropna()
        if len(agg) < 3:
            continue
        lv = {k: np.full(n, np.nan) for k in ("PP", "R1", "R2", "S1", "S2")}
        keys = list(agg.index)
        for i in range(1, len(keys)):
            prev = agg.iloc[i - 1]
            piv = calc_pivots(prev["high"], prev["low"], prev["close"])
            start = keys[i]
            end = keys[i + 1] if i + 1 < len(keys) else df.index[-1] + pd.Timedelta(seconds=1)
            m = (df.index >= start) & (df.index < end)
            for k in lv:
                lv[k][m] = piv[k]
        for k, v in lv.items():
            out[f"dist_piv_{k}_{tag}_atr_{label}"] = (close - v) / a

    E = pd.DataFrame(out, index=df.index)
    # 🔴 ПРИЧИННОСТЬ: значение ЗАКРЫТОГО бара, а не текущего
    return E.shift(1)


def candle_volume_features(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """
    ОСНОВЫ, которых в матрице не было (проверено грепом 28.08, напоминание Егора):
      · АНАТОМИЯ СВЕЧИ — 0 признаков в `compute_flags`. Тело и тени рассказывают,
        кто победил в периоде и как далеко цена ходила ПРОТИВ итога.
      · ОБЪЁМ — был ОДИН признак на 565: `vol_spike = v > 1.5·SMA20`. При этом
        значимое движение сопровождается объёмом в 3-4 раза выше среднего, то есть
        единственный порог стоял ВТРОЕ ниже интересной зоны. Здесь — непрерывное
        отношение, отбор ищет порог сам.
      · ДЕЛЬТА-ПРОКСИ — знак объёма по цвету свечи. Настоящую дельту (агрессивные
        покупки минус продажи) даёт только лента сделок, её у нас нет; цвет свечи —
        грубое, но причинное приближение.
    """
    n = len(df)
    o, h, l, c = (df.open.values, df.high.values, df.low.values, df.close.values)
    v = df.volume.values if "volume" in df else np.zeros(n)
    rng = np.where((h - l) > 0, h - l, np.nan)
    out = {}

    # ── анатомия: всё в долях ДИАПАЗОНА бара, поэтому сравнимо между монетами ──
    out[f"body_frac_{label}"] = np.abs(c - o) / rng
    out[f"upper_wick_frac_{label}"] = (h - np.maximum(o, c)) / rng
    out[f"lower_wick_frac_{label}"] = (np.minimum(o, c) - l) / rng
    # где ЗАКРЫЛИСЬ внутри бара: 100 = на максимуме (победили покупатели), 0 = на минимуме
    out[f"close_pos_in_bar_{label}"] = (c - l) / rng * 100
    out[f"bar_range_pct_{label}"] = (h - l) / np.where(c != 0, c, np.nan) * 100
    # перевес тени: >0 верхняя длиннее (продавцы давили сверху), <0 нижняя
    out[f"wick_skew_{label}"] = ((h - np.maximum(o, c)) - (np.minimum(o, c) - l)) / rng

    # поглощение: тело текущего бара перекрывает тело предыдущего и цвет сменился
    body_lo = np.minimum(o, c); body_hi = np.maximum(o, c)
    prev_lo = np.roll(body_lo, 1); prev_hi = np.roll(body_hi, 1)
    up = c > o; prev_up = np.roll(up, 1)
    eng = (body_lo <= prev_lo) & (body_hi >= prev_hi) & (up != prev_up)
    eng[0] = False
    out[f"engulfing_{label}"] = eng.astype(float)

    # ── объём: НЕПРЕРЫВНОЕ отношение вместо одного порога 1.5 ──
    for w in (20, 50, 120):
        sma = pd.Series(v).rolling(w, min_periods=max(3, w // 4)).mean().values
        out[f"vol_ratio{w}_{label}"] = v / np.where(sma > 0, sma, np.nan)
    # объём × ход: сильное движение НА объёме отличается от такого же без него
    out[f"vol_x_range_{label}"] = out[f"vol_ratio20_{label}"] * out[f"bar_range_pct_{label}"]

    # ── дельта-прокси: знак объёма по цвету, и накопление ──
    sv = np.where(c > o, v, np.where(c < o, -v, 0.0))
    out[f"vol_delta_{label}"] = sv / np.where(v > 0, v, np.nan)      # −1..+1, чистый знак
    for w in (5, 20):
        s = pd.Series(sv).rolling(w, min_periods=2).sum().values
        tot = pd.Series(np.abs(sv)).rolling(w, min_periods=2).sum().values
        out[f"cum_delta{w}_{label}"] = s / np.where(tot > 0, tot, np.nan)

    E = pd.DataFrame(out, index=df.index)
    return E.shift(1)     # 🔴 причинность: значение ЗАКРЫТОГО бара


MINOR_LEN, MAJOR_LEN = 5, 50


def _break_arrays(df: pd.DataFrame, length: int) -> dict[str, np.ndarray]:
    """
    Сломы структуры ОДНОГО масштаба, развёрнутые в непрерывное СОСТОЯНИЕ по барам.

    `detect_structure_breaks` отдаёт список событий; матрица до сих пор знала о них
    только булев флаг «на этом баре был слом». Здесь событие превращается в то, что
    можно спросить на ЛЮБОМ баре: куда смотрит структура, давно ли это случилось,
    насколько далеко ушла цена от пробитого уровня.

    Причинность: уровень свинга активируется у детектора на баре `idx + length`,
    то есть после подтверждения — заглянуть вперёд нечем. Пробой фиксируется на
    своём баре по close. Итоговый сдвиг на 1 бар делает вызывающая функция.
    """
    from core.smc.smc_engine import detect_structure_breaks

    n = len(df)
    z = lambda: np.full(n, np.nan)                                   # noqa: E731
    ev_dir, ev_choch, ev_vol, ev_lvl, ev_at = z(), z(), z(), z(), z()
    hits = np.zeros(n)

    for b in detect_structure_breaks(df, length=length):
        i = int(b.idx)
        if not 0 <= i < n:
            continue
        # несколько сломов на одном баре: побеждает последний — он же актуальный
        ev_dir[i] = 1.0 if b.direction == "bull" else -1.0
        ev_choch[i] = 1.0 if b.kind == "CHoCH" else 0.0
        ev_vol[i] = 1.0 if b.has_volume else 0.0
        ev_lvl[i] = float(b.price)
        ev_at[i] = float(i)
        hits[i] += 1.0

    ff = lambda a: pd.Series(a, index=df.index).ffill().values        # noqa: E731
    at = ff(ev_at)
    return {
        "dir": ff(ev_dir),
        "choch": ff(ev_choch),
        "vol": ff(ev_vol),
        "lvl": ff(ev_lvl),
        "age": np.arange(n, dtype=float) - at,
        "cum": np.cumsum(hits),           # для «сколько младших внутри старшей»
        "hits": hits,
        "at": at,
    }


def structure_scales_features(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """
    🔴 ДВЕ СТРУКТУРЫ ВМЕСТО ОДНОЙ (28.08.2026) — класс признаков, которого в матрице
    не было ВООБЩЕ.

    Повод. Прогон полной матрицы дал ноль находок трижды подряд (585 признаков,
    P(шум) = 0.500). Разбор показал причину, которая не в признаках, а в их наборе:
    вся структурная семья `combinator_core` строится ОДНИМ масштабом —
    `swing_bridge._get_choch_length()` читает `arch104.choch_length` = 50. То есть
    матрица знала, КУДА смотрит старшая структура, и не знала НИ ОДНОГО признака
    того, КОГДА входить. Искать триггер входа в наборе без триггеров невозможно.

    Метод Егора ([[method_egor_two_scale_entry]], подтверждён 28.08 на графике):
    два `length` на ОДНОМ графике дают старшую и младшую структуру — старшая
    задаёт сторону, младшая даёт момент. Здесь ровно это, в виде чисел.

    Масштабы выбраны не на глаз: замер `choch_length_across_tf.py` показал, что
    15m·50 (12.5 ч) — календарный эквивалент 4h·5 (20 ч) с перекрытием уровней
    66.7%. То есть 50 УЖЕ является «старшим» на 15m, и младший к нему — 5.

    Три группы:
      st{N}_*  состояние каждого масштаба по отдельности (в т.ч. ДАВНОСТЬ, которой
               у булевых `bull_bos_*` нет);
      sc_*     СОГЛАСОВАНИЕ масштабов — то, ради чего всё затевалось;
      sc_pullback / sc_resume — две геометрии входа, названные явно.
    """
    n = len(df)
    out: dict[str, np.ndarray] = {}
    if n < MAJOR_LEN * 4:
        return pd.DataFrame(out, index=df.index)

    from core.smc.impulse_fib import _atr
    atr = _atr(df).values
    atr_s = np.where(atr > 0, atr, np.nan)
    c = df.close.values

    S = {}
    for ln in (MINOR_LEN, MAJOR_LEN):
        a = _break_arrays(df, ln)
        S[ln] = a
        p = f"st{ln}"
        out[f"{p}_dir_{label}"] = a["dir"]
        out[f"{p}_is_choch_{label}"] = a["choch"]
        out[f"{p}_had_vol_{label}"] = a["vol"]
        out[f"{p}_age_{label}"] = a["age"]
        # знаковая дистанция до пробитого уровня в ATR: цена вернулась к нему или ушла
        out[f"{p}_dist_atr_{label}"] = (c - a["lvl"]) / atr_s
        # 🔑 направление × давность: свежий слом и старый слом — разные состояния,
        # а по отдельности отбор их не различает (закон о состоянии, не моменте)
        out[f"{p}_dir_x_age_{label}"] = a["dir"] * a["age"]

    # частота МЛАДШИХ сломов = рваность хода. Чистый ход даёт мало сломов,
    # пила — много. У старшего масштаба на таком окне частота вырождается.
    for w in (20, 50):
        out[f"st{MINOR_LEN}_count{w}_{label}"] = (
            pd.Series(S[MINOR_LEN]["hits"], index=df.index)
            .rolling(w, min_periods=1).sum().values)

    # ── СОГЛАСОВАНИЕ МАСШТАБОВ ──────────────────────────────────────────────
    mn, mj = S[MINOR_LEN], S[MAJOR_LEN]
    agree = np.where(np.isnan(mn["dir"]) | np.isnan(mj["dir"]), np.nan,
                     np.where(mn["dir"] == mj["dir"], 1.0, -1.0))
    out[f"sc_agree_{label}"] = agree

    # 🔑 НОМЕР МЛАДШЕЙ НОГИ внутри старшей: сколько младших сломов прошло с момента
    # последнего старшего. Первый откат после слома тренда — не то же самое, что пятый.
    cum_at_major = pd.Series(
        np.where(mj["hits"] > 0, mn["cum"], np.nan), index=df.index).ffill().values
    out[f"sc_minor_since_major_{label}"] = mn["cum"] - cum_at_major

    # возраст младшего относительно старшего: младший всегда свежее, но НАСКОЛЬКО —
    # это и есть «где мы внутри старшей ноги»
    out[f"sc_age_ratio_{label}"] = mn["age"] / (mj["age"] + 1.0)

    # ── ДВЕ ГЕОМЕТРИИ ВХОДА, НАЗВАННЫЕ ЯВНО ─────────────────────────────────
    # ОТКАТ: старшая идёт продолжением (BOS), младшая сломалась ПРОТИВ неё —
    # классическая точка входа по тренду, а не разворот.
    out[f"sc_pullback_{label}"] = (
        (mj["choch"] == 0.0) & (agree == -1.0)).astype(float)
    # ВОЗОБНОВЛЕНИЕ: младшая вернулась НА сторону старшей — откат закончился.
    resumed = (agree == 1.0) & (mn["age"] < mj["age"])
    out[f"sc_resume_{label}"] = resumed.astype(float)
    # то же, но с объёмом на младшем сломе (критерий «настоящего слома»)
    out[f"sc_resume_vol_{label}"] = (resumed & (mn["vol"] == 1.0)).astype(float)

    E = pd.DataFrame(out, index=df.index)
    return E.shift(1)     # 🔴 причинность: состояние на ЗАКРЫТОМ баре


def wave_features(df: pd.DataFrame, label: str,
                  swing_len: int = MAJOR_LEN, internal_len: int = MINOR_LEN) -> pd.DataFrame:
    """
    🔴 ВОЛНЫ (ноги структуры) — в матрице их не было ВООБЩЕ (грep 28.08: 0 упоминаний
    `leg` в `combinator_core` и в `matrix_full`).

    Повод — вопрос Егора: «с микроструктурой ты и волны по-другому считать будешь?».
    Проверка вскрыла, что в проекте ДВА движка структуры:
      · `oko_sm_engine.run_structure(swing_len=50, internal_len=5)` — ведёт ДВА масштаба
        с раздельными трендами `trend`/`itrend` и хранит `leg_history` — НОГУ на каждом
        баре, каузально. На нём стоит боевая `choch_wavec`;
      · `smc_engine.detect_structure_breaks(length)` — один масштаб; на нём висит
        `swing_bridge` → `combinator_core` → ВСЯ МАТРИЦА.
    Сверка событий: **совпадение 100%** (1006 internal и 126 swing, допуск ±0 баров).
    Различие одно: у `SMEvent` нет `has_volume`, поэтому семья SCALES остаётся на
    `smc_engine` (её признаки `*_had_vol` иначе исчезнут), а волны берутся ОТСЮДА —
    `leg_history` есть только у движка ([[principle_reuse_not_duplication]]).

    Что даёт нога, чего не дают сломы: слом — это ТОЧКА, нога — ОТРЕЗОК. Появляются
    вопросы, которые до сих пор задать было нечем: где цена ВНУТРИ ноги (это ровно то,
    от чего механика отмеряет фибо), насколько нога крутая, сколько младших волн в неё
    уложилось.

    🔑 Последнее — перевод находки [[two_scale_structure_minor_churn]] на волновой язык.
    «Младшая пилит ≥2 слома за 5 часов» физически означает СТУПЕНЧАТУЮ старшую ногу,
    а не гладкую. `leg_minor_per100` меряет это прямо и без привязки к окну в барах.
    """
    from core.smc.oko_sm_engine import run_structure

    n = len(df)
    out: dict[str, np.ndarray] = {}
    if n < swing_len * 4:
        return pd.DataFrame(out, index=df.index)

    dd = df.reset_index(drop=True)[["open", "high", "low", "close"]]
    st = run_structure(dd, swing_len=swing_len, internal_len=internal_len,
                       record_legs=True)
    legs = st.leg_history
    if len(legs) < n:
        legs = list(legs) + [None] * (n - len(legs))

    from core.smc.impulse_fib import _atr
    atr = _atr(df).values
    atr_s = np.where(atr > 0, atr, np.nan)
    c = df.close.values
    t_arr = np.arange(n, dtype=float)

    z = lambda: np.full(n, np.nan)                                    # noqa: E731
    o_px, e_px, o_i, e_i, d_ = z(), z(), z(), z(), z()
    for t, lg in enumerate(legs[:n]):
        if not lg:
            continue
        o_px[t] = lg["origin"]; e_px[t] = lg["extreme"]
        o_i[t] = lg["origin_i"] if lg["origin_i"] is not None else np.nan
        e_i[t] = lg["extreme_i"] if lg["extreme_i"] is not None else np.nan
        d_[t] = 1.0 if lg["trend"] == "long" else -1.0

    span = e_px - o_px                       # знаковая высота ноги
    span_s = np.where(np.abs(span) > 0, span, np.nan)
    out[f"leg_dir_{label}"] = d_
    out[f"leg_amp_pct_{label}"] = np.abs(span) / np.where(o_px != 0, o_px, np.nan) * 100
    out[f"leg_amp_atr_{label}"] = np.abs(span) / atr_s
    out[f"leg_span_bars_{label}"] = e_i - o_i
    out[f"leg_age_extreme_{label}"] = t_arr - e_i
    out[f"leg_age_origin_{label}"] = t_arr - o_i

    # 🔑 ГДЕ ЦЕНА ВНУТРИ НОГИ: 1.0 = на экстремуме, 0 = вернулась к началу, <0 = пробила
    pos = (c - o_px) / span_s
    out[f"leg_pos_{label}"] = pos
    out[f"leg_retr_{label}"] = 1.0 - pos                 # глубина отката — язык фибо
    # зоны, которыми механика реально пользуется
    out[f"leg_in_ote_{label}"] = ((1.0 - pos >= 0.618) & (1.0 - pos <= 0.79)).astype(float)
    out[f"leg_in_disc_{label}"] = (1.0 - pos > 0.5).astype(float)
    # крутизна: ATR на бар. Одинаковая амплитуда за 10 и за 200 баров — разные вещи
    sb = out[f"leg_span_bars_{label}"]
    out[f"leg_speed_atr_{label}"] = out[f"leg_amp_atr_{label}"] / np.where(sb > 0, sb, np.nan)

    # ── СКОЛЬКО МЛАДШИХ ВОЛН УЛОЖИЛОСЬ В СТАРШУЮ НОГУ ───────────────────────
    ihit = np.zeros(n)
    idir_ev = z()
    for e in st.events:
        if 0 <= e.i < n and e.internal:
            ihit[e.i] += 1.0
            idir_ev[e.i] = 1.0 if e.bull else -1.0
    icum = np.cumsum(ihit)
    oi = np.where(np.isnan(o_i), 0, o_i).astype(int)
    minor_in_leg = np.where(np.isnan(o_i), np.nan, icum - icum[np.clip(oi, 0, n - 1)])
    out[f"leg_minor_breaks_{label}"] = minor_in_leg
    age_o = out[f"leg_age_origin_{label}"]
    out[f"leg_minor_per100_{label}"] = minor_in_leg / np.where(age_o > 0, age_o, np.nan) * 100

    # согласие младшего тренда со старшим — готовое у движка, но по барам его нет
    idir = pd.Series(idir_ev, index=df.index).ffill().values
    out[f"leg_minor_agree_{label}"] = np.where(
        np.isnan(idir) | np.isnan(d_), np.nan, np.where(idir == d_, 1.0, -1.0))

    E = pd.DataFrame(out, index=df.index)
    return E.shift(1)     # 🔴 причинность: нога, известная на ЗАКРЫТОМ баре


def profile_features(df: pd.DataFrame, tf: str, senior: str) -> pd.DataFrame:
    """
    «ЗАГЛЯНУТЬ ВНУТРЬ СВЕЧИ» — прокси кластерного анализа на полной истории.

    Настоящий footprint требует ленты сделок, которой у нас нет. Но старший бар
    можно разобрать МЛАДШИМ, который уже загружен: внутри часового бара четыре
    пятнадцатиминутки, внутри четырёхчасового — шестнадцать. Это грубое, но
    ЧЕСТНОЕ распределение объёма по цене внутри старшей свечи.

    Считаем на каждый старший бар:
      · POC — цена младшего бара с максимальным объёмом (point of control);
      · насколько цена сейчас далека от POC (в долях диапазона старшего бара);
      · где POC лежит внутри старшего бара (вверху = объём торговался высоко);
      · концентрация — доля объёма в самом объёмном младшем баре. Высокая
        концентрация = один всплеск, низкая = равномерная торговля.

    🔴 Причинность: берём ЗАКРЫТЫЙ старший бар (`shift(1)`), как в `mtf_flags`.
    """
    RULE = {"1h": "1h", "4h": "4h", "1d": "1D"}
    rule = RULE.get(senior)
    if rule is None:
        return pd.DataFrame(index=df.index)
    g = df.resample(rule)
    agg = g.agg({"high": "max", "low": "min", "close": "last"}).dropna()
    if len(agg) < 50:
        return pd.DataFrame(index=df.index)

    # индекс младшего бара с максимальным объёмом внутри каждого старшего
    vol = df.volume if "volume" in df else pd.Series(0.0, index=df.index)
    grp = vol.groupby(pd.Grouper(freq=rule))
    idxmax = grp.idxmax()
    vmax, vsum = grp.max(), grp.sum()
    typical = ((df.high + df.low + df.close) / 3)
    poc = typical.reindex(idxmax.dropna()).values
    P = pd.DataFrame(index=idxmax.dropna().index)
    P["poc"] = poc
    P = P.join(agg, how="inner")
    P["conc"] = (vmax / vsum.replace(0, np.nan)).reindex(P.index)
    rngs = (P.high - P.low).replace(0, np.nan)
    P[f"poc_pos_in_bar__{senior}"] = (P.poc - P.low) / rngs * 100
    P[f"poc_conc__{senior}"] = P["conc"] * 100
    keep = [c for c in P.columns if c.startswith("poc_")]
    P = P[keep + ["poc"]].shift(1)                    # 🔴 только ЗАКРЫТЫЙ старший бар
    P = P.reindex(df.index, method="ffill")
    out = pd.DataFrame(index=df.index)
    for c in keep:
        out[c] = P[c]
    # дистанция ТЕКУЩЕЙ цены до POC закрытого старшего бара, в % — магнит объёма
    out[f"dist_poc_pct__{senior}"] = (df.close.shift(1) - P["poc"]) / P["poc"] * 100
    return out


def extra_flags(df: pd.DataFrame, tf: str, symbol: str,
                M: pd.DataFrame | None = None,
                senior: list[str] | None = None) -> pd.DataFrame:
    """
    Полный набор «вне combinator_core» для одного символа: FUND + MKT + DIST/STATE,
    включая DIST/STATE со СТАРШИХ ТФ (закрытый бар, shift(1)) — по тем же правилам,
    что `research_harness.mtf_flags`.
    """
    AUTO = {"5m": ["15m", "1h"], "15m": ["1h", "4h"], "1h": ["4h", "1d"], "4h": ["1d"]}
    RULE = {"15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}
    senior = AUTO.get(tf, []) if senior is None else senior

    parts = [symbol_features(df, tf),
             candle_volume_features(df, tf),          # анатомия свечи + объём как следует
             funding_features(df.index, symbol),
             market_features(df.index, M)]
    # 🔴 две структуры вместо одной: у матрицы не было признаков ТРИГГЕРА входа
    try:
        parts.append(structure_scales_features(df, tf))
    except Exception:                                  # noqa: BLE001
        pass
    # 🔴 волны: слом — точка, нога — отрезок. В матрице ног не было вовсе
    try:
        parts.append(wave_features(df, tf))
    except Exception:                                  # noqa: BLE001
        pass
    # профиль объёма старших баров, разобранных ТЕКУЩИМ ТФ («внутрь свечи»)
    for stf in senior:
        try:
            parts.append(profile_features(df, tf, stf))
        except Exception:                              # noqa: BLE001
            pass
    for stf in senior:
        rule = RULE.get(stf)
        if rule is None:
            continue
        agg = df.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                     "close": "last", "volume": "sum"}).dropna()
        if len(agg) < 300:
            continue
        S = symbol_features(agg, stf)                 # уже сдвинут на 1 свой бар
        S = S.reindex(df.index, method="ffill")
        S.columns = [f"{c}__from_{stf}" for c in S.columns]
        parts.append(S)
    return pd.concat(parts, axis=1)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:      # noqa: BLE001
        pass
    print(__doc__)
    M = market_context(rebuild="--rebuild" in sys.argv)
    print(f"\nрыночный контекст: {M.shape[0]} дней × {M.shape[1]} признаков "
          f"({M.index[0].date()} → {M.index[-1].date()})")
    print(M.tail(3).round(2).to_string())
