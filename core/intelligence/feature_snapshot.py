"""
ARCH-118 — Единый снимок признаков (snapshot_features).

Шаг 1: чистая функция-обёртка над ЕДИНЫМ калькулятором (`combinator_v2.compute_flags`),
собирающая снимок ~47 флагов × TF + pivot на момент входа КАЖДОЙ сделки.

🔴 ИНВАРИАНТ «ОДИН КАЛЬКУЛЯТОР» (docs/ENCYCLOPEDIA.md → ИНВАРИАНТ ВЫСШЕГО УРОВНЯ):
live (этот модуль) и бэктест используют ОДНУ функцию compute_flags. Запрещён второй
независимый путь расчёта одного признака — это корень самоподтверждения.

Схема снимка (features_schema_version=2):
  {
    "schema_version": 2,
    "meta":   {entry_tf, tfs[], snapshot_ts, n_true, n_total},
    "context":{ smc:{...}, wt:{...}, rsi:{...}, trend:{...}, mom:{...}, pivot:{...} },
    "signal": {...}   # specifics: pattern_id, confirmations[] — передаются снаружи
  }
context хранится SPARSE: пишутся только взведённые (true) флаги. False восстанавливается
декодером из канона схемы (snapshot_to_vector). Размер: dense 770≈207MB → sparse≈22MB.

⚠️ ДОЛГ (для прод-интеграции в register_trade):
combinator_v2 на уровне импорта переопределяет sys.stdout и держит HISTORY_DIR (скрипт).
Здесь импорт защищён (_import_compute_flags восстанавливает stdout). Для чистого
инварианта compute_flags + indicator-функции нужно вынести в core/ модуль без side-effects.
"""
from __future__ import annotations

import io
import sys
import os
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

SCHEMA_VERSION = 6   # v6 (04.09.2026): в compute_flags добавлены перцентиль ATR
                     #   (atr_prank/atr_prank80/atr_vol_high/atr_vol_low) и семья
                     #   CANDLE+VOL (анатомия свечи + непрерывный объём, 14 признаков).
                     #   Непрерывные пишутся ЗНАЧЕНИЕМ (_NUMERIC_PREFIXES), а не sparse-bool.
                     # v5 (02.09.2026): структура — двухслойный эталон OKO-SM;
                     #   добавлены *_bos_i / *_choch_i (микроструктура len=5),
                     #   из старшего слоя убрана примесь zigzag_atr.
                     # v4 (17.08.2026): pivot-флаги на ВСЕХ TF (было — только 1h)

# TF, для которых compute_flags вызывает pivot-флаги.
# 17.08.2026 (Егор: «насытить 5m и 1d остальными флагами»): было `_PIVOT_TF = "1h"` —
# 1h получал 149 флагов, остальные TF только 73. SMC (OB/FVG/CHoCH/BOS/OTE/EQH/EQL/
# Elliott, 29 флагов) считались везде и раньше; не хватало ровно пивотов — 76 признаков
# (38 уровневых × 1D и 1W).
# Уровни 1D/1W одни и те же на любом TF, но флаг «цена у уровня»/«отбой» на 5m точнее
# по времени, чем на 1h, а на 1d даёт контекст закрытия дня относительно уровня.
# Цена: на живом df (300–500 баров) — доли секунды; замер 17.08 на 20 000 барах:
# 5m 2.00→3.60с, 15m 3.94→6.20с, 1h 0.62→1.31с, 4h 0.14→0.33с, 1d 0.05→0.08с.
_PIVOT_TFS = {"5m", "15m", "1h", "4h", "1d"}
_PIVOT_TF = "1h"     # оставлен для обратной совместимости импортов
# Канонический порядок TF (для сортировки в snapshot_from_flags_row)
_TF_ORDER = ["5m", "15m", "1h", "4h", "1d"]


def _import_cb():
    """ARCH-118.3 (05.06): ЧИСТЫЙ импорт единого калькулятора из core/calculators/.
    Хак с sys.stdout detach + sys.path больше НЕ нужен — combinator_core не имеет
    import-time side-effects (вынесен из combinator_v2). Инвариант «один калькулятор»."""
    from core.calculators import combinator_core
    return combinator_core


def _import_compute_flags():
    """Единый калькулятор флагов (core.calculators.combinator_core.compute_flags)."""
    from core.calculators.combinator_core import compute_flags
    return compute_flags


async def _fetch_df(data_collector: Any, symbol: str, tf: str, limit: int,
                    since: Optional[int] = None):
    """Загрузить OHLCV и привести к стандартному виду (как arch104 observer, parity).

    Поддерживает оба формата индекса: 'ts' (ccxt) и 'time' (data_collector, D-042).
    since (ms) — для пагинации истории назад (HTFHistoryCache).
    """
    try:
        df = await data_collector.get_ohlcv(symbol, timeframe=tf, limit=limit, since=since)
    except TypeError:
        # data_collector без since в сигнатуре — fallback
        try:
            df = await data_collector.get_ohlcv(symbol, timeframe=tf, limit=limit)
        except Exception:
            return None
    except Exception:
        return None
    if df is None or len(df) < 2:
        return None
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    ts_col = "ts" if "ts" in df.columns else ("time" if "time" in df.columns else None)
    if ts_col is not None:
        df[ts_col] = pd.to_datetime(df[ts_col], unit="ms", utc=True, errors="coerce")
        df = df.set_index(ts_col)
    if not isinstance(df.index, pd.DatetimeIndex):
        return None
    return df[["open", "high", "low", "close", "volume"]].dropna().sort_index()


# ── HTFHistoryCache (ARCH-118 Шаг 4, рой 7/7) ──────────────────────────────
# Глубина 1h для сходимости HTF-индикаторов (ema200_1d). Эмпирически (12 пар):
# 1h@300→48 расхождений, @1000→23, @2000→14, @4000→0. Цель ≥4000.
# BingX max 1440/запрос → пагинация 3 страницы. TTL длинный (HTF меняется медленно).
_HTF_TARGET_BARS = 4320       # 3 × 1440, запас над 4000 (0 HTF-расхождений vs full)
_HTF_PAGE = 1440              # BingX max OHLCV за один запрос (код 109400 при >1440)
_HTF_CACHE_TTL = 1800.0       # сек; HTF медленный, пере-загрузка раз в 30 мин
_TF_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


class _HTFHistoryCache:
    """Per-symbol кэш ГЛУБОКОЙ 1h-истории (≥4320 баров) с пагинацией.

    Резолвит источник (2) расхождения parity: live грузил 1h@300 → 1d≈12 баров →
    ema200_1d недостоверна. Кэш даёт ~180 1d баров → HTF-индикаторы сходятся к full.
    HTF (4h/1d) ресемплятся из этого 1h → resample-parity с бэктестом сохранён.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}

    async def get_deep_1h(self, data_collector: Any, symbol: str):
        import time as _t
        ent = self._store.get(symbol)
        if ent is not None and (_t.monotonic() - ent[1]) < _HTF_CACHE_TTL \
                and len(ent[0]) >= _HTF_TARGET_BARS * 0.9:
            return ent[0]
        df = await self._paginate_1h(data_collector, symbol)
        if df is not None and len(df) > 0:
            self._store[symbol] = (df, _t.monotonic())
        return df

    async def _paginate_1h(self, data_collector: Any, symbol: str):
        """Собрать ~_HTF_TARGET_BARS 1h через несколько since-окон назад от now."""
        from datetime import datetime, timezone
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        step_ms = _HTF_PAGE * _TF_SECONDS["1h"] * 1000
        pages = (_HTF_TARGET_BARS + _HTF_PAGE - 1) // _HTF_PAGE
        frames = []
        for k in range(pages):
            # окно k: [now - (k+1)*page, now - k*page]
            since_ms = now_ms - (k + 1) * step_ms
            d = await _fetch_df(data_collector, symbol, "1h", _HTF_PAGE, since=since_ms)
            if d is not None and len(d) > 0:
                frames.append(d)
        if not frames:
            # fallback: обычный неглубокий fetch (parity деградирует, но снимок не None)
            return await _fetch_df(data_collector, symbol, "1h", 300)
        full = pd.concat(frames)
        full = full[~full.index.duplicated(keep="last")].sort_index()
        return full


_HTF_CACHE = _HTFHistoryCache()


async def build_df_by_tf(
    data_collector: Any,
    symbol: str,
    *,
    want_5m: bool = False,
    deep_htf: bool = True,
) -> dict[str, "pd.DataFrame"]:
    """Собрать df_by_tf для снимка. HTF (4h/1d) = resample глубокого 1h (parity + глубина).

    deep_htf=True (ARCH-118 Шаг 4): 1h берётся из HTFHistoryCache (≥4320 баров) →
    ema200_1d/wt_ob_1d сходятся к backtest (0 HTF-расхождений). 4h/1d ресемплятся из
    того же 1h (resample-parity). 15m/5m — нативный fetch (LTF, parity уже идеален).
    """
    out: dict[str, Any] = {}
    if deep_htf:
        df_1h = await _HTF_CACHE.get_deep_1h(data_collector, symbol)
    else:
        df_1h = await _fetch_df(data_collector, symbol, "1h", 300)
    if df_1h is None or len(df_1h) < 50:
        return out
    out["1h"] = df_1h
    # 17.08.2026: 400 → 500. Пивот-флаги 1D/1W требуют многодневной истории:
    # замер показал, что 15m набирает их с 500 баров (~5 суток), на 400 — впритык.
    df_15m = await _fetch_df(data_collector, symbol, "15m", 500)
    if df_15m is not None:
        out["15m"] = df_15m
    cb = _import_cb()
    for htf in ("4h", "1d"):
        try:
            out[htf] = cb.aggregate_tf(df_1h, htf)  # resample из глубокого 1h = parity
        except Exception:
            pass
    if want_5m:
        # 17.08.2026: 500 → 1440. На 500 барах (сутки) пивот-флаги 1D/1W НЕ считаются
        # вовсе — уровням нужна многодневная история. Замер порога: 1200 и 1300 баров
        # дают 0 пивотов, 1440 (4д 23ч) — все 76. 1440 = максимум BingX за один запрос,
        # то есть глубина взята впритык и без лишних обращений к API.
        df_5m = await _fetch_df(data_collector, symbol, "5m", 1440)
        if df_5m is not None and len(df_5m) >= 100:
            out["5m"] = df_5m
    return out


def _domain_of(flag: str) -> str:
    """Доменная группировка флага по префиксу (имя с суффиксом _{tf})."""
    if flag.startswith("pivot_"):
        return "pivot"
    if flag.startswith("wt_"):
        return "wt"
    if flag.startswith("rsi_"):
        return "rsi"
    if flag.startswith(("atr_", "above_ema", "below_ema", "ema50_")):
        return "trend"
    if flag.startswith(("vol_spike", "bull_mom", "bear_mom",
                        "vol_ratio", "vol_x_range", "vol_delta", "cum_delta")):
        return "mom"
    # 04.09.2026: анатомия свечи — новый домен (раньше таких признаков не было вовсе)
    if flag.startswith(("body_frac", "upper_wick_frac", "lower_wick_frac",
                        "close_pos_in_bar", "bar_range_pct", "wick_skew", "engulfing")):
        return "candle"
    # FVG/OB/BOS/CHoCH/OTE/premium/discount/eqh/eql
    return "smc"


def snapshot_features(
    df_by_tf: dict[str, pd.DataFrame],
    entry_tf: str,
    *,
    signal: Optional[dict] = None,
    _compute_flags: Any = None,
) -> dict:
    """Собрать единый снимок признаков на момент входа из OHLCV по таймфреймам.

    Args:
        df_by_tf:  {tf_label: DataFrame[open,high,low,close,volume]} — закрытые свечи.
                   Последняя строка каждого df = момент входа (последняя ЗАКРЫТАЯ свеча TF).
        entry_tf:  TF, на котором сработал сигнал (для meta).
        signal:    specifics сигнала (pattern_id, confirmations[]) → кладётся в snapshot["signal"].
        _compute_flags: инъекция калькулятора (для тестов); по умолчанию — combinator_v2.

    Returns:
        dict — вложенный sparse-снимок (см. docstring модуля).
    """
    compute_flags = _compute_flags or _import_compute_flags()

    flag_items: list[tuple[str, bool]] = []
    tfs_used: list[str] = []

    for tf, df in df_by_tf.items():
        if df is None or len(df) == 0:
            continue
        flags_df = compute_flags(df, tf, include_pivots=(tf in _PIVOT_TFS))
        if flags_df is None or len(flags_df) == 0:
            continue
        last = flags_df.iloc[-1]  # момент входа = последняя закрытая свеча TF
        tfs_used.append(tf)
        flag_items.extend((col, last[col]) for col in flags_df.columns)  # raw (value-cols сохранятся)

    context, n_true, n_total = _pack_context(flag_items)
    return _build_snapshot(context, n_true, n_total, entry_tf, tfs_used,
                           signal, source="live",
                           snapshot_ts=datetime.now(timezone.utc).isoformat())


def snapshot_features_at(
    df_by_tf: dict[str, "pd.DataFrame"],
    entry_ts,
    entry_tf: str,
    *,
    signal: Optional[dict] = None,
    closed_only: bool = True,
    _compute_flags: Any = None,
) -> dict:
    """Снимок на ИСТОРИЧЕСКУЮ точку входа entry_ts — КАНОН independent-last (рой 5/7).

    Для бэктеста: на момент входа берётся последняя ЗАКРЫТАЯ свеча каждого TF
    (df[df.index + tf <= entry_ts]) → compute_flags → last. Это идентично live
    snapshot_features (последняя закрытая HTF-свеча, БЕЗ lookahead, trade-time не
    bar-time). Заменяет reindex+shift для снимка-фичи (combinator-matching паттернов
    остаётся на reindex+shift — отдельный слой).

    closed_only=True: исключить свечу, ещё не закрытую к entry_ts (анти-lookahead).
    """
    entry_ts = pd.Timestamp(entry_ts)
    if entry_ts.tzinfo is None:
        entry_ts = entry_ts.tz_localize("UTC")
    sliced: dict[str, Any] = {}
    for tf, df in df_by_tf.items():
        if df is None or len(df) == 0:
            continue
        if closed_only:
            tf_sec = _TF_SECONDS.get(tf, 0)
            # свеча с open=T закрыта к entry_ts если T + tf <= entry_ts
            cutoff = entry_ts - pd.Timedelta(seconds=tf_sec)
            d = df[df.index <= cutoff]
        else:
            d = df[df.index <= entry_ts]
        if len(d) > 0:
            sliced[tf] = d
    snap = snapshot_features(sliced, entry_tf, signal=signal, _compute_flags=_compute_flags)
    snap["meta"]["source"] = "backtest"
    snap["meta"]["snapshot_ts"] = entry_ts.isoformat()
    return snap


def snapshot_from_flags_row(
    flags_row: "pd.Series",
    entry_tf: str,
    *,
    signal: Optional[dict] = None,
    snapshot_ts: Optional[str] = None,
) -> dict:
    """Собрать снимок из ГОТОВОЙ строки combinator-флагов (для бэктест-движков).

    В бэктесте `all_flags` (мульти-TF combinator-флаги с суффиксом _{tf}) уже посчитан
    одним проходом — снимок на момент входа = `all_flags.iloc[entry_idx]`. Та же схема,
    что live `snapshot_features`, → parity ПО ОПРЕДЕЛЕНИЮ (один калькулятор, одна упаковка).

    Args:
        flags_row:   pd.Series — одна строка combinator-флагов (имена `{flag}_{tf}`).
        entry_tf:    TF входа (для meta).
        signal:      specifics сигнала.
        snapshot_ts: ISO-время бара входа (если есть); иначе None.
    """
    flag_items = [(col, flags_row[col]) for col in flags_row.index]  # raw (value-cols сохранятся)
    context, n_true, n_total = _pack_context(flag_items)
    tfs_used = sorted({c.rsplit("_", 1)[1] for c in flags_row.index
                       if c.rsplit("_", 1)[-1] in _TF_ORDER},
                      key=lambda t: _TF_ORDER.index(t))
    return _build_snapshot(context, n_true, n_total, entry_tf, tfs_used,
                           signal, source="backtest", snapshot_ts=snapshot_ts)


# Числовые/категориальные колонки (ARCH-118 Шаг 5, вариант B): пишутся ЗНАЧЕНИЕМ,
# не sparse-bool. Это свёртка pivot (nearest/dist/relation) из combinator (один калькулятор).
_VALUE_PREFIXES = ("pivot_nearest_", "pivot_dist_pct_", "pivot_relation_")

# 04.09.2026: НЕПРЕРЫВНЫЕ признаки, добавленные в compute_flags (перцентиль ATR и
# семья CANDLE+VOL). Пишутся ЗНАЧЕНИЕМ по тому же правилу, что `pivot_dist_pct`.
# 🔴 Иначе был бы молчаливый отказ: `_pack_context` считает всё небулево булевым, а
# `bool(0.44)` и `bool(nan)` дают True → 16 непрерывных признаков попали бы в
# n_true/n_total как «сработавшие флаги» и испортили бы и features_json, и долю
# активных флагов, на которую смотрят обучающие срезы.
# 🔴 `engulfing_` СЮДА НЕ ВНОСИТЬ: он float64, но значения ровно {0.0, 1.0} — это
# булев флаг, и ветка `bool(val)` обрабатывает его верно (sparse, участвует в n_total).
# В списке непрерывных он выпал бы из счётчика флагов (187 паттернов его не увидят)
# и писал бы 0.0 в КАЖДЫЙ снимок вопреки sparse-принципу.
# `vol_delta_` наоборот обязан быть здесь: значения {-1, 0, +1}, и `bool(-1.0)` = True
# пометил бы продажный бар как «сработавший флаг».
_NUMERIC_PREFIXES = ("atr_prank", "body_frac_", "upper_wick_frac_", "lower_wick_frac_",
                     "close_pos_in_bar_", "bar_range_pct_", "wick_skew_",
                     "vol_ratio", "vol_x_range_", "vol_delta_", "cum_delta",
                     # 04.09: ликвидность — дистанция в % и сила зоны (число свингов).
                     # `liq_sweep_*` и `liq_near_*` СЮДА НЕ ВНОСИТЬ: они булевы и должны
                     # остаться sparse-флагами, участвующими в n_true/n_total.
                     "liq_up_dist_pct", "liq_dn_dist_pct",
                     "liq_up_strength", "liq_dn_strength")


def _is_value_col(col: str) -> bool:
    return col.startswith(_VALUE_PREFIXES)


def _pack_context(flag_items) -> tuple[dict, int, int]:
    """Упаковать (flag, value) → context по доменам + счётчики. Общий код live+бэктест.

    Булевы флаги — SPARSE (пишутся только true=1). Числовые/категориальные value-колонки
    (pivot nearest/dist/relation) — пишутся ЗНАЧЕНИЕМ в домен pivot (не участвуют в n_true/n_total).
    """
    context: dict[str, dict] = {}
    n_true = 0
    n_total = 0
    for col, val in flag_items:
        if _is_value_col(col):
            if col.startswith("pivot_dist_pct_"):
                fv = float(val) if val is not None else float("nan")
                if fv == fv:  # не nan
                    context.setdefault("pivot", {})[col] = round(fv, 3)
            else:  # nearest / relation — категория
                if val is not None and str(val) != "nan":
                    context.setdefault("pivot", {})[col] = str(val)
            continue
        if col.startswith(_NUMERIC_PREFIXES):     # 04.09: непрерывные — значением
            fv = float(val) if val is not None else float("nan")
            if fv == fv:                          # не nan
                context.setdefault(_domain_of(col), {})[col] = round(fv, 4)
            continue
        n_total += 1
        if bool(val):
            n_true += 1
            context.setdefault(_domain_of(col), {})[col] = 1  # SPARSE: только true
    return context, n_true, n_total


def _build_snapshot(context, n_true, n_total, entry_tf, tfs_used,
                    signal, *, source, snapshot_ts) -> dict:
    """Собрать финальную структуру снимка (единая для live и backtest)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "entry_tf": entry_tf,
            "tfs": tfs_used,
            "snapshot_ts": snapshot_ts,
            "source": source,
            "n_true": n_true,
            "n_total": n_total,
        },
        "context": context,
        "signal": signal or {},
    }


def snapshot_to_vector(snapshot: dict, canon_flags: list[str]) -> dict[str, int]:
    """Декодер sparse-снимка в полный фиксированный вектор для ML.

    Отсутствующий флаг = 0 (false по определению версионированной схемы).

    Args:
        snapshot:    результат snapshot_features (sparse).
        canon_flags: канонический список ВСЕХ флагов схемы (детерминирован compute_flags).

    Returns:
        {flag: 0|1} для всех canon_flags.
    """
    present: dict[str, int] = {}
    for domain_flags in (snapshot.get("context") or {}).values():
        present.update(domain_flags)
    return {flag: int(present.get(flag, 0)) for flag in canon_flags}
