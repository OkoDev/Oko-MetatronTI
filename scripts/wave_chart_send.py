#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""WAVE-CHART: стандартный сигнал-чарт бота (свечи+WT+volume+уровни) → TG-канал.

Использует core.ui.chart_builder.build_signal_chart (тот же рендер, что бот шлёт в
сигналах — уровни/пивоты + WaveTrend-панель + volume). Caption: волновая фаза + SMC.

Использование:
  python scripts/wave_chart_send.py SUI --tf 1h
  python scripts/wave_chart_send.py XLM --tf 15m --chat -1001549739381
"""
import sys, os, argparse, asyncio
sys.path.insert(0, r"e:/MTF BOT/CURSOR/crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv()
import ccxt, pandas as pd, requests
from core.ui.chart_builder import build_signal_chart
from core.smc.smc_engine import (zigzag_atr, detect_elliott_impulse,
                                  detect_structure_breaks, _zz_typed)

DEFAULT_CHAT = "-1001549739381"  # Oko - Alerts


def wave_smc_caption(sym, tf, ex):
    """Краткий вердикт: волновая фаза + SMC (CHoCH/BOS) для caption."""
    try:
        o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", tf, limit=150)
        df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
        price = df["close"].iloc[-1]
        li = None
        for d in (3.0, 5.0):
            for imp in detect_elliott_impulse(zigzag_atr(df, 11, d)):
                if li is None or imp["waves"][-1][0] > li["waves"][-1][0]:
                    li = imp
        if li:
            dd = "ВНИЗ ↓" if li["direction"] == "down" else "ВВЕРХ ↑"
            wave = f"импульс {dd}{' ✓textbook' if li['textbook'] else ''}"
        else:
            wave = "коррекция/боковик (импульс не классифицирован)"
        brks = detect_structure_breaks(df, length=5)
        smc = "—"
        if brks:
            b = brks[-1]
            smc = f"{b.kind} {b.direction}{'+V' if b.has_volume else ''}"
        return (f"🌊 <b>{sym} {tf}</b>  цена {price:.5f}\n"
                f"волна: {wave}\n"
                f"SMC: {smc}\n"
                f"— Wave+SMC analyzer (Oko-MetatronTI)")
    except Exception as e:
        return f"🌊 {sym} {tf} (caption err: {str(e)[:40]})"


def send_tg(png_bytes, caption, chat, token):
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    r = requests.post(url, data={"chat_id": chat, "caption": caption, "parse_mode": "HTML"},
                      files={"photo": ("chart.png", png_bytes)}, timeout=30)
    return r.json()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--chat", default=DEFAULT_CHAT)
    a = ap.parse_args()
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("TELEGRAM_TOKEN не найден в .env"); return
    sym = a.symbol.upper()
    full = f"{sym}/USDT:USDT"  # полный формат для chart_builder
    # стандартный сигнал-чарт бота (WT + volume + уровни), без bot → fallback ccxt
    png = await build_signal_chart(full, a.tf, bot=None)
    if not png:
        print(f"чарт не построился для {sym} {a.tf} (blacklist / нет данных?)"); return
    ex = ccxt.bingx()
    cap = wave_smc_caption(sym, a.tf, ex)
    resp = send_tg(png, cap, a.chat, token)
    print("TG:", "✅ отправлено" if resp.get("ok") else f"❌ {resp.get('description', resp)}")


if __name__ == "__main__":
    asyncio.run(main())
