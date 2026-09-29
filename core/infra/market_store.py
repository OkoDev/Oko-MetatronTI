# -*- coding: utf-8 -*-
"""Сфера 1 — единое хранилище ЗАКРЫТЫХ баров (BACKLOG N15; решения Егора 28.09: BingX по умолчанию,
Binance — исследования, формат — паркеты, рабочие ТФ от 3m).

Закон переиспользования: процессу нужен рынок → он ЧИТАЕТ отсюда, а не качает сам. Биржа, ТФ и глубина —
параметры чтения, а не отдельные загрузчики (инвентаризация: docs/MARKET_DATA_INVENTORY.md).

Раскладка: {ROOT}/{exchange}/{tf}/{BASE}/{YYYY-MM}.parquet, колонки time (мс UTC, ОТКРЫТИЕ бара) + OHLCV.
Только закрытые бары. Прошлые месяцы не меняются; текущий перезаписывается атомарно (tmp → replace) —
на Windows читатель может держать файл, поэтому запись повторяется.

Кто пишет: scripts/market_store_service.py (начальная глубина + догрузка при закрытии бара).
Кто читает: read_bars(...) — тот же формат, что core/waves/bingx_klines.fetch_closed (drop-in).
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(os.environ.get("OKO_MARKET_STORE", "C:/oko_data/market"))
COLS = ["open", "high", "low", "close", "volume"]

# Синтетика BingX — не крипта: акции (NCSK*), валютные пары (NCFX*), сырьё (NCCO*), индексы (NCSI*).
# 16.09 их было 592 из 1180 пар (перенесено из scripts/wave5_shadow.py — один фильтр на всех).
SYNTH_PREFIXES = ("NCSK", "NCFX", "NCCO", "NCSI")


def is_synthetic(base: str) -> bool:
    return base.upper().startswith(SYNTH_PREFIXES)


def base_of(sym: str) -> str:
    """«SOLV», «SOLV/USDT», «SOLV/USDT:USDT», «SOLV-USDT» → «SOLV»."""
    return sym.split("/")[0].split(":")[0].split("-")[0].upper()


def _dir(base: str, tf: str, exchange: str) -> Path:
    return ROOT / exchange / tf / base_of(base)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """В каноническую форму: колонка time (мс), OHLCV float64, без дублей, по времени."""
    d = df.copy()
    if "time" not in d.columns:
        idx = pd.DatetimeIndex(d.index)
        idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
        d = d.assign(time=idx.asi8 // 1_000_000)
    d = d[["time"] + COLS].astype({"time": "int64", **{c: "float64" for c in COLS}})
    return d.drop_duplicates("time", keep="last").sort_values("time").reset_index(drop=True)


def _replace_retry(tmp: Path, path: Path, tries: int = 20) -> None:
    for i in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:                      # читатель держит файл (Windows)
            time.sleep(0.1 * (i + 1))
    raise PermissionError(f"не удалось заменить {path}")


def append_bars(base: str, tf: str, df: pd.DataFrame, exchange: str = "bingx") -> int:
    """Дописать закрытые бары. Совпавшее время перезаписывается новым значением. Возврат: новых строк."""
    if df is None or len(df) == 0:
        return 0
    new = _normalize(df)
    folder = _dir(base, tf, exchange)
    folder.mkdir(parents=True, exist_ok=True)
    added = 0
    months = pd.to_datetime(new.time, unit="ms", utc=True).dt.strftime("%Y-%m")
    for month, part in new.groupby(months.to_numpy()):
        path = folder / f"{month}.parquet"
        if path.exists():
            old = pd.read_parquet(path)
            added += int((~part.time.isin(old.time)).sum())
            part = pd.concat([old, part], ignore_index=True).drop_duplicates("time", keep="last").sort_values("time")
        else:
            added += len(part)
        tmp = path.with_suffix(".tmp")
        part.reset_index(drop=True).to_parquet(tmp, compression="zstd", index=False)
        _replace_retry(tmp, path)
    return added


def _months(base: str, tf: str, exchange: str) -> list[Path]:
    folder = _dir(base, tf, exchange)
    return sorted(folder.glob("*.parquet")) if folder.exists() else []


def _read(path: Path, tries: int = 10) -> pd.DataFrame:
    for i in range(tries):
        try:
            return pd.read_parquet(path)
        except (OSError, PermissionError):           # файл как раз заменяется
            time.sleep(0.05 * (i + 1))
    return pd.read_parquet(path)


def last_time(base: str, tf: str, exchange: str = "bingx") -> Optional[int]:
    """Время открытия последнего сохранённого бара (мс) или None."""
    files = _months(base, tf, exchange)
    return int(_read(files[-1]).time.max()) if files else None


CLOSED_STATS: dict = {"store": 0, "rest": 0}      # сколько раз closed_bars отдал из хранилища / ушёл в REST


def closed_bars(sym: str, tf: str, n: int, now: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    """Для клиентов Сферы 1 — drop-in замена core.waves.bingx_klines.fetch_closed: до n закрытых баров на момент
    now (DatetimeIndex UTC, OHLCV). Из хранилища; в REST BingX — только если хранилище отстало от последнего
    закрытого бара, в окне дыра или истории меньше n, а в хранилище она не кончилась (монета не молодая)."""
    from core.trading.source_registry import _TF_MIN
    now = now or pd.Timestamp.utcnow()
    step = pd.Timedelta(minutes=_TF_MIN[tf])
    since = now - step * (n + 2)
    d = read_bars(base_of(sym), tf, since_ms=int(since.value // 1_000_000))
    d = d[d.index + step <= now].iloc[-n:]
    last_closed = now.floor(step) - step
    fresh = len(d) > 0 and d.index[-1] >= last_closed
    whole = len(d) < 2 or bool((d.index[1:] - d.index[:-1] == step).all())
    enough = len(d) >= n or (len(d) > 0 and d.index[0] > since + step)   # молодая: в хранилище вся её история
    if fresh and whole and enough:
        CLOSED_STATS["store"] += 1
        return d
    CLOSED_STATS["rest"] += 1
    from core.waves.bingx_klines import fetch_closed
    return fetch_closed(sym, tf, n, now=now)


def bars_with_forming(sym: str, tf: str, n: int, now: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    """n баров, последний — текущий незакрытый (как у REST-клиентов «с живым краем»): n−1 закрытых из хранилища
    (closed_bars) + один короткий запрос за текущим баром. Текущий не пришёл → только закрытые."""
    from core.waves.bingx_klines import fetch_forming
    now = now or pd.Timestamp.utcnow()
    closed = closed_bars(sym, tf, n - 1, now=now)
    live = fetch_forming(sym, tf, now=now)
    return pd.concat([closed, live]) if len(live) else closed


def read_bars(base: str, tf: str, n: Optional[int] = None, since_ms: Optional[int] = None,
              exchange: str = "bingx") -> pd.DataFrame:
    """Закрытые бары: DatetimeIndex UTC (открытие бара), колонки open/high/low/close/volume.
    n — последние n баров; since_ms — начиная с этого времени. Ничего нет → пустой DataFrame."""
    parts, have = [], 0
    for path in reversed(_months(base, tf, exchange)):
        d = _read(path)
        parts.append(d)
        have += len(d)
        if since_ms is not None and len(d) and int(d.time.min()) <= since_ms:
            break
        if since_ms is None and n is not None and have >= n:
            break
    if not parts:
        return pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], tz="UTC", name="ts"))
    df = pd.concat(parts[::-1], ignore_index=True).drop_duplicates("time").sort_values("time")
    if since_ms is not None:
        df = df[df.time >= since_ms]
    if n is not None:
        df = df.iloc[-n:]
    df.index = pd.DatetimeIndex(pd.to_datetime(df.time, unit="ms", utc=True), name="ts")
    return df[COLS]
