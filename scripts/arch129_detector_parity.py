#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ARCH-129 detector parity: shadow-сравнение двух наборов SMC-детекторов.

Набор A (smc_engine.py, tuple) — чарт/бэктест/OTE/wave.
Набор B (core.smc.fvg/order_blocks/structure, dataclass) — snapshot→Сфера4→TPSelector магниты.

Замеряет РЕАЛЬНЫЙ дрейф между ними на живых данных (FVG/OB/structure), чтобы
выбрать канон по фактам (как ARCH-117 ph3), а не по предположению «формула идентична».

Использование: python scripts/arch129_detector_parity.py
"""
import sys
sys.path.insert(0, r"e:/MTF BOT/CURSOR/crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv()
import ccxt, pandas as pd

# набор A
from core.smc.smc_engine import (detect_fvg as fvg_A, detect_order_blocks as ob_A,
                                 detect_structure_breaks as struct_A)
# набор B
from core.smc.fvg import detect_fvg as fvg_B
from core.smc.order_blocks import detect_order_blocks as ob_B
from core.smc.structure import detect_structure as struct_B

PAIRS = ["BTC", "ETH", "SOL", "XLM", "ONDO", "SUI", "LINK", "AVAX", "DOGE", "ADA",
         "OP", "ARB", "INJ", "TIA", "SEI"]
TFS = ["15m", "1h"]
ex = ccxt.bingx()


def _match(zones_a, zones_b, price, tol=0.002):
    """Сколько зон A нашли пару в B (midpoint в пределах tol%)."""
    m = 0
    for ma in zones_a:
        for mb in zones_b:
            if abs(ma - mb) / price <= tol:
                m += 1; break
    return m


def main():
    tot = {"fvg_a": 0, "fvg_b": 0, "fvg_match": 0,
           "ob_a": 0, "ob_b": 0, "ob_match": 0,
           "struct_same": 0, "struct_diff": 0, "n": 0}
    for sym in PAIRS:
        for tf in TFS:
            try:
                o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", tf, limit=300)
                df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
                df.index = pd.to_datetime(df["ts"], unit="ms")
                price = float(df["close"].iloc[-1])
                tot["n"] += 1

                # ── FVG: активные midpoints ──
                fa = [( (f[1]+f[2])/2 ) for f in fvg_A(df) if f[5] is None]
                _fb = fvg_B(df)
                fb = [(z.top+z.bottom)/2 for z in (_fb.active_bull + _fb.active_bear)]
                tot["fvg_a"] += len(fa); tot["fvg_b"] += len(fb)
                tot["fvg_match"] += _match(fa, fb, price)

                # ── OB: активные midpoints ──
                ba = struct_A(df, length=5)
                oa = [((b.top+b.bottom)/2) for b in ob_A(df, ba) if b.mitigated_idx == -1]
                _sb = struct_B(df)
                _obB = ob_B(df, _sb)
                obb = [((b.top+b.bottom)/2) for b in (_obB.active_bull + _obB.active_bear)]
                tot["ob_a"] += len(oa); tot["ob_b"] += len(obb)
                tot["ob_match"] += _match(oa, obb, price)

                # ── structure: направление последнего слома ──
                la = ba[-1].direction if ba else None       # 'bull'/'bear'
                _brB = _sb.breaks[-1] if _sb.breaks else None
                lb = ("bull" if _brB and _brB.direction == "LONG" else
                      "bear" if _brB else None)
                if la and lb:
                    if la == lb: tot["struct_same"] += 1
                    else: tot["struct_diff"] += 1
                print(f"  {sym:5} {tf}: FVG A={len(fa)} B={len(fb)} match={_match(fa,fb,price)} | "
                      f"OB A={len(oa)} B={len(obb)} match={_match(oa,obb,price)} | last {la}/{lb}")
            except Exception as e:
                print(f"  {sym} {tf}: ERR {str(e)[:60]}")
    print("\n" + "=" * 60)
    n = tot["n"]
    print(f"ИТОГО ({n} прогонов):")
    print(f"  FVG:    A={tot['fvg_a']} зон, B={tot['fvg_b']} зон, совпало(A в B)={tot['fvg_match']} "
          f"({tot['fvg_match']/max(tot['fvg_a'],1)*100:.0f}% A)")
    print(f"  OB:     A={tot['ob_a']} зон, B={tot['ob_b']} зон, совпало={tot['ob_match']} "
          f"({tot['ob_match']/max(tot['ob_a'],1)*100:.0f}% A)")
    print(f"  STRUCT: совпало направление={tot['struct_same']}, разошлось={tot['struct_diff']} "
          f"({tot['struct_same']/max(tot['struct_same']+tot['struct_diff'],1)*100:.0f}% согласие)")


if __name__ == "__main__":
    main()
