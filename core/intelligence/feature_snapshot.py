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

SCHEMA_VERSION = 2

# TF, для которых compute_flags вызывает pivot-флаги (эталон: только исходный 1h)
_PIVOT_TF = "1h"
# Канонический порядок TF (для сортировки в snapshot_from_flags_row)
_TF_ORDER = ["5m", "15m", "1h", "4h", "1d"]


def _import_cb():
    """Импорт ЕДИНОГО калькулятора (combinator_v2) с защитой от import-time side-effects.

    combinator_v2.py при импорте делает `sys.stdout = TextIOWrapper(...)` (строка 21) —
    в проде это сломало бы stdout/логирование. Сохраняем и восстанавливаем stdout, а
    созданный combinator'ом wrapper отвязываем от buffer'а через detach() (иначе его
    __del__ при GC закроет общий buffer → "I/O operation on closed file").

    При повторном вызове модуль берётся из sys.modules (тело не выполняется заново),
    sys.stdout не трогается → detach пропускается.
    """
    saved_stdout = sys.stdout
    saved_path = list(sys.path)
    try:
        pm_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "tools", "pattern_mining",
        )
        if pm_dir not in sys.path:
            sys.path.insert(0, pm_dir)
        import combinator_v2 as cb  # noqa: WPS433 (намеренно локальный импорт)
        new_wrapper = sys.stdout
        if new_wrapper is not saved_stdout:
            try:
                new_wrapper.detach()  # сервать от buffer, чтобы __del__ его не закрыл
            except Exception:
                pass
        return cb
    finally:
        sys.stdout = saved_stdout  # откатываем side-effect
        sys.path[:] = saved_path


def _import_compute_flags():
    """Единый калькулятор флагов (combinator_v2.compute_flags)."""
    return _import_cb().compute_flags


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
    df_15m = await _fetch_df(data_collector, symbol, "15m", 400)
    if df_15m is not None:
        out["15m"] = df_15m
    cb = _import_cb()
    for htf in ("4h", "1d"):
        try:
            out[htf] = cb.aggregate_tf(df_1h, htf)  # resample из глубокого 1h = parity
        except Exception:
            pass
    if want_5m:
        df_5m = await _fetch_df(data_collector, symbol, "5m", 500)
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
    if flag.startswith(("vol_spike", "bull_mom", "bear_mom")):
        return "mom"
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
        flags_df = compute_flags(df, tf, include_pivots=(tf == _PIVOT_TF))
        if flags_df is None or len(flags_df) == 0:
            continue
        last = flags_df.iloc[-1]  # момент входа = последняя закрытая свеча TF
        tfs_used.append(tf)
        flag_items.extend((col, bool(last[col])) for col in flags_df.columns)

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
    flag_items = [(col, bool(flags_row[col])) for col in flags_row.index]
    context, n_true, n_total = _pack_context(flag_items)
    tfs_used = sorted({c.rsplit("_", 1)[1] for c in flags_row.index
                       if c.rsplit("_", 1)[-1] in _TF_ORDER},
                      key=lambda t: _TF_ORDER.index(t))
    return _build_snapshot(context, n_true, n_total, entry_tf, tfs_used,
                           signal, source="backtest", snapshot_ts=snapshot_ts)


def _pack_context(flag_items) -> tuple[dict, int, int]:
    """Упаковать (flag, bool) → sparse-context по доменам + счётчики. Общий код live+бэктест."""
    context: dict[str, dict[str, int]] = {}
    n_true = 0
    n_total = 0
    for col, val in flag_items:
        n_total += 1
        if val:
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
