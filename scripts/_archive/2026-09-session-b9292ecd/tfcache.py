"""Предрасчёт таймфреймов на диске G: (16.09, Егор: «нужно оптимизировать процессы»).
Каждый замер заново пересобирал 1m → 3m/5m/15m/4h по 2 млн строк на монету — это и был основной расход ЦП и памяти.
Теперь один раз считаем и кладём в G:\\oko_lab\\tf\\<tf>\\<SYM>.parquet; лабы берут готовое через load_tf().
Запуск: python tfcache.py build [N] [proc]   (низкий приоритет, по умолчанию 3 процесса)"""
import sys
from pathlib import Path
from multiprocessing import Pool
import pandas as pd

PARQ = Path("C:/oko_history/1m")
CACHE = Path("G:/oko_lab/tf")
TFS = {"3m": "3min", "5m": "5min", "15m": "15min", "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1D"}
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def load_tf(sym: str, tf: str, tz: str | None = None, cols=None) -> pd.DataFrame:
    """Готовый таймфрейм с диска G:; если кэша нет — считает из 1m на лету (старое поведение).
    Индекс naive-UTC; tz="UTC" — для скриптов, работающих с tz-aware (fifth_zone_lab)."""
    p = CACHE / tf / f"{sym}.parquet"
    if p.exists():
        d = pd.read_parquet(p, columns=cols)
    else:
        b = pd.read_parquet(PARQ / f"{sym}.parquet")[["open", "high", "low", "close", "volume"]]
        if getattr(b.index, "tz", None) is not None:
            b.index = b.index.tz_convert("UTC").tz_localize(None)
        d = b.resample(TFS[tf], label="left", closed="left").agg(AGG).dropna()
        if cols:
            d = d[cols]
    if tz:
        d.index = d.index.tz_localize(tz)
    return d


def build(sym: str):
    try:
        import psutil
        psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS)
    except Exception:
        pass
    try:
        b = pd.read_parquet(PARQ / f"{sym}.parquet")[["open", "high", "low", "close", "volume"]]
        if getattr(b.index, "tz", None) is not None:
            b.index = b.index.tz_convert("UTC").tz_localize(None)
        n = 0
        src_mt = (PARQ / f"{sym}.parquet").stat().st_mtime
        for tf, rule in TFS.items():
            out = CACHE / tf; out.mkdir(parents=True, exist_ok=True)
            f = out / f"{sym}.parquet"
            if f.exists() and f.stat().st_mtime >= src_mt:    # кэш свежее исходника — пересчитывать нечего
                continue
            d = b.resample(rule, label="left", closed="left").agg(AGG).dropna()
            # float64 как в исходных паркетах: на float32 у дешёвых монет теряются знаки и сравнение цены
            # со стопом/целью может разойтись с боевым кодом
            d.to_parquet(f, compression="zstd")
            n += 1
        return sym, f"{n} тф"
    except Exception as e:
        return sym, f"ошибка: {type(e).__name__} {e}"


if __name__ == "__main__":
    syms = sorted(p.stem for p in PARQ.glob("*.parquet"))
    if len(sys.argv) > 2 and sys.argv[2].isdigit():
        syms = syms[:int(sys.argv[2])]
    proc = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    print(f"монет: {len(syms)} · процессов: {proc} · кэш: {CACHE}", flush=True)
    with Pool(proc) as pool:
        for i, (s, msg) in enumerate(pool.imap_unordered(build, syms), 1):
            if i % 20 == 0 or "ошибка" in msg:
                print(f"  {i}/{len(syms)} {s}: {msg}", flush=True)
    tot = sum(f.stat().st_size for f in CACHE.rglob("*.parquet")) / 1024**3
    print(f"готово · размер кэша {tot:.1f} ГБ", flush=True)
