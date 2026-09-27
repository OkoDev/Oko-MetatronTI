"""МОЖЕТ ЛИ ЯДРО ВОЛН ПОМОЧЬ РАДАРУ (Егор 26.09: «как ядро может ему помочь?»).

Радар торгует РАЗВОРОТ после выдоха, опираясь на СВОЙ счёт ног (ZigZag 15m/24ч, Binance).
Ядро OKO-SM 4h (mark_impulse) знает другое: завершена ли ПЯТЁРКА старшего масштаба — а по замеру
21.09 разворот после пятой поднимает каждую механику, продолжение после пятой минусит у всех.

Считаем состояние ядра 4h на момент КАЖДОЙ заявки радара (каузально: только бары ДО заявки),
и сверяем со стороной входа:
  согласие   — ядро показало завершённую пятёрку ВВЕРХ, радар шортит (или зеркально);
  против     — пятёрка в ту же сторону, что и вход радара (входим в продолжение импульса);
  нет пятёрки — ядро молчит.
Исход берём РЕАЛЬНЫЙ (переигрыш заявок на публичных klines, vst_real_resolve.pkl), а не из VST.

python radar_wave_core_ctx.py
"""
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
import logging; logging.disable(logging.CRITICAL)
from core.waves import mark_impulse, WaveParams          # noqa: E402
from core.waves.bingx_klines import fetch_closed          # noqa: E402

P = WaveParams()
OUT = Path("G:/oko_lab/out/radar_wave_core_ctx.pkl")

R = pd.read_pickle("G:/oko_lab/out/vst_real_resolve.pkl")
r = R[R.src == "radar_pump"].copy()
print(f"заявок радара: {len(r)} · монет: {r.sym.nunique()}")

rows, cache = [], {}
for i, t in enumerate(r.itertuples(), 1):
    sym = t.sym
    if sym not in cache:
        try:
            cache[sym] = fetch_closed(sym, "4h", 1000, now=pd.Timestamp.utcnow())
        except Exception:                                  # noqa: BLE001
            cache[sym] = None
    dh = cache[sym]
    st = []
    if dh is not None and len(dh) > 0:
        cut = dh[dh.index < pd.Timestamp(t.created).tz_localize("UTC")]   # только ДО заявки
        if len(cut) >= 6 * P.sw + 50:
            try:
                # lookback 12 баров 4h = двое суток: пятёрка, завершённая недавно
                st = mark_impulse(cut, pd.Timestamp(t.created).tz_localize("UTC"), P, "4h", lookback=12)
            except Exception:                              # noqa: BLE001
                st = []
    s = st[0] if st else None
    rows.append({
        "id": t.id, "sym": sym, "dir": t.dir, "real": t.real, "real_pnl": t.real_pnl,
        "vst": t.vst, "vst_pnl": t.vst_pnl, "created": t.created,
        "ядро_есть": bool(s),
        "ядро_side": (s or {}).get("side"),
        "ядро_полное": bool((s or {}).get("core_full")),
        "ядро_imp%": (s or {}).get("imp_pct"),
        "часов_от_пятой": (None if not s else round(
            (pd.Timestamp(t.created).tz_localize("UTC")
             - (lambda x: x if x.tzinfo else x.tz_localize("UTC"))(pd.Timestamp(s["top_time"]))
             ).total_seconds() / 3600, 1)),
    })
    if i % 20 == 0:
        print(f"  {i}/{len(r)}", flush=True)

d = pd.DataFrame(rows)
d.to_pickle(OUT)

# согласие: ядро дало импульс ВВЕРХ (LONG), радар входит SHORT — то есть разворот после пятой
def rel(z):
    if not z["ядро_есть"]:
        return "ядро молчит"
    core_up = str(z["ядро_side"]).upper() == "LONG"
    short = str(z["dir"]).upper() == "SHORT"
    return "СОГЛАСИЕ (разворот после пятой)" if core_up == short else "против (вход в продолжение)"

d["связь"] = d.apply(rel, axis=1)
real = d[d.real.isin(["SL", "TP", "время"])]
pd.set_option("display.width", 250)
print(f"\nсопоставлено: {len(d)} · ядро дало пятёрку в {int(d['ядро_есть'].sum())} случаях")
print("\n=== РЕАЛЬНЫЙ исход × связь со ядром 4h")
g = real.groupby("связь").agg(n=("id", "size"), ср=("real_pnl", "mean"), сумма=("real_pnl", "sum"),
                              медиана=("real_pnl", "median"),
                              WR=("real_pnl", lambda x: round(100 * (x > 0).mean())))
print(g.round(2).to_string())
print("\n=== то же, но ТОЛЬКО полное ядро (core_full)")
gf = real[real["ядро_полное"]].groupby("связь").agg(n=("id", "size"), ср=("real_pnl", "mean"),
                                                    сумма=("real_pnl", "sum"))
print(gf.round(2).to_string() if len(gf) else "  полных ядер в выборке нет")
print("\n=== свежесть пятой (часов от вершины) × исход")
if real["часов_от_пятой"].notna().any():
    b = pd.cut(real["часов_от_пятой"], [0, 24, 72, 168, 10_000], labels=["<1д", "1-3д", "3-7д", ">7д"])
    print(real.groupby(b, observed=True).agg(n=("id", "size"), ср=("real_pnl", "mean"),
                                             сумма=("real_pnl", "sum")).round(2).to_string())
print(f"\nсохранено: {OUT}")
