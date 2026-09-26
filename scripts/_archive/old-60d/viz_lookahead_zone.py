# -*- coding: utf-8 -*-
"""Визуализация lookahead: ХИНДСАЙТ-зона vs PIT-зона на BTC 4h (увидеть глазами разницу).

ХИНДСАЙТ (как было в бэктесте): select_significant_impulse на ПОЛНОМ df → выбирает ногу
по цене КОНЦА всей истории (хиндсайт) → нога тянется в БУДУЩЕЕ относительно сделки.
PIT (честно): тот же выбор на СРЕЗЕ df до момента слома → нога только из прошлого.

Запуск: python scripts/viz_lookahead_zone.py [--sym BTC/USDT] [--asof 2025-11-05] [--out e:/tmp/oko_lookahead.png]
"""
import argparse, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

CACHE = ROOT / "ohlcv_cache.db"


def _load(conn, sym, tf):
    df = pd.read_sql_query(
        "SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
        conn, params=(sym, tf))
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df


def _candles(ax, d):
    w = 0.12  # ширина тела (дни)
    x = mdates.date2num(d.index.to_pydatetime())
    for xi, (_, r) in zip(x, d.iterrows()):
        up = r["close"] >= r["open"]
        col = "#26a69a" if up else "#ef5350"
        ax.plot([xi, xi], [r["low"], r["high"]], color=col, lw=0.6, zorder=2)
        ax.add_patch(plt.Rectangle((xi - w / 2, min(r["open"], r["close"])), w,
                                   max(abs(r["close"] - r["open"]), 1e-9),
                                   color=col, zorder=3))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", default="BTC/USDT")
    ap.add_argument("--asof", default="2025-11-05")
    ap.add_argument("--out", default="e:/tmp/oko_lookahead.png")
    a = ap.parse_args()
    from core.smc.smc_engine import zigzag_atr, select_significant_impulse, adaptive_dev
    from core.smc.smc_snapshot import _zz_params

    conn = sqlite3.connect(CACHE, timeout=60)
    d = _load(conn, a.sym, "4h"); conn.close()
    dp, _ = _zz_params("4h")
    asof = pd.Timestamp(a.asof, tz="UTC")

    # ХИНДСАЙТ: на полном df (current_price = последний бар ВСЕЙ истории)
    zz_full = zigzag_atr(d, depth=dp, dev_mult=adaptive_dev(d, dp))
    h_hind = select_significant_impulse(d, zz_full)
    # PIT: срез до asof
    d_cut = d.loc[:asof]
    zz_cut = zigzag_atr(d_cut, depth=dp, dev_mult=adaptive_dev(d_cut, dp))
    h_pit = select_significant_impulse(d_cut, zz_cut)

    # окно отрисовки: вокруг сделки + видно обе ноги
    view = d.loc["2025-08-01":"2026-03-01"]
    fig, ax = plt.subplots(figsize=(16, 8))
    _candles(ax, view)

    def draw_zone(h, color, label, ytext):
        if not h:
            return
        olo, ohi = h["ote"]
        fr_ts, fr_p = h["from"]; to_ts, to_p = h["to"]
        # OTE-полоса на всю ширину окна
        ax.axhspan(olo, ohi, color=color, alpha=0.13, zorder=1)
        ax.axhline(olo, color=color, lw=0.8, ls="--", alpha=0.6)
        ax.axhline(ohi, color=color, lw=0.8, ls="--", alpha=0.6)
        # нога импульса (from→to) — пунктир по диагонали
        ax.plot([mdates.date2num(pd.Timestamp(fr_ts).to_pydatetime()),
                 mdates.date2num(pd.Timestamp(to_ts).to_pydatetime())],
                [fr_p, to_p], color=color, lw=2.0, ls=":", zorder=4,
                marker="o", ms=5)
        ax.text(mdates.date2num(view.index[2].to_pydatetime()), ytext,
                f"{label}\nнога {pd.Timestamp(fr_ts).date()}→{pd.Timestamp(to_ts).date()} ({h['direction']})\nOTE {olo:.0f}-{ohi:.0f}",
                color=color, fontsize=10, fontweight="bold", va="center",
                bbox=dict(boxstyle="round", fc="white", ec=color, alpha=0.85), zorder=6)

    # вертикаль = момент сделки
    ax.axvline(mdates.date2num(asof.to_pydatetime()), color="black", lw=1.5, ls="-", alpha=0.7, zorder=5)
    ax.text(mdates.date2num(asof.to_pydatetime()), view["high"].max(),
            f"  МОМЕНТ СДЕЛКИ\n  {a.asof}", fontsize=10, fontweight="bold", va="top", zorder=6)

    draw_zone(h_hind, "#d32f2f", "ХИНДСАЙТ (как в бэктесте)", view["high"].max() * 0.97)
    draw_zone(h_pit, "#2e7d32", "PIT (честно, на момент сделки)", view["low"].min() * 1.06)

    ax.set_title(f"{a.sym} 4h — lookahead в выборе OTE-зоны: ХИНДСАЙТ видит будущее, PIT — нет\n"
                 f"(хиндсайт-нога заканчивается ПОСЛЕ момента сделки = заглядывание в будущее)",
                 fontsize=12)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.grid(alpha=0.15); ax.set_ylabel("Цена USDT")
    plt.tight_layout()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(a.out, dpi=110)
    print(f"[viz] saved → {a.out}")
    print(f"ХИНДСАЙТ нога: {h_hind['from'][0]} → {h_hind['to'][0]} ({h_hind['direction']}) OTE {h_hind['ote']}")
    if h_pit:
        print(f"PIT нога:      {h_pit['from'][0]} → {h_pit['to'][0]} ({h_pit['direction']}) OTE {h_pit['ote']}")


if __name__ == "__main__":
    main()
