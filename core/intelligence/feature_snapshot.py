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


async def _fetch_df(data_collector: Any, symbol: str, tf: str, limit: int):
    """Загрузить OHLCV и привести к стандартному виду (как arch104 observer, parity).

    Поддерживает оба формата индекса: 'ts' (ccxt) и 'time' (data_collector, D-042).
    """
    try:
        df = await data_collector.get_ohlcv(symbol, timeframe=tf, limit=limit)
    except Exception:
        return None
    if df is None or len(df) < 50:
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


async def build_df_by_tf(
    data_collector: Any,
    symbol: str,
    *,
    want_5m: bool = False,
) -> dict[str, "pd.DataFrame"]:
    """Собрать df_by_tf ТЕМ ЖЕ способом, что arch104 observer и бэктест (parity).

    1d = `aggregate_tf(df_1h)` (resample из 1h, как в бэктесте process_symbol),
    остальные TF — нативный fetch. 1h обязателен (без него снимок бессмыслен).
    """
    out: dict[str, Any] = {}
    df_1h = await _fetch_df(data_collector, symbol, "1h", 300)
    if df_1h is None or len(df_1h) < 50:
        return out
    out["1h"] = df_1h
    df_15m = await _fetch_df(data_collector, symbol, "15m", 400)
    if df_15m is not None:
        out["15m"] = df_15m
    df_4h = await _fetch_df(data_collector, symbol, "4h", 200)
    if df_4h is not None and len(df_4h) >= 30:
        out["4h"] = df_4h
    try:
        out["1d"] = _import_cb().aggregate_tf(df_1h, "1d")  # resample = parity
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

    context: dict[str, dict[str, int]] = {}
    n_true = 0
    n_total = 0
    tfs_used: list[str] = []

    for tf, df in df_by_tf.items():
        if df is None or len(df) == 0:
            continue
        flags_df = compute_flags(df, tf, include_pivots=(tf == _PIVOT_TF))
        if flags_df is None or len(flags_df) == 0:
            continue
        last = flags_df.iloc[-1]  # момент входа = последняя закрытая свеча TF
        tfs_used.append(tf)
        for col in flags_df.columns:
            n_total += 1
            if bool(last[col]):
                n_true += 1
                context.setdefault(_domain_of(col), {})[col] = 1  # SPARSE: только true

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "entry_tf": entry_tf,
            "tfs": tfs_used,
            "snapshot_ts": datetime.now(timezone.utc).isoformat(),
            "n_true": n_true,
            "n_total": n_total,
        },
        "context": context,
        "signal": signal or {},
    }
    return snapshot


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
