"""OTE-ЗОНА КАК КОНТЕКСТ, А НЕ ВХОД: те же 1987 филлов impulse_fib 1h (map_replays/trades.pkl) → лежал ли вход внутри
OTE-зоны 4h того же направления (ote_retest_setups на 200 барах 4h, provisional, зигзаг как в шкафу — тот же калькулятор,
что у ote_nested), и что это даёт против сделок вне зоны. Каузально: зоны по 4h-барам, закрытым до бара сигнала.
python ote_context_impulse.py"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot"); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf
from core.smc.smc_engine import ote_retest_setups
from core.smc.ote_signal_generator import OTESignalGenerator
import logging; logging.disable(logging.CRITICAL)
pd.set_option("display.width", 250)
gen = OTESignalGenerator(); zz_depth, zz_dev = gen._zz("4h")
d = pd.read_pickle("G:/oko_lab/out/map_replays/trades.pkl"); z = d[d.mech == "impulse_fib_1h"].copy()
rows = []; cache = {}
for r in z.itertuples():
    if r.sym not in cache:
        cache[r.sym] = load_tf(r.sym, "4h")
    m4 = cache[r.sym]; k4 = int(np.searchsorted(m4.index.values, np.datetime64(r.signal_t), "right")) - 1   # бары 4h, ЗАКРЫТЫЕ до сигнала
    if k4 < 60:
        rows.append({"idx": r.Index, "zone": "нет данных"}); continue
    try:
        st = ote_retest_setups(m4.iloc[max(0, k4 - 200):k4], depth=zz_depth, dev_mult=zz_dev, only_choch=False, provisional=True)
    except Exception:
        rows.append({"idx": r.Index, "zone": "ошибка"}); continue
    e = float(r.entry_px); side = "long" if r.side == "LONG" else "short"
    same = [x for x in st if x["direction"] == side and x["ote"][0] <= e <= x["ote"][1]]
    opp = [x for x in st if x["direction"] != side and x["ote"][0] <= e <= x["ote"][1]]
    rows.append({"idx": r.Index, "zone": "в OTE 4h (своё напр.)" if same else ("в OTE 4h (против)" if opp else "вне зоны"), "n_zones": len(st)})
Z = pd.DataFrame(rows).set_index("idx"); z = z.join(Z)
def agg(g):
    return g.agg(n=("pnl", "size"), монет=("sym", "nunique"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"), мед=("pnl", "median"),
                 ctl_r=("ctl_rand", "mean"), ctl_t=("ctl_time", "mean")).assign(Δr=lambda x: (x["ср"] - x.ctl_r).round(2), Δt=lambda x: (x["ср"] - x.ctl_t).round(2)).round(2)
print("=== impulse_fib 1h: вход в OTE-зоне 4h vs вне"); print(agg(z.groupby(["side", "zone"])).to_string())
print("\n=== × год (ср)"); print(z.groupby(["side", "zone", "год"]).pnl.mean().round(2).unstack("год").to_string())
print("\n=== × USDT.D"); print(agg(z.groupby(["side", "zone", "USDT.D"])).to_string())
for (s_, zn), g in z.groupby(["side", "zone"]):
    top = g.pnl.nlargest(max(1, int(len(g) * 0.1))).sum(); print(f"  хрупкость {s_} {zn}: n {len(g)} · сумма {g.pnl.sum():.0f} · без топ-10% {g.pnl.sum() - top:.0f} · монет+ {(g.groupby('sym').pnl.sum() > 0).mean() * 100:.0f}%")
z.to_pickle("G:/oko_lab/out/map_replays/impulse_fib_ote_context.pkl")
