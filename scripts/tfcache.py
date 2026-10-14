# -*- coding: utf-8 -*-
"""Предрасчёт таймфреймов для ЗАМЕРОВ: 1m-паркеты → G:/oko_lab/tf/<tf>/<SYM>.parquet.

Вид B по паспорту инструмента (`docs/TOOL_CONTRACT.md`): запускается по расписанию, отчитывается строкой итога.

Зачем. Каждый замер пересобирал 1m → 3m/5m/15m/4h по 2 млн строк на монету — это и было узкое место
(16.09.2026, Егор: «оптимизировать процесс»). Готовый ТФ читается за 0.7 с на монету.

🔴 13.10.2026: инструмент лежал в `scripts/_archive` и указывал на `C:/oko_history/1m` — путь, которого нет.
ТФ-паркеты отстали на 27 суток, и никто этого не видел. Возвращён в `scripts/`, путь исправлен на
`C:/oko_data/history/1m`, добавлены: пропуск неизменившихся монет, отчёт и проверка свежести.

Запуск:
    python scripts/tfcache.py refresh          # докачать хвост 1m + пересобрать (ночная pm2-задача)
    python scripts/tfcache.py build            # пересобрать устаревшие (по времени файла 1m)
    python scripts/tfcache.py build --all      # пересобрать всё заново
    python scripts/tfcache.py status           # что отстаёт

🔴 Хранилище ЗАМЕРОВ (Binance 1m → ТФ). НЕ путать с онлайн-кэшем бота (`cache_topup_cron.py`, другой контур).
"""
from __future__ import annotations

import argparse
import multiprocessing
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import pandas as pd


def _use_windowless_workers() -> None:
    """Windows: воркеры Pool со spawn получают НОВОЕ окно консоли — при каждом build всплывали пустые
    python-окна (в т.ч. из ночной pm2-задачи tfcache-refresh 04:20). pythonw.exe делает ту же работу без
    окна; родитель остаётся на python.exe и печатает отчёт как раньше. На не-Windows и если pythonw нет —
    ничего не меняем."""
    if sys.platform != "win32":
        return
    pyw = Path(sys.executable).with_name("pythonw.exe")
    if pyw.exists():
        multiprocessing.set_executable(str(pyw))

PARQ = Path("C:/oko_data/history/1m")        # источник: минутки Binance (замеры идут на них)
CACHE = Path("G:/oko_lab/tf")                # приёмник: готовые ТФ для лабораторий
TFS = {"3m": "3min", "5m": "5min", "15m": "15min", "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1D"}
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def load_tf(sym: str, tf: str, tz: str | None = None, cols=None) -> pd.DataFrame:
    """Готовый таймфрейм с диска; если кэша нет — считает из 1m на лету. Индекс naive-UTC."""
    p = CACHE / tf / f"{sym}.parquet"
    if p.exists():
        d = pd.read_parquet(p, columns=cols)
    else:
        b = pd.read_parquet(PARQ / f"{sym}.parquet")[["open", "high", "low", "close", "volume"]]
        if getattr(b.index, "tz", None) is not None:
            b.index = b.index.tz_convert("UTC").tz_localize(None)
        d = b.resample(TFS[tf]).agg(AGG).dropna()
        if cols:
            d = d[cols]
    if tz and getattr(d.index, "tz", None) is None:
        d.index = d.index.tz_localize(tz)
    return d


def _needs_rebuild(sym: str) -> bool:
    """Пересобирать, если 1m новее любого из ТФ-файлов (или ТФ-файла нет)."""
    src = PARQ / f"{sym}.parquet"
    if not src.exists():
        return False
    src_m = src.stat().st_mtime
    for tf in TFS:
        p = CACHE / tf / f"{sym}.parquet"
        if not p.exists() or p.stat().st_mtime < src_m:
            return True
    return False


def build(sym: str) -> tuple[str, int, str]:
    """Пересобрать все ТФ одной монеты. Возвращает (символ, число ТФ, сообщение об ошибке)."""
    try:
        b = pd.read_parquet(PARQ / f"{sym}.parquet")[["open", "high", "low", "close", "volume"]]
        if getattr(b.index, "tz", None) is not None:
            b.index = b.index.tz_convert("UTC").tz_localize(None)
        n = 0
        for tf, rule in TFS.items():
            d = b.resample(rule).agg(AGG).dropna()
            if not len(d):
                continue
            out = CACHE / tf
            out.mkdir(parents=True, exist_ok=True)
            d.to_parquet(out / f"{sym}.parquet", compression="zstd")
            n += 1
        return sym, n, ""
    except Exception as e:                                   # noqa: BLE001
        return sym, 0, f"{type(e).__name__}: {e}"


def status() -> int:
    """Свежесть ТФ-паркетов против источника. Код возврата 1 — что-то отстало."""
    now = pd.Timestamp.utcnow().tz_localize(None)
    src = PARQ / "BTCUSDT.parquet"
    if src.exists():
        d = pd.read_parquet(src, columns=["close"])
        print(f"источник 1m (BTC): последний бар {d.index[-1]:%Y-%m-%d %H:%M} · "
              f"отстаёт {(now - d.index[-1]).total_seconds() / 86400:.1f} сут")
    stale = 0
    for tf in TFS:
        p = CACHE / tf / "BTCUSDT.parquet"
        if not p.exists():
            print(f"   {tf:<4} нет файла")
            stale += 1
            continue
        d = pd.read_parquet(p, columns=["close"])
        age = (now - d.index[-1]).total_seconds() / 86400
        print(f"   {tf:<4} последний бар {d.index[-1]:%Y-%m-%d %H:%M} · отстаёт {age:5.1f} сут{'  🔴' if age > 3 else ''}")
        stale += age > 3
    syms = sorted(p.stem for p in PARQ.glob("*.parquet"))
    need = [s for s in syms if _needs_rebuild(s)]
    print(f"монет в источнике: {len(syms)} · требуют пересборки: {len(need)}")
    return 1 if (stale or need) else 0


def refresh(days: int = 40, procs: int = 3) -> int:
    """Докачать хвост 1m за последние `days` дней + пересобрать изменившиеся ТФ. Для ночной pm2-задачи.

    Докачку делает тот же `fetch_binance_vision --out parquet`, что и руками: дневными архивами Binance,
    резюмируемо. Затем `build` пересоберёт только монеты, у которых 1m стал новее ТФ."""
    import subprocess
    since = (pd.Timestamp.utcnow() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    print(f"[tfcache refresh] докачка 1m с {since} → {PARQ}")
    r = subprocess.run([sys.executable, str(Path(__file__).with_name("fetch_binance_vision.py")),
                        "--out", "parquet", "--tfs", "1m", "--since-day", since,
                        "--outdir", str(PARQ.parent)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    for line in (r.stdout or "").splitlines()[-3:]:
        print("   " + line)
    if r.returncode != 0:
        print(f"[tfcache refresh] 🔴 докачка 1m вернула {r.returncode}: {(r.stderr or '')[:200]}")
    return _build(procs=procs, only_stale=True)


def _build(procs: int, only_stale: bool, limit: int = 0) -> int:
    syms = sorted(p.stem for p in PARQ.glob("*.parquet"))
    if only_stale:
        syms = [s for s in syms if _needs_rebuild(s)]
    if limit:
        syms = syms[:limit]
    if not syms:
        print("[tfcache] пересобирать нечего — все ТФ новее своих 1m")
        return 0
    print(f"[tfcache] пересобираю {len(syms)} монет × {len(TFS)} ТФ, процессов {procs}")
    _use_windowless_workers()
    t0 = time.time()
    done = errs = 0
    with Pool(procs) as pool:
        for i, (sym, n, err) in enumerate(pool.imap_unordered(build, syms), 1):
            if err:
                errs += 1
                print(f"   🔴 {sym}: {err}")
            else:
                done += 1
            if i % 50 == 0:
                print(f"   {i}/{len(syms)} · {time.time() - t0:.0f} с")
    print(f"[tfcache] ГОТОВО: монет {done}, ошибок {errs}, за {time.time() - t0:.0f} с")
    return 1 if errs else 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # молчим: настройка кодировки консоли, на расчёт не влияет
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "status", "refresh"])
    ap.add_argument("--all", action="store_true", help="пересобрать все монеты, а не только устаревшие")
    ap.add_argument("--procs", type=int, default=3, help="процессов (по умолчанию 3 — чтобы не мешать боту)")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "status":
        return status()
    if a.cmd == "refresh":
        return refresh(procs=a.procs)
    return _build(procs=a.procs, only_stale=not a.all, limit=a.limit)


if __name__ == "__main__":
    sys.exit(main())
