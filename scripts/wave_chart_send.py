#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""WAVE-CHART: размеченный график (волна+OB+FVG+EQL+пивоты) → PNG → TG-канал.

Использование:
  python scripts/wave_chart_send.py XLM
  python scripts/wave_chart_send.py BTC --tf 15m
  python scripts/wave_chart_send.py SOL --chat -1001549739381

Рендер: matplotlib (свечи + ZigZag-волна с нумерацией 0-1-2-3 + OB-боксы bull/bear +
FVG-штрих + EQL + 4h/daily-пивоты). Caption: вердикт волна+SMC+конфлюэнция.
Доставка: TG sendPhoto (chat_id канала). Юзер в РФ — TG-канал работает.
"""
import sys, os, argparse
sys.path.insert(0, r"e:/MTF BOT/CURSOR/crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv()
import ccxt, pandas as pd, requests
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from core.smc.smc_engine import (
    zigzag_atr, detect_structure_breaks, detect_order_blocks,
    detect_fvg, detect_equal_levels, detect_elliott_impulse, _zz_typed,
)
from core.indicators.indicators import calculate_pivot_points

DEFAULT_CHAT = "-1001549739381"


def adaptive_dev(df, target=8):
    """ARCH-96 инсайт юзера: dev адаптируется под TF/окно (целевое N swing ~8)."""
    best_dev, best_diff = 3.0, 1e9
    for dev in (1.5, 2.0, 2.5, 3.0, 4.0):
        n = len(zigzag_atr(df, 11, dev))
        if abs(n - target) < best_diff:
            best_diff, best_dev = abs(n - target), dev
    return best_dev


def render(sym, tf, ex):
    o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", tf, limit=150)
    df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
    price = df["close"].iloc[-1]; n = len(df)
    dev = adaptive_dev(df)  # адаптивный dev под TF
    fig, ax = plt.subplots(figsize=(16, 9)); fig.patch.set_facecolor("#0e1117"); ax.set_facecolor("#0e1117")
    for i, r in df.iterrows():
        col = "#26a69a" if r["close"] >= r["open"] else "#ef5350"
        ax.plot([i, i], [r["low"], r["high"]], color=col, linewidth=0.7, zorder=2)
        ax.add_patch(Rectangle((i - 0.3, min(r["open"], r["close"])), 0.6,
                     abs(r["close"] - r["open"]) or price * 1e-5, facecolor=col, edgecolor=col, zorder=3))
    # ZigZag + волновые метки (нумерация с 0)
    typed = _zz_typed(zigzag_atr(df, 11, dev))
    ax.plot([i for i, _, _ in typed], [p for _, p, _ in typed], color="#ffa726",
            linewidth=1.4, zorder=4, alpha=0.85, label=f"ZigZag dev={dev}")
    for k, (idx, p, t) in enumerate(typed[-10:]):
        ax.annotate(str(k), (idx, p), color="#ffd54f", fontsize=13, fontweight="bold",
                    zorder=7, ha="center", va="bottom" if t == "H" else "top")
    # OB
    brks = detect_structure_breaks(df, length=5)
    for b in detect_order_blocks(df, brks):
        if b.mitigated_idx != -1: continue
        col = "#26a69a" if b.kind == "bull" else "#ef5350"
        ax.add_patch(Rectangle((b.left_idx, b.bottom), n - b.left_idx, b.top - b.bottom,
                     facecolor=col, alpha=0.13, edgecolor=col, linewidth=1.0, zorder=1))
        ax.text(n + 0.5, (b.top + b.bottom) / 2, f"OB {b.kind}", color=col, fontsize=7, va="center")
    # FVG (близкие)
    for f in detect_fvg(df)[-12:]:
        top, bot, kind = f[1], f[2], f[3]
        if abs((top + bot) / 2 - price) / price > 0.025: continue
        col = "#42a5f5" if kind == "bull" else "#ff7043"
        ax.add_patch(Rectangle((f[0], min(top, bot)), n - f[0], abs(top - bot),
                     facecolor=col, alpha=0.16, edgecolor=col, linewidth=0.6, zorder=1, hatch="///"))
    # EQL
    for e in detect_equal_levels(df)[-4:]:
        ax.axhline(e[1], color="#ab47bc", linestyle=":", linewidth=0.7, alpha=0.5, zorder=2)
    # пивоты 4h
    o4 = ex.fetch_ohlcv(f"{sym}/USDT:USDT", "4h", limit=3)
    d4 = pd.DataFrame(o4, columns=["ts", "o", "h", "l", "c", "v"]); pr = d4.iloc[-2]
    piv = calculate_pivot_points(float(pr["h"]), float(pr["l"]), float(pr["c"]))
    for kk, c2 in [("R2", "#ef5350"), ("R1", "#ff9800"), ("PP", "#ffeb3b"), ("S1", "#4caf50"), ("S2", "#26a69a")]:
        if kk in piv:
            ax.axhline(piv[kk], color=c2, linestyle="--", linewidth=0.8, alpha=0.55, zorder=2)
            ax.text(n + 5, piv[kk], f"4h-{kk} {piv[kk]:.4f}", color=c2, fontsize=8, va="center")
    ax.axhline(price, color="#fff", linewidth=0.6, alpha=0.5)
    ax.set_title(f"{sym} {tf} — Wave+SMC (волна / OB / FVG / 4h-пивоты)  цена={price:.5f}",
                 color="#e0e0e0", fontsize=12, fontweight="bold")
    ax.tick_params(colors="#888"); [s.set_color("#333") for s in ax.spines.values()]
    ax.legend(loc="upper left", framealpha=0.3, facecolor="#1e222d", labelcolor="#ccc")
    plt.tight_layout()
    out = f"e:/tmp/wave_chart_{sym}_{tf}.png"
    plt.savefig(out, dpi=95, facecolor="#0e1117"); plt.close()
    # caption: волновая фаза
    li = None
    for d in (3.0, 5.0):
        for imp in detect_elliott_impulse(zigzag_atr(df, 11, d)):
            if li is None or imp["waves"][-1][0] > li["waves"][-1][0]: li = imp
    phase = "?"
    if li:
        dd = "↓" if li["direction"] == "down" else "↑"
        phase = f"ИМП{dd}{'✓' if li['textbook'] else ''}"
    cap = f"🌊 <b>{sym} {tf}</b>  цена {price:.5f}\nволна: {phase}  |  dev={dev}\nWave+SMC: OB/FVG/EQL/4h-пивоты на графике"
    return out, cap


def send_tg(png, caption, chat, token):
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    with open(png, "rb") as f:
        r = requests.post(url, data={"chat_id": chat, "caption": caption, "parse_mode": "HTML"},
                          files={"photo": f}, timeout=30)
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--chat", default=DEFAULT_CHAT)
    a = ap.parse_args()
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("TELEGRAM_TOKEN не найден в .env"); return
    ex = ccxt.bingx()
    png, cap = render(a.symbol.upper(), a.tf, ex)
    print(f"PNG: {png}")
    resp = send_tg(png, cap, a.chat, token)
    print("TG:", "✅ отправлено" if resp.get("ok") else f"❌ {resp.get('description', resp)}")


if __name__ == "__main__":
    main()
