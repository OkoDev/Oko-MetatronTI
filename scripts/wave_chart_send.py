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
    """Полный сигнал-вердикт: волна + OTE-зона + конфлюэнция + вход/SL/TP/RR + SMC."""
    try:
        from core.smc.smc_engine import _zz_typed, detect_equal_levels
        from core.indicators.indicators import calculate_pivot_points
        o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", tf, limit=150)
        df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
        price = df["close"].iloc[-1]
        # волна
        li = None
        for d in (3.0, 5.0):
            for imp in detect_elliott_impulse(zigzag_atr(df, 11, d)):
                if li is None or imp["waves"][-1][0] > li["waves"][-1][0]:
                    li = imp
        wave = (f"импульс {'ВНИЗ ↓' if li['direction']=='down' else 'ВВЕРХ ↑'}"
                f"{' ✓textbook' if li['textbook'] else ''}") if li else "коррекция/боковик"
        # SMC
        brks = detect_structure_breaks(df, length=5)
        smc = f"{brks[-1].kind} {brks[-1].direction}{'+V' if brks[-1].has_volume else ''}" if brks else "—"
        # OTE-зона последнего движения (Фибо)
        typed = _zz_typed(zigzag_atr(df, 11, 3.0))
        ote, direction = {}, None
        if len(typed) >= 2:
            (_ia, _pa, _ta), (_ib, _pb, _tb) = typed[-2], typed[-1]
            rng = _pb - _pa
            if abs(rng) / price > 0.003:
                for f in (0.618, 0.705, 0.786):
                    ote[f] = _pb - f * rng
                direction = "LONG" if _tb == "H" else "SHORT"  # откат после H = LONG-сетап
        # 4h-пивоты (для конфлюэнции)
        h4 = {}
        try:
            o4 = ex.fetch_ohlcv(f"{sym}/USDT:USDT", "4h", limit=3)
            d4 = pd.DataFrame(o4, columns=["ts", "h2", "h", "l", "c", "v"]); pr = d4.iloc[-2]
            h4 = calculate_pivot_points(float(pr["h"]), float(pr["l"]), float(pr["c"]))
        except Exception:
            pass
        # конфлюэнция Фибо × 4h-пивот (<0.5%)
        confl = []
        for f, flvl in ote.items():
            for pk, pv in h4.items():
                if abs(flvl - pv) / price < 0.005:
                    confl.append(f"{f}×4h-{pk} @{(flvl+pv)/2:.5f}")
        # MTF-OTE контекст: направление + OTE-зона по СТАРШИМ ТФ (основа сетапа)
        mtf = []
        for _mtf in ("1d", "4h", "1h"):
            try:
                _om = ex.fetch_ohlcv(f"{sym}/USDT:USDT", _mtf, limit=150)
                _dm = pd.DataFrame(_om, columns=["ts", "open", "high", "low", "close", "volume"])
                _tm = _zz_typed(zigzag_atr(_dm, 11, 3.0))
                if len(_tm) >= 2:
                    (_a, _pa2, _ta2), (_b2, _pb2, _tb2) = _tm[-2], _tm[-1]
                    _dr = "LONG" if _tb2 == "H" else "SHORT"
                    _rg2 = _pb2 - _pa2
                    _olo, _ohi = _pb2 - 0.786 * _rg2, _pb2 - 0.618 * _rg2
                    _was = "✓был" if (_mtf in ("1d", "4h") and _dm["low"].min() <= min(_olo, _ohi)) else ""
                    mtf.append(f"{_mtf} {_dr}{_was}")
            except Exception:
                pass
        # сборка
        lines = [f"🌊 <b>{sym} {tf}</b>  цена <code>{price:.5f}</code>"]
        if mtf:
            lines.append("📊 MTF: " + " · ".join(mtf))
        lines.append(f"волна: {wave}  |  SMC: {smc}")
        if ote:
            zlo, zhi = ote[0.786], ote[0.618]
            in_zone = min(zlo, zhi) <= price <= max(zlo, zhi)
            lines.append(f"🌀 OTE {direction}: <code>{ote[0.618]:.5f}–{ote[0.786]:.5f}</code>"
                         f"{'  ✅ ЦЕНА В ЗОНЕ' if in_zone else ''}")
            # вход/SL/TP/RR если в зоне
            if in_zone and direction:
                entry = price
                sl = ote[0.786] * (0.997 if direction == "LONG" else 1.003)  # за дальнюю границу
                # TP = ближайший пивот в сторону
                tps = sorted([v for v in h4.values() if (v > entry) == (direction == "LONG")],
                             key=lambda v: abs(v - entry))
                tp = tps[0] if tps else entry * (1.04 if direction == "LONG" else 0.96)
                risk = abs(entry - sl); rr = abs(tp - entry) / risk if risk > 0 else 0
                lines.append(f"💰 вход <code>{entry:.5f}</code> | SL <code>{sl:.5f}</code> "
                             f"| TP <code>{tp:.5f}</code> | R:R <b>1:{rr:.1f}</b>")
        if confl:
            lines.append("⭐ конфлюэнция: " + " · ".join(confl[:3]))
        lines.append("— Oko-MetatronTI · Wave+SMC")
        return "\n".join(lines)
    except Exception as e:
        return f"🌊 {sym} {tf} (caption err: {str(e)[:50]})"


def send_tg(png_bytes, caption, chat, token):
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    r = requests.post(url, data={"chat_id": chat, "caption": caption, "parse_mode": "HTML"},
                      files={"photo": ("chart.png", png_bytes)}, timeout=30)
    return r.json()


def send_media_group(media_list, caption, chat, token):
    """media_list = [(tf, png_bytes)]. Несколько чартов ОДНИМ постом (мульти-TF фрактал)."""
    import json
    url = f"https://api.telegram.org/bot{token}/sendMediaGroup"
    media, files = [], {}
    for i, (tf, png) in enumerate(media_list):
        files[f"file{i}"] = (f"{tf}.png", png)
        m = {"type": "photo", "media": f"attach://file{i}"}
        if i == 0:  # caption на первом фото = подпись всего альбома
            m["caption"] = caption; m["parse_mode"] = "HTML"
        media.append(m)
    r = requests.post(url, data={"chat_id": chat, "media": json.dumps(media)},
                      files=files, timeout=60)
    return r.json()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--tfs", default="5m,15m,1h",
                    help="ТФ через запятую (мульти-TF одним постом). Один ТФ = одиночный чарт.")
    ap.add_argument("--chat", default=DEFAULT_CHAT)
    a = ap.parse_args()
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("TELEGRAM_TOKEN не найден в .env"); return
    sym = a.symbol.upper()
    full = f"{sym}/USDT:USDT"
    tfs = [t.strip() for t in a.tfs.split(",") if t.strip()]
    ex = ccxt.bingx()
    # caption по СТАРШЕМУ ТФ (контекст) — последний в списке
    cap = wave_smc_caption(sym, tfs[-1], ex)
    cap = f"{cap}\n📊 мульти-TF: {' · '.join(tfs)}"
    # рендерим чарты на каждом ТФ
    media = []
    for tf in tfs:
        png = await build_signal_chart(full, tf, bot=None, wave_overlay=True)
        if png:
            media.append((tf, png))
        else:
            print(f"  {tf}: не построился (blacklist/нет данных)")
    if not media:
        print(f"ни один чарт не построился для {sym}"); return
    if len(media) == 1:
        resp = send_tg(media[0][1], cap, a.chat, token)
    else:
        resp = send_media_group(media, cap, a.chat, token)
    ok = resp.get("ok") if isinstance(resp, dict) else False
    print(f"TG: {'✅ отправлено '+str(len(media))+' чарт(ов)' if ok else '❌ '+str(resp)[:80]}")


if __name__ == "__main__":
    asyncio.run(main())
