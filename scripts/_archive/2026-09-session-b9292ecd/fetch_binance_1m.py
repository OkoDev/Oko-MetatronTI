"""1m-архивы Binance USDⓈ-M (data.binance.vision, публичные, без ключей) → C:\\oko_history\\1m\\<SYM>USDT.parquet.
Егор 14.09: «Скачать 1m-архивы Binance» — 3m для механики CHoCH 3m на всей базе ядра (145 монет), 2022-12…2026-08.
Существующие паркеты (50 монет, 2025-01+) не затираются: новые месяцы сливаются, дубли по времени убираются.
Формат как у существующих: DatetimeIndex (UTC) + open/high/low/close/volume."""
import io, sys, zipfile, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd

OUT = Path(r"C:\oko_history\1m")
BASE = "https://data.binance.vision/data/futures/um/monthly/klines/{s}/1m/{s}-1m-{m}.zip"
MONTHS = [p.strftime("%Y-%m") for p in pd.period_range("2022-12", "2026-08", freq="M")]
ref = pd.read_parquet(next(OUT.glob("*.parquet")))
TZ = ref.index.tz


def get(url):
    for i in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 + 3 * i)
        except Exception:
            time.sleep(2 + 3 * i)
    return None


def month(s, m):
    raw = get(BASE.format(s=s, m=m))
    if not raw:
        return None
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        txt = z.read(z.namelist()[0])
    df = pd.read_csv(io.BytesIO(txt), header=None, usecols=range(6))
    if not str(df.iloc[0, 0]).isdigit():
        df = df.iloc[1:]
    df.columns = ["t", "open", "high", "low", "close", "volume"]
    df = df.astype({"t": "int64", "open": float, "high": float, "low": float, "close": float, "volume": float})
    idx = pd.to_datetime(df.t, unit="ms", utc=True)
    df.index = idx if TZ is not None else idx.dt.tz_localize(None)
    return df[["open", "high", "low", "close", "volume"]]


def symbol(bingx):
    base = bingx.split("/")[0]
    for cand in (base + "USDT", "1000" + base + "USDT"):
        if get(BASE.format(s=cand, m="2025-06")) is None and get(BASE.format(s=cand, m="2024-06")) is None:
            continue
        parts = []
        with ThreadPoolExecutor(6) as ex:
            for df in ex.map(lambda m: month(cand, m), MONTHS):
                if df is not None:
                    parts.append(df)
        if not parts:
            continue
        new = pd.concat(parts)
        p = OUT / f"{base}USDT.parquet"
        if p.exists():
            new = pd.concat([pd.read_parquet(p), new])
        new = new[~new.index.duplicated(keep="first")].sort_index()
        new.to_parquet(p)
        return f"{bingx} ← {cand}: {len(parts)} мес, {len(new)} баров, {new.index[0]:%Y-%m} … {new.index[-1]:%Y-%m}"
    return f"{bingx}: нет на Binance UM"


syms = [s.strip() for s in open(sys.argv[1], encoding="utf-8") if s.strip()]
print(f"монет: {len(syms)} · месяцев: {len(MONTHS)}", flush=True)
for i, s in enumerate(syms, 1):
    try:
        print(f"[{i}/{len(syms)}] {symbol(s)}", flush=True)
    except Exception as e:
        print(f"[{i}/{len(syms)}] {s}: ОШИБКА {e}", flush=True)
print("ГОТОВО", flush=True)
