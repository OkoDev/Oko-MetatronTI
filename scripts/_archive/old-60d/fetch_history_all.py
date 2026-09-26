"""
Массовая загрузка TOP50 исторических данных 1h.
Запускает fetch_history.py последовательно для каждой пары.
Пропускает уже скачанные. Выводит итог.

Запуск: python scripts/fetch_history_all.py [--force]
"""
import sys, time, subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

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

PYTHON = r"C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe"
SCRIPT = "scripts/fetch_history.py"
HISTORY_DIR = Path("data/history/1h")
force = "--force" in sys.argv

done, skip, fail = [], [], []
t0 = time.time()

print(f"Загрузка TOP50 × 1h × 2024-01-01–2026-05-17")
print(f"Пропускаем уже существующие {'(force=off)' if not force else '(force=on)'}\n")

for i, sym in enumerate(TOP50, 1):
    path = HISTORY_DIR / f"{sym}.parquet"
    if path.exists() and not force:
        size_mb = path.stat().st_size / 1024 / 1024
        print(f"  [{i:>2}/50] {sym:<15} уже есть ({size_mb:.1f} MB) — пропуск")
        skip.append(sym)
        continue

    print(f"  [{i:>2}/50] {sym:<15} скачиваем...", end=" ", flush=True)
    t_sym = time.time()
    cmd = [PYTHON, SCRIPT, "--symbol", sym] + (["--force"] if force else [])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    elapsed = time.time() - t_sym

    if result.returncode == 0:
        if path.exists():
            size_mb = path.stat().st_size / 1024 / 1024
            print(f"✅ {size_mb:.1f} MB за {elapsed:.0f}с")
            done.append(sym)
        else:
            print(f"⚠️ файл не создан")
            fail.append(sym)
    else:
        err = (result.stderr or result.stdout or "")[-200:]
        print(f"❌ {err.strip()}")
        fail.append(sym)

elapsed_total = time.time() - t0
print(f"\n{'='*50}")
print(f"Готово: {len(done)} скачано, {len(skip)} пропущено, {len(fail)} ошибок")
print(f"Время: {elapsed_total/60:.1f} мин")
if fail:
    print(f"Ошибки: {', '.join(fail)}")

# Итоговый размер
total_mb = sum(
    (HISTORY_DIR / f"{s}.parquet").stat().st_size / 1024 / 1024
    for s in done + skip
    if (HISTORY_DIR / f"{s}.parquet").exists()
)
print(f"Итого на диске: {total_mb:.0f} MB")
