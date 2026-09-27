"""Выход impulse_fib 1h: те же филлы из реплея (map_replays/trades.pkl), разные выходы.
Сетка: удержание 24/48/96/144/240 баров × цель (−1.618 как в бою / без цели) × стоп как в бою; плюс выход по структуре —
первый закрытый бар ниже минимума последних 3 баров (long) после +1R. Контроль той же геометрии для каждого удержания
(случайный вход ±30 дн той же монеты ×4). python impulse_fib_exit_lab.py"""
import sys, random
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf
from triangle_lab import walk
COST = 0.10
d = pd.read_pickle("G:/oko_lab/out/map_replays/trades.pkl"); z = d[d.mech == "impulse_fib_1h"].copy()
HOLDS = (24, 48, 96, 144, 240); rows = []; cache = {}
rs = random.Random(7)
for r in z.itertuples():
    if r.sym not in cache:
        cache[r.sym] = load_tf(r.sym, "1h")
    m = cache[r.sym]; hi, lo, cl = m.high.values, m.low.values, m.close.values
    j = int(m.index.searchsorted(r.entry_t)); long_ = r.side == "LONG"; e, sl = float(r.entry_px), float(r.sl_px)
    tgt = e * (1 + r.tgt_pct / 100) if long_ else e * (1 - r.tgt_pct / 100)
    out = {"sym": r.sym, "side": r.side, "год": r.год}
    for H in HOLDS:
        out[f"цель_{H}"] = walk(hi, lo, cl, j + 1, j + 1 + H, long_, e, sl, tgt)[0]
        out[f"безцели_{H}"] = walk(hi, lo, cl, j + 1, j + 1 + H, long_, e, sl, 1e18 if long_ else -1.0)[0]
        # контроль: случайный вход той же геометрии ±30 дн, то же удержание, та же цель
        a = []
        for _ in range(4):
            j0 = j + rs.randint(-720, 720)
            if 1 <= j0 < len(m) - 12:
                e0 = float(m.open.values[j0]); rsk = abs(e - sl) / e; tg = r.tgt_pct / 100
                a.append(walk(hi, lo, cl, j0, j0 + H, long_, e0, e0 * (1 - rsk) if long_ else e0 * (1 + rsk), e0 * (1 + tg) if long_ else e0 * (1 - tg))[0])
        out[f"ctl_{H}"] = np.mean(a) if a else np.nan
    # структурный выход: после +1R — первый close ниже min(low 3 баров) (long) / выше max(high 3) (short); стоп как в бою; лимит 240
    rsk_abs = abs(e - sl); armed = False; pnl = None
    for k in range(j + 1, min(j + 1 + 240, len(m))):
        if (lo[k] <= sl) if long_ else (hi[k] >= sl):
            pnl = ((sl - e) / e * 100) * (1 if long_ else -1) - COST; break
        if not armed and ((hi[k] - e >= rsk_abs) if long_ else (e - lo[k] >= rsk_abs)):
            armed = True
        if armed and k >= j + 4 and ((cl[k] < lo[k - 3:k].min()) if long_ else (cl[k] > hi[k - 3:k].max())):
            pnl = ((cl[k] - e) / e * 100) * (1 if long_ else -1) - COST; break
    if pnl is None:
        k = min(j + 240, len(m) - 1); pnl = ((cl[k] - e) / e * 100) * (1 if long_ else -1) - COST
    out["структура"] = pnl
    rows.append(out)
R = pd.DataFrame(rows); pd.set_option("display.width", 250)
print(f"филлов {len(R)}")
def tab(g):
    t = {}
    for H in HOLDS:
        t[f"цель {H}"] = g[f"цель_{H}"].mean(); t[f"без цели {H}"] = g[f"безцели_{H}"].mean(); t[f"ctl {H}"] = g[f"ctl_{H}"].mean()
    t["структура"] = g["структура"].mean(); return pd.Series(t)
print("=== среднее % по выходу (сторона)"); print(R.groupby("side").apply(tab).round(2).T.to_string())
print("\n=== медиана"); print(R.groupby("side").apply(lambda g: pd.Series({f"цель {H}": g[f"цель_{H}"].median() for H in HOLDS} | {f"без цели {H}": g[f"безцели_{H}"].median() for H in HOLDS} | {"структура": g["структура"].median()})).round(2).T.to_string())
print("\n=== WR %"); print(R.groupby("side").apply(lambda g: pd.Series({f"цель {H}": (g[f"цель_{H}"] > 0).mean() * 100 for H in HOLDS} | {"структура": (g["структура"] > 0).mean() * 100})).round(1).T.to_string())
print("\n=== по годам, цель 96 / без цели 240 / структура (LONG)")
L = R[R.side == "LONG"]; print(L.groupby("год").agg(n=("структура", "size"), цель96=("цель_96", "mean"), безцели240=("безцели_240", "mean"), ctl240=("ctl_240", "mean"), структура=("структура", "mean")).round(2).to_string())
for col in ("цель_96", "безцели_240", "структура"):
    s = L[col]; top = s.nlargest(int(len(s) * 0.1)).sum(); print(f"  хрупкость LONG {col}: сумма {s.sum():.0f} · без топ-10% {s.sum() - top:.0f}")
R.to_pickle("G:/oko_lab/out/map_replays/impulse_fib_exit_lab.pkl")
