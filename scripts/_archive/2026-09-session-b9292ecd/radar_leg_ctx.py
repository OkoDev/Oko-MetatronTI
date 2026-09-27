"""ЧЕМ ЯДРО МОЖЕТ ПОМОЧЬ РАДАРУ — слой 2: НОГА структуры OKO-SM 4h (покрытие ~100%, в отличие от
пятёрки, которая встретилась радару 2 раза из 74).

Для каждой заявки радара считаем на 4h (каузально, только бары ДО заявки):
  trend      — направление старшего масштаба (swing 50);
  глубина    — где цена внутри текущей ноги (0 = у начала ноги, 1 = у экстремума);
  позиция    — вход ПРОТИВ ноги у её экстремума (то, что платило в ote_context_counter_leg_extreme)
               или ПО ноге.
Исход — РЕАЛЬНЫЙ (переигрыш на публичных klines). python radar_leg_ctx.py
"""
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
import logging; logging.disable(logging.CRITICAL)
from core.smc.oko_sm_engine import run_structure, current_leg     # noqa: E402
from core.waves.bingx_klines import fetch_closed                   # noqa: E402

R = pd.read_pickle("G:/oko_lab/out/vst_real_resolve.pkl")
r = R[R.src == "radar_pump"].copy()
print(f"заявок радара: {len(r)} · монет: {r.sym.nunique()}")

rows, cache = [], {}
for i, t in enumerate(r.itertuples(), 1):
    if t.sym not in cache:
        try:
            cache[t.sym] = fetch_closed(t.sym, "4h", 1000, now=pd.Timestamp.utcnow())
        except Exception:                                          # noqa: BLE001
            cache[t.sym] = None
    dh = cache[t.sym]
    trend = depth = None
    if dh is not None and len(dh) > 120:
        cut = dh[dh.index < pd.Timestamp(t.created).tz_localize("UTC")]
        if len(cut) > 120:
            try:
                st = run_structure(cut[["open", "high", "low", "close"]], swing_len=50, internal_len=5)
                trend = st.trend
                leg = current_leg(st)
                px = float(cut.close.iloc[-1])
                if leg and leg.get("origin") is not None and leg.get("extreme") is not None:
                    o, e = float(leg["origin"]), float(leg["extreme"])
                    if o != e:
                        depth = (px - o) / (e - o)          # 1 = у экстремума ноги, 0 = у её начала
            except Exception:                                      # noqa: BLE001
                pass
    rows.append({"id": t.id, "sym": t.sym, "dir": t.dir, "real": t.real, "real_pnl": t.real_pnl,
                 "trend4h": trend, "глубина": depth})
    if i % 20 == 0:
        print(f"  {i}/{len(r)}", flush=True)

d = pd.DataFrame(rows)
d.to_pickle("G:/oko_lab/out/radar_leg_ctx.pkl")
real = d[d.real.isin(["SL", "TP", "время"])].copy()
pd.set_option("display.width", 250)
print(f"\nтренд 4h посчитан у {int(d.trend4h.notna().sum())} из {len(d)} · глубина у {int(d['глубина'].notna().sum())}")

real["против тренда"] = [("по тренду 4h" if (tr == 1) == (dr == "LONG") else "ПРОТИВ тренда 4h")
                         if tr in (1, -1) else "тренд не определён"
                         for tr, dr in zip(real.trend4h, real["dir"])]
print("\n=== РЕАЛЬНЫЙ исход × тренд 4h (старший масштаб OKO-SM)")
print(real.groupby("против тренда").agg(n=("id", "size"), ср=("real_pnl", "mean"), сумма=("real_pnl", "sum"),
      медиана=("real_pnl", "median"), WR=("real_pnl", lambda x: round(100 * (x > 0).mean()))).round(2).to_string())

g = real[real["глубина"].notna()].copy()
if len(g):
    g["зона ноги"] = pd.cut(g["глубина"], [-9, 0.5, 0.79, 1.0, 9],
                            labels=["< 0.5", "0.5-0.79 (OTE)", "0.79-1.0 (у экстремума)", "за экстремумом"])
    print("\n=== РЕАЛЬНЫЙ исход × ГДЕ цена внутри ноги 4h")
    print(g.groupby("зона ноги", observed=True).agg(n=("id", "size"), ср=("real_pnl", "mean"),
          сумма=("real_pnl", "sum"), WR=("real_pnl", lambda x: round(100 * (x > 0).mean()))).round(2).to_string())
