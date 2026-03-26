"""
Тестовая отправка сигнала с графиком в Telegram.

Запуск:
    python scripts/send_test_signal.py
"""
import asyncio
import io
import os
import sys

import aiohttp
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("ADMIN_ID") or os.getenv("CHAT_ID")

# ── Импорт chart-функций (sys.argv не влияет на них) ──────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from chart_example import fetch_ohlcv, calculate_wt, build_chart  # noqa: E402

BARS   = 300
WARMUP = 80
TF     = "1h"


async def send_photo(session: aiohttp.ClientSession, chat_id: str,
                     png: bytes, caption: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    form = aiohttp.FormData()
    form.add_field("chat_id", chat_id)
    form.add_field("caption", caption, content_type="text/plain")
    form.add_field("parse_mode", "HTML")
    form.add_field("photo", io.BytesIO(png),
                   filename="chart.png", content_type="image/png")
    async with session.post(url, data=form) as r:
        data = await r.json()
        if not data.get("ok"):
            print(f"  Telegram error: {data}")


async def make_signal(symbol_arg: str) -> tuple[bytes, str]:
    symbol = f"{symbol_arg}/USDT"
    print(f"  Загружаю {symbol} {TF}...")
    df_full = await fetch_ohlcv(symbol, TF, BARS + WARMUP)
    df_full = calculate_wt(df_full)
    df = df_full.iloc[-BARS:].copy()

    last   = df["close"].iloc[-1]
    wt1    = round(float(df["wt1"].iloc[-1]), 2)
    wt2    = round(float(df["wt2"].iloc[-1]), 2)
    pct    = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
    sign   = "+" if pct >= 0 else ""
    zone   = "🔴 OB" if wt1 > 60 else ("🟢 OS" if wt1 < -60 else "⚪ нейтраль")

    caption = (
        f"<b>📊 {symbol}  ·  {TF}</b>\n"
        f"Цена: <b>${last:.5g}</b>  ({sign}{pct:.1f}%)\n"
        f"WT1: <b>{wt1}</b>  WT2: {wt2}  {zone}\n"
        f"\n<i>⚡ Тестовый сигнал — chart_example</i>"
    )

    png = build_chart(df, symbol, TF, "")
    return png, caption


async def main():
    symbols = ["GRT", "BTC"]
    async with aiohttp.ClientSession() as session:
        for sym in symbols:
            try:
                png, caption = await make_signal(sym)
                print(f"  Отправляю {sym}...")
                await send_photo(session, CHAT_ID, png, caption)
                print(f"  ✓ {sym} отправлен")
            except Exception as e:
                print(f"  ✗ {sym} ошибка: {e}")


if __name__ == "__main__":
    asyncio.run(main())
