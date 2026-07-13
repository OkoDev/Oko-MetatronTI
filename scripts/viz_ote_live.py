"""Визуализация ЖИВОГО OTE-сетапа (что бот видит СЕЙЧАС) через ЭТАЛОН draw_chart (не менять).
Находит символ с ценой в OTE-зоне прямо сейчас, рисует 4h+LTF с зоной/entry/SL/TP(fib-1.0)/CHoCH.
Запуск: py312 scripts/viz_ote_live.py [SYMBOL] [HTF] [LTF]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, sqlite3
import ccxt
from core.smc.smc_engine import ote_retest_setups, build_ote
from scripts.draw_ote_rpl import draw_chart   # ЭТАЛОН — не менять

ex = ccxt.bingx({"options": {"defaultType": "swap"}})
OUTDIR = "e:/tmp"


def fetch(sym, tf, limit=200):
    o = ex.fetch_ohlcv(sym, tf, limit=limit)
    df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("ts").astype(float)


def candidates():
    # символы из недавних ote_nested сделок (то, что бот реально смотрит)
    try:
        c = sqlite3.connect("subscriptions.db")
        rows = [r[0] for r in c.execute(
            """SELECT DISTINCT symbol FROM simulated_trades WHERE source_router='ote_nested'
               AND created_at>=datetime('now','-2 days') ORDER BY created_at DESC LIMIT 40""")]
        c.close()
        return rows
    except Exception:
        return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]


def find_live(htf, ltf):
    for sym in candidates():
        try:
            d4 = fetch(sym, htf)
            setups = ote_retest_setups(d4, only_choch=False, provisional=True)
            if not setups:
                continue
            h = setups[-1]
            olo, ohi = h["ote"]
            price = float(d4["close"].values[-1])
            if olo <= price <= ohi:        # цена В зоне СЕЙЧАС = живой сетап
                return sym, d4, h, price
        except Exception:
            continue
    return None, None, None, None


def main():
    if len(sys.argv) > 1:
        sym = sys.argv[1]; htf = sys.argv[2] if len(sys.argv) > 2 else "4h"; ltf = sys.argv[3] if len(sys.argv) > 3 else "1h"
        d4 = fetch(sym, htf); setups = ote_retest_setups(d4, only_choch=False, provisional=True)
        h = setups[-1] if setups else None; price = float(d4["close"].values[-1])
    else:
        htf, ltf = "4h", "1h"
        sym, d4, h, price = find_live(htf, ltf)
        if sym is None:
            print("Живого сетапа (цена в зоне) не нашёл среди кандидатов."); return
    if h is None:
        print(f"{sym}: сетап не построен"); return

    direction = h["direction"]
    olo, ohi = h["ote"]
    sl = h["sl"]
    entry = h["entry"]
    # TP = fib -1.0 того же импульса (build_ote(конец, начало) как в find_setups_zz)
    o = build_ote(h["to"][1], h["from"][1])
    tp_fib = o["levels"].get(-1.0)
    # direction-correct: long TP выше entry, short ниже (иначе fallback 1R)
    if not (tp_fib and ((direction == "long" and tp_fib > entry) or (direction == "short" and tp_fib < entry))):
        risk = abs(entry - sl); tp_fib = entry + risk if direction == "long" else entry - risk

    print(f"ЖИВОЙ: {sym} {htf} dir={direction} price={price:.6g}")
    print(f"  зона OTE={olo:.6g}..{ohi:.6g}  entry={entry:.6g}  SL(fib1.0)={sl:.6g}  TP(fib-1.0)={tp_fib:.6g}")
    print(f"  R:R = {abs(tp_fib-entry)/abs(entry-sl):.2f}  choch={h.get('choch_ts')}")

    os.makedirs(OUTDIR, exist_ok=True)
    base = sym.split('/')[0]
    # HTF график (зона)
    out_h = f"{OUTDIR}/ote_live_{base}_{htf}.png"
    draw_chart(
        d4.tail(90), f"{sym} {htf} — ЖИВОЙ OTE {direction.upper()} | зона+TP fib-1.0", out_h,
        swing_lo=h["from"][1] if direction == "long" else h["to"][1],
        swing_hi=h["to"][1] if direction == "long" else h["from"][1],
        direction=direction, entry=entry, sl=sl, tp=tp_fib,
        zone_lo=olo, zone_hi=ohi, choch_time=h.get("choch_ts"),
    )

    # LTF график (ПОЧЕМУ вход: LTF-слом/CHoCH в сторону сделки внутри HTF-зоны)
    d_l = fetch(sym, ltf, 300)
    setups_l = ote_retest_setups(d_l, only_choch=False, provisional=True)
    # LTF-сетап той же стороны, чей вход попадает в HTF-зону
    cand = [s for s in setups_l if s["direction"] == direction and olo <= s["entry"] <= ohi]
    s_l = cand[-1] if cand else (setups_l[-1] if setups_l else None)
    out_l = f"{OUTDIR}/ote_live_{base}_{ltf}.png"
    if s_l is not None:
        llo, lhi = s_l["ote"]
        print(f"  LTF {ltf}: слом(CHoCH)={s_l.get('choch_ts')} entry={s_l['entry']:.6g} "
              f"sl={s_l['sl']:.6g} зона={llo:.6g}..{lhi:.6g} — ПРИЧИНА входа")
        draw_chart(
            d_l.tail(140), f"{sym} {ltf} — ПОЧЕМУ ВХОД: LTF-слом {direction.upper()} в HTF-зоне", out_l,
            swing_lo=s_l["from"][1] if direction == "long" else s_l["to"][1],
            swing_hi=s_l["to"][1] if direction == "long" else s_l["from"][1],
            direction=direction, entry=s_l["entry"], sl=s_l["sl"], tp=tp_fib,
            zone_lo=llo, zone_hi=lhi, choch_time=s_l.get("choch_ts"),
            htf_zone=(olo, ohi),
        )
    else:
        print(f"  LTF {ltf}: сетап не построен")


if __name__ == "__main__":
    main()
