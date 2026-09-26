"""
Загрузчик исторических данных 1h за 2 года.
Источник: Binance Vision (data.binance.vision) — бесплатно, без ключей, без rate limit.
Хранение: Parquet файлы в data/history/1h/<SYMBOL>.parquet

Топ-50 пар — пересечение наших торгуемых и фьючерсов Binance USDT-M.

Запуск: python scripts/fetch_history.py [--symbol BTC] [--all] [--check]
"""
import sys, os, io, zipfile, urllib.request, time, argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

# ─── Конфиг ──────────────────────────────────────────────────────────────────
HISTORY_DIR = Path("data/history/1h")
EXT = ".parquet"
BASE_URL    = "https://data.binance.vision/data/futures/um/daily/klines"
INTERVAL    = "1h"
START_DATE  = datetime(2024, 1, 1, tzinfo=timezone.utc)
END_DATE    = datetime(2026, 5, 17, tzinfo=timezone.utc)

# Топ-50 пар: наши торгуемые (из БД по объёму) — Binance futures символ без /
TOP50 = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LTCUSDT", "LINKUSDT",
    "DOTUSDT", "UNIUSDT", "FILUSDT", "ETCUSDT", "TRXUSDT",
    "SHIBUSDT", "MATICUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
    "SUIUSDT", "PEPEUSDT", "1000BONKUSDT", "ENAUSDT", "INJUSDT",
    "WIFUSDT", "FLOKIUSDT", "MKRUSDT", "AAVEUSDT", "RENDERUSDT",
    "FETUSDT", "GRTUSDT", "KASUSDT", "SEIUSDT", "TIAUSDT",
    "STXUSDT", "JUPUSDT", "RUNEUSDT", "TNSRUSDT", "WLDUSDT",
    "MNTUSDT", "CRVUSDT", "APEUSDT", "GALAUSDT", "ZROUSDT",
    "DYDXUSDT", "ENSUSDT", "ATOMUSDT", "NEARUSDT", "TONUSDT",
]

COLUMNS = ["ts", "open", "high", "low", "close", "volume",
           "close_ts", "quote_vol", "trades", "taker_buy_vol", "taker_buy_quote", "ignore"]

# ─── Утилиты ─────────────────────────────────────────────────────────────────

def binance_sym_to_local(sym: str) -> str:
    """BTCUSDT → BTC/USDT:USDT"""
    base = sym.replace("USDT", "")
    return f"{base}/USDT:USDT"


def fetch_day(symbol: str, date: datetime) -> pd.DataFrame | None:
    """Скачать один день CSV из Binance Vision."""
    date_str = date.strftime("%Y-%m-%d")
    url = f"{BASE_URL}/{symbol}/{INTERVAL}/{symbol}-{INTERVAL}-{date_str}.zip"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = resp.read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            name = zf.namelist()[0]
            with zf.open(name) as f:
                df = pd.read_csv(f)  # заголовок есть в новых файлах Binance Vision
        # Нормализуем имена колонок — могут быть open_time или 0
        df.columns = [str(c).strip() for c in df.columns]
        ts_col = "open_time" if "open_time" in df.columns else df.columns[0]
        df = df.rename(columns={ts_col: "ts"})
        df = df[["ts", "open", "high", "low", "close", "volume"]].copy()
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
        df.set_index("ts", inplace=True)
        return df
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # дня нет — листинг позже
        raise
    except Exception as e:
        print(f"    ERR {symbol} {date_str}: {e}", file=sys.stderr)
        return None


def fetch_symbol(symbol: str, force: bool = False) -> bool:
    """Скачать всю историю для одного символа и сохранить в Parquet."""
    path = HISTORY_DIR / f"{symbol}{EXT}"
    if path.exists() and not force:
        df_ex = pd.read_parquet(path)
        last  = df_ex.index.max()
        print(f"  {symbol}: уже есть {len(df_ex)} баров до {last:%Y-%m-%d}, пропускаем")
        return True

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    cur = START_DATE
    ok, fail = 0, 0
    while cur <= END_DATE:
        df_day = fetch_day(symbol, cur)
        if df_day is not None and not df_day.empty:
            frames.append(df_day)
            ok += 1
        else:
            fail += 1
        cur += timedelta(days=1)
        # Минимальная пауза чтобы не флудить
        if ok % 50 == 0 and ok > 0:
            time.sleep(0.3)

    if not frames:
        print(f"  {symbol}: нет данных")
        return False

    result = pd.concat(frames).sort_index().drop_duplicates()
    result.to_parquet(path, engine="pyarrow", compression="snappy")
    mb = path.stat().st_size / 1024 / 1024
    print(f"  {symbol}: ✅ {len(result)} баров, {ok} дней ({fail} нет), {mb:.1f} MB → {path.name}")
    return True


def check_availability(symbols: list[str], sample_date: str = "2024-06-01") -> None:
    """Быстрая проверка — какие символы доступны на Binance Vision."""
    date = datetime.strptime(sample_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    print(f"Проверяем {len(symbols)} символов на {sample_date}...")
    ok, miss = [], []
    for sym in symbols:
        df = fetch_day(sym, date)
        if df is not None:
            ok.append(sym)
            print(f"  ✅ {sym}")
        else:
            miss.append(sym)
            print(f"  ❌ {sym} (нет на Binance Vision)")
    print(f"\nДоступны: {len(ok)}/{len(symbols)}")
    if miss:
        print(f"Отсутствуют: {', '.join(miss)}")


# ─── Точка входа ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Загрузчик истории 1h из Binance Vision")
    ap.add_argument("--check",  action="store_true", help="Проверить доступность символов")
    ap.add_argument("--symbol", help="Скачать один символ (напр. BTCUSDT)")
    ap.add_argument("--all",    action="store_true", help="Скачать все TOP50")
    ap.add_argument("--force",  action="store_true", help="Перезаписать существующие")
    args = ap.parse_args()

    if args.check:
        check_availability(TOP50[:10])  # первые 10 для быстрой проверки
        return

    if args.symbol:
        sym = args.symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        t0 = time.time()
        fetch_symbol(sym, force=args.force)
        print(f"Время: {time.time()-t0:.1f}с")
        return

    if args.all:
        print(f"Скачиваем TOP50 × 1h × {START_DATE:%Y-%m-%d}–{END_DATE:%Y-%m-%d}")
        print(f"Каждый символ ~500 дней, ориентировочно 2-3 мин на пару\n")
        t0 = time.time()
        done, fail = 0, 0
        for sym in TOP50:
            ok = fetch_symbol(sym, force=args.force)
            if ok: done += 1
            else:  fail += 1
        elapsed = time.time() - t0
        print(f"\n=== Готово: {done} символов, {fail} ошибок, {elapsed/60:.1f} мин ===")
        return

    # По умолчанию — только проверка
    print("Используй: --check | --symbol BTCUSDT | --all")
    print(f"TOP50: {', '.join(TOP50)}")


if __name__ == "__main__":
    main()
