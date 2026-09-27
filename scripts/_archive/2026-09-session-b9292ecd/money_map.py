# -*- coding: utf-8 -*-
"""🗺️ ГДЕ ЖИВУТ ДЕНЬГИ: кроссы × окраска баров (наклон медианы) × зона × медиана (Егор, 11.09).

Окраска баров у Егора = barcolor(maRising ? зелёный : красный), где ma = EMA(wt1, 200), реакция 1.
То есть ЦВЕТ БАРА = НАКЛОН МЕДИАНЫ = режим. Раньше как фильтр не проверялся ни разу.

Отрезок = от кросса до ВСТРЕЧНОГО кросса (выход Егора), обе стороны:
  LONG  : кросс ▲ → следующий кросс ▼
  SHORT : кросс ▼ → следующий кросс ▲
Вход по open следующего бара после кросса, выход по open следующего бара после встречного.
Разрезы на входе: цвет бара · зона wt1 (<−60 / −60…0 / 0…+60 / >+60) · wt1 над/под медианой.

Часть A — GRT на барах с графика TV (15m, 1h, 4h), чтобы сверить с картинкой.
Часть B — вся вселенная: 15m-кэш 2022-2026, ТФ 15m / 1h / 4h, 291 монета.
Косты 0.35% на круг; печатаю и ГРЯЗНЫМИ — где ход есть, а где его съедают косты.
"""
import sys, json, os, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

COST, MA_LEN, WARM = 0.35, 200, 400
R = (r"C:\Users\yogoru\.claude\projects\e--MTF-BOT-CURSOR-crypto-volume-bot"
     r"\b9292ecd-40bf-480f-b583-11c47310bf19\tool-results")
TVF = {"15m": "mcp-tradingview-data_get_ohlcv-1789098715467.txt",
       "1h": "mcp-tradingview-data_get_ohlcv-1789098355195.txt",
       "4h": "mcp-tradingview-data_get_ohlcv-1789098559882.txt"}


def segments(d, warm):
    """d: open/high/low/close. Вернуть DataFrame отрезков кросс→встречный кросс."""
    w = calculate_wt(d[["open", "high", "low", "close"]].reset_index(drop=True))
    w1, w2 = w.wt1.values, w.wt2.values
    ma = pd.Series(w1).ewm(span=MA_LEN, adjust=False).mean().values
    rising = np.concatenate(([False], ma[1:] > ma[:-1]))
    x = w1 - w2
    cu = np.concatenate(([False], (x[:-1] <= 0) & (x[1:] > 0)))
    cd = np.concatenate(([False], (x[:-1] >= 0) & (x[1:] < 0)))
    op = d.open.values
    idx = np.where(cu | cd)[0]
    out = []
    for a, b in zip(idx[:-1], idx[1:]):
        if a < warm or b + 1 >= len(op):
            continue
        side = 1 if cu[a] else -1
        e, xpx = op[a + 1], op[b + 1]
        g = (xpx - e) / e * 100 * side
        z = w1[a]
        zone = "<−60" if z < -60 else ("−60…0" if z < 0 else ("0…+60" if z <= 60 else ">+60"))
        out.append(dict(side=side, gross=g, net=g - COST, bars=b - a,
                        green=bool(rising[a]), zone=zone, above=bool(w1[a] > ma[a])))
    return pd.DataFrame(out)


def table(S, title):
    if not len(S):
        print(f"  {title}: нет отрезков"); return
    print(f"\n  ── {title} · отрезков {len(S):,} ──")
    print(f"  {'сторона':>7} {'бар':>8} {'зона':>7} {'медиана':>8} {'n':>7} {'грязн':>8} "
          f"{'нетто':>8} {'WR':>6} {'сумма нетто':>12} {'бар мед':>8}")
    for side, sn in [(1, "LONG"), (-1, "SHORT")]:
        for green, cn in [(True, "зелёный"), (False, "красный")]:
            for zone in ["<−60", "−60…0", "0…+60", ">+60"]:
                for above, an in [(True, "над"), (False, "под")]:
                    g = S[(S.side == side) & (S.green == green) & (S.zone == zone) & (S.above == above)]
                    if len(g) < 15:
                        continue
                    print(f"  {sn:>7} {cn:>8} {zone:>7} {an:>8} {len(g):>7,} {g.gross.mean():+7.3f}% "
                          f"{g.net.mean():+7.3f}% {(g.net>0).mean()*100:5.1f}% {g.net.sum():+11.1f}% "
                          f"{g.bars.median():>8.0f}")
    print("\n  сводка по ЦВЕТУ бара на входе:")
    for side, sn in [(1, "LONG"), (-1, "SHORT")]:
        for green, cn in [(True, "зелёный"), (False, "красный")]:
            g = S[(S.side == side) & (S.green == green)]
            if len(g):
                print(f"    {sn:>5} {cn:>8}: n={len(g):>7,} · грязн {g.gross.mean():+.3f}% · "
                      f"нетто {g.net.mean():+.3f}% · WR {(g.net>0).mean()*100:.1f}%")


print("=" * 100 + "\nЧАСТЬ A — GRT, бары с графика TradingView (разгон EMA200 ≈ 200 баров отброшен)\n" + "=" * 100)
for tf, f in TVF.items():
    j = json.load(open(os.path.join(R, f), encoding="utf-8"))
    d = pd.DataFrame(j["bars"]).sort_values("time").reset_index(drop=True)
    table(segments(d, warm=200), f"GRT {tf} (TV)")

if len(sys.argv) > 1 and sys.argv[1] == "all":
    print("\n" + "=" * 100 + "\nЧАСТЬ B — ВСЯ ВСЕЛЕННАЯ, 15m-кэш 2022-2026\n" + "=" * 100, flush=True)
    con = sqlite3.connect("ohlcv_cache.db")
    syms = [r[0] for r in con.execute(
        "select symbol from ohlcv_cache where timeframe='15m' "
        "group by symbol having count(*) > 50000 order by count(*) desc")][:300]
    allseg = {"15m": [], "1h": [], "4h": []}
    for fi, sym in enumerate(syms, 1):
        d = pd.read_sql("select time,open,high,low,close from ohlcv_cache where symbol=? "
                        "and timeframe='15m' order by time", con, params=(sym,))
        d["ts"] = pd.to_datetime(d.time, unit="ms")
        d = d.drop_duplicates("ts").set_index("ts")[["open", "high", "low", "close"]]
        for tf, rule in [("15m", None), ("1h", "60min"), ("4h", "240min")]:
            dd = d if rule is None else d.resample(rule, label="left", closed="left").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
            if len(dd) < WARM + 100:
                continue
            s = segments(dd.reset_index(drop=True), warm=WARM)
            s["sym"] = sym
            allseg[tf].append(s)
        if fi % 50 == 0:
            print(f"  [{fi}/{len(syms)}]", flush=True)
    for tf, parts in allseg.items():
        S = pd.concat(parts, ignore_index=True)
        S.to_pickle(os.path.join(os.path.dirname(__file__), f"money_map_{tf}.pkl"))
        table(S, f"ВСЕЛЕННАЯ {tf}")
