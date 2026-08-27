# -*- coding: utf-8 -*-
"""РАЗБОР СДЕЛКИ impulse_fib НА ГРАФИКЕ: как детектор нашёл импульс и построил вход.

Рисует свечи 1h + разметку механики:
  · нога импульса origin → extreme (что детектор счёл импульсом и почему),
  · зона входа = откат 0.382 от экстремума, факт исполнения лимитки,
  · стоп 2.5·ATR, цель −1.618 фибо, текущая цена,
  · подписи гейтов (объём / тренд / волатильность) и причин отбора.

Запуск: python scripts/chart_impulse_trade.py <trade_id> [bars]
"""
import json
import sqlite3
import sys
import urllib.request

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt        # noqa: E402
import mplfinance as mpf               # noqa: E402
import pandas as pd                    # noqa: E402

from core.smc.impulse_fib import (ENTRY_FIB, MIN_ATR, MAX_RETR, STOP_ATR_K,  # noqa: E402
                                  TARGET_FIB, WAIT_BARS, _atr, find_impulses)

DB = "subscriptions.db"
TRADE_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 58367
BARS = int(sys.argv[2]) if len(sys.argv) > 2 else 160
OUT = f"scratch_trade_{TRADE_ID}.png"


def klines(sym: str, limit: int = 1000) -> pd.DataFrame:
    base = sym.split("/")[0]
    url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={base}USDT"
           f"&interval=1h&limit={limit}")
    arr = json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "oko"}), timeout=20))
    d = pd.DataFrame(arr, columns=["t", "Open", "High", "Low", "Close", "Volume",
                                   "ct", "qv", "n", "tb", "tq", "ig"])
    for c in ("Open", "High", "Low", "Close", "Volume"):
        d[c] = d[c].astype(float)
    d.index = pd.to_datetime(d.t, unit="ms", utc=True)
    return d[["Open", "High", "Low", "Close", "Volume"]]


con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
tr = dict(con.execute("SELECT * FROM simulated_trades WHERE id=?", (TRADE_ID,)).fetchone())
con.close()
feat = json.loads(tr.get("features_json") or "{}")
sym = tr["symbol"]
entry_declared = float(tr["entry_price"])
entry_actual = float(tr["actual_entry_price"] or 0) or None
sl_now, sl_orig = float(tr["stop_loss"]), float(tr["original_sl"] or tr["stop_loss"])
tp = float(tr["take_profit"])
origin_ts = feat.get("if_impulse_ts")

df = klines(sym)
dd = df.reset_index(drop=True)
H, L, C = dd.High.values, dd.Low.values, dd.Close.values
atr = _atr(dd.rename(columns=str.lower)).values

# ── находим ТОТ импульс, который дал сделку ───────────────────────────────────
imps = find_impulses(H, L, C, atr, len(dd))
target_b = None
if origin_ts:
    want = pd.Timestamp(origin_ts, tz="UTC")
    for a, b, up in imps:
        if df.index[b] == want:
            target_b = (a, b, up)
            break
if target_b is None and imps:
    target_b = imps[-1]
a, b, up = target_b
o_, x_ = float(C[a]), float(C[b])
amp = abs(x_ - o_)
sign = -1.0 if up else 1.0

# ── чистота импульса: максимальный контр-откат внутри хода ────────────────────
import numpy as np                                            # noqa: E402
sh, sl_arr = H[a:b + 1], L[a:b + 1]
dd_max = (float(np.max(np.maximum.accumulate(sh) - sl_arr)) if up
          else float(np.max(sh - np.minimum.accumulate(sl_arr))))

print("═" * 94)
print(f"РАЗБОР СДЕЛКИ #{TRADE_ID} · {sym} · {tr['direction']} · статус {tr['status']}")
print("═" * 94)
print("1. ЧТО ДЕТЕКТОР СЧЁЛ ИМПУЛЬСОМ")
print(f"   начало (origin)   бар {a}  {df.index[a]:%Y-%m-%d %H:%M}  цена {o_:.6g}")
print(f"   конец  (extreme)  бар {b}  {df.index[b]:%Y-%m-%d %H:%M}  цена {x_:.6g}")
print(f"   длина {b - a} баров (лимит 60) · ход {amp / x_ * 100:.2f}% = "
      f"{amp / atr[b]:.2f}·ATR (нужно ≥{MIN_ATR})")
print(f"   макс. контр-откат ВНУТРИ хода {dd_max / amp * 100:.1f}% (лимит {MAX_RETR * 100:.0f}%)"
      f" → {'чистый ход' if dd_max / amp <= MAX_RETR else 'НЕ проходит'}")
print()
print("2. КАК ПОСТРОЕН ВХОД")
print(f"   вход = экстремум {'−' if up else '+'} 0.382·ход = {entry_declared:.6g} "
      f"({(entry_declared - x_) / x_ * 100:+.2f}% от экстремума)")
if entry_actual:
    print(f"   ФАКТ исполнения {entry_actual:.6g} · расхождение "
          f"{(entry_actual - entry_declared) / entry_declared * 100:+.3f}%")
print(f"   стоп = {STOP_ATR_K}·ATR({atr[b]:.6g}) = {sl_orig:.6g} "
      f"({abs(entry_declared - sl_orig) / entry_declared * 100:.2f}% от входа)")
print(f"   цель = экстремум {'+' if up else '−'} 1.618·ход = {tp:.6g} "
      f"(+{abs(tp - entry_declared) / entry_declared * 100:.1f}% от входа) · "
      f"RR {abs(tp - entry_declared) / abs(entry_declared - sl_orig):.2f}")
print()
print("3. ГЕЙТЫ (все три обязательны)")
print(f"   объём импульса к средней : {feat.get('if_vratio')}  (коридор 1.0-1.5)")
print(f"   по тренду EMA200         : {'да' if feat.get('if_with_trend') else 'НЕТ'}")
print(f"   волатильность ATR/SMA100 : {feat.get('if_regime')}  (нужно ≥1.1)")
if sl_now != sl_orig:
    print()
    print(f"4. 🔴 СТОП СДВИНУТ ТРЕЙЛИНГОМ: {sl_orig:.6g} → {sl_now:.6g} "
          f"({(sl_now - entry_declared) / entry_declared * 100:+.2f}% от входа) — "
          f"выход перестал быть фиксированным")

# ── график ────────────────────────────────────────────────────────────────────
view = df.iloc[max(0, b - BARS + 40):]
mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350",
                           wick={"up": "#26a69a", "down": "#ef5350"},
                           volume={"up": "#26a69a44", "down": "#ef535044"}, edge="inherit")
style = mpf.make_mpf_style(marketcolors=mc, facecolor="#131722", figcolor="#131722",
                           gridcolor="#1e2130", gridstyle="--", y_on_right=True,
                           rc={"axes.labelcolor": "#d1d4dc", "xtick.color": "#787b86",
                               "ytick.color": "#787b86", "text.color": "#d1d4dc",
                               "xtick.labelsize": 7})

lines = [[(df.index[a], o_), (df.index[b], x_)]]          # нога импульса
colors = ["#ffb300"]
hlines = dict(hlines=[entry_declared, sl_orig, tp],
              colors=["#42a5f5", "#ef5350", "#26a69a"],
              linestyle=["--", "-", "-"], linewidths=[1.2, 1.0, 1.0])
if sl_now != sl_orig:
    hlines["hlines"].append(sl_now); hlines["colors"].append("#ff7043")
    hlines["linestyle"].append(":"); hlines["linewidths"].append(1.2)

exit_px = float(tr["exit_price"]) if tr.get("exit_price") else None
if exit_px:
    hlines["hlines"].append(exit_px); hlines["colors"].append("#ab47bc")
    hlines["linestyle"].append("-."); hlines["linewidths"].append(1.4)

fig, axes = mpf.plot(view, type="candle", style=style, volume=True, returnfig=True,
                     figsize=(16, 9), datetime_format="%d.%m %H:%M", xrotation=0,
                     alines=dict(alines=lines, colors=colors, linewidths=[2.4]),
                     hlines=hlines, tight_layout=True,
                     # цель уходит далеко вверх — раздвигаем ось, иначе масштаб «взяли
                     # 5.5% из заявленных 27.6%» не виден
                     ylim=(min(view.Low.min(), sl_orig) * 0.985,
                           max(view.High.max(), tp) * 1.01),
                     title=f"\n\n{sym} 1h · сделка #{TRADE_ID} · импульс {amp / x_ * 100:.1f}% "
                           f"({amp / atr[b]:.1f} ATR, откат внутри {dd_max / amp * 100:.0f}%)")
ax = axes[0]
rows_txt = [(f"импульс {df.index[a]:%d.%m %H:%M} → {df.index[b]:%d.%m %H:%M}  "
             f"{o_:.6g} → {x_:.6g}", "#ffb300"),
            (f"вход 0.382 = {entry_declared:.6g}"
             + (f"  (факт {entry_actual:.6g})" if entry_actual else ""), "#42a5f5"),
            (f"стоп 2.5·ATR = {sl_orig:.6g}", "#ef5350"),
            (f"цель −1.618 = {tp:.6g}  (+{abs(tp - entry_declared) / entry_declared * 100:.1f}%)",
             "#26a69a")]
if sl_now != sl_orig:
    rows_txt.append((f"стоп после трейлинга = {sl_now:.6g}", "#ff7043"))
if exit_px and entry_actual:
    rows_txt.append((f"ВЫХОД {exit_px:.6g}  ({(exit_px - entry_actual) / entry_actual * 100:+.2f}%) "
                     f"— закрыл трейлинг, не цель", "#ab47bc"))
for i, (txt, col) in enumerate(rows_txt):
    ax.text(0.012, 0.975 - i * 0.035, txt, transform=ax.transAxes,
            color=col, fontsize=9, va="top", family="DejaVu Sans")
fig.savefig(OUT, dpi=110, facecolor="#131722", bbox_inches="tight")
print(f"\nграфик: {OUT}")
