"""Проверить реальный формат Binance Vision CSV."""
import sys, io, zipfile, urllib.request
sys.stdout.reconfigure(encoding='utf-8')

url = "https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT/1h/BTCUSDT-1h-2024-06-01.zip"
print(f"Скачиваем: {url}")
with urllib.request.urlopen(url, timeout=15) as resp:
    data = resp.read()
print(f"Размер ZIP: {len(data)} байт")

with zipfile.ZipFile(io.BytesIO(data)) as zf:
    print(f"Файлы в ZIP: {zf.namelist()}")
    with zf.open(zf.namelist()[0]) as f:
        lines = f.read().decode('utf-8').splitlines()

print(f"Первые 3 строки:")
for i, line in enumerate(lines[:3]):
    print(f"  [{i}] {line[:120]}")
print(f"Всего строк: {len(lines)}")
