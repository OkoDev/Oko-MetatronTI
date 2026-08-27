# -*- coding: utf-8 -*-
"""СПРЕД VST ПРОТИВ БОЕВОГО — СИСТЕМАТИЧНО ЛИ (14.08.2026, Даат).

Проверка п.1 бэклога [[backlog_vst_spread_poisons_forward]]: разовый снимок показал
спред демо-домена VST в 10–350× шире боевого (ETH 0.001% против 0.184%). Если это
систематично, то `exec_sim_split_epic` объявил истиной форварда прибор с ФАНТОМНЫМ
налогом на исполнение, а гейт REAL-MONEY (20–30 чистых net+) не пройдёт никогда —
не из-за отсутствия эджа, а из-за демо-стакана.

Почему это важнее OOS механики: OOS проверяет НАХОДКУ, а это — ПРИБОР, которым
находку собираются проверять. Цикл «8 месяцев на сломанном приборе» уже был с FVG.

Домены (из `core/exchange/bingx_client.py`):
    LIVE = https://open-api.bingx.com      VST = https://open-api-vst.bingx.com
Читается ПУБЛИЧНЫЙ стакан (ключи не нужны): /openApi/swap/v2/quote/depth

Считается по каждой паре: spread% = (ask − bid) / mid × 100, и отношение VST/LIVE.
Разрезы: ликвидность (по обороту) · абсолютная величина налога в % от сделки.

Запуск:  python scripts/vst_spread_systematic_check.py [--top 60] [--rounds 3]
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LIVE = "https://open-api.bingx.com"
VST = "https://open-api-vst.bingx.com"
DEPTH = "/openApi/swap/v2/quote/depth"


def spread_of(base: str, symbol: str, timeout=8):
    """Возврат (spread_pct, mid) из публичного стакана домена."""
    try:
        r = requests.get(f"{base}{DEPTH}", params={"symbol": symbol, "limit": 5},
                         timeout=timeout)
        j = r.json()
    except Exception:
        return None, None
    d = j.get("data") or {}
    bids, asks = d.get("bids") or [], d.get("asks") or []
    if not bids or not asks:
        return None, None
    try:
        # BingX отдаёт bids по убыванию, asks — тоже строками [price, qty]
        bid = max(float(b[0]) for b in bids)
        ask = min(float(x[0]) for x in asks)
    except Exception:
        return None, None
    if bid <= 0 or ask <= 0 or ask < bid:
        return None, None
    mid = (ask + bid) / 2
    return (ask - bid) / mid * 100, mid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=60, help="сколько пар по обороту")
    ap.add_argument("--rounds", type=int, default=3, help="замеров во времени (не снимок)")
    ap.add_argument("--pause", type=float, default=20.0, help="пауза между раундами, с")
    a = ap.parse_args()

    print("═" * 108)
    print("СПРЕД VST ПРОТИВ БОЕВОГО · публичные стаканы обоих доменов BingX")
    print(f"{a.top} пар × {a.rounds} замеров с паузой {a.pause:.0f}с — проверка на систематичность")
    print("═" * 108)

    # вселенная по обороту с боевого домена
    try:
        r = requests.get(f"{LIVE}/openApi/swap/v2/quote/ticker", timeout=15).json()
        rows = []
        for t in (r.get("data") or []):
            s = t.get("symbol", "")
            if not s.endswith("-USDT"):
                continue
            qv = float(t.get("quoteVolume") or 0)
            if qv > 0:
                rows.append((s, qv))
        rows.sort(key=lambda x: -x[1])
    except Exception as e:
        print(f"не удалось получить тикеры: {e}")
        return 1
    syms = rows[:a.top]
    print(f"вселенная: {len(syms)} пар\n")

    rec = []
    for rd in range(1, a.rounds + 1):
        got = 0
        for sym, qv in syms:
            sl, ml = spread_of(LIVE, sym)
            sv, mv = spread_of(VST, sym)
            if sl is None or sv is None:
                continue
            rec.append(dict(round=rd, symbol=sym, live=sl, vst=sv,
                            ratio=(sv / sl) if sl > 0 else np.nan, qv=qv,
                            px_live=ml, px_vst=mv))
            got += 1
            time.sleep(0.12)
        print(f"  раунд {rd}/{a.rounds}: снято {got} пар")
        if rd < a.rounds:
            time.sleep(a.pause)

    if not rec:
        print("\nданных нет — публичный стакан не ответил")
        return 1
    d = pd.DataFrame(rec)

    print(f"\n=== СВОДКА ({len(d)} замеров) ===")
    print(f"  медиана спреда LIVE : {d.live.median():.4f}%")
    print(f"  медиана спреда VST  : {d.vst.median():.4f}%")
    print(f"  медиана отношения   : {d.ratio.median():.1f}×")
    print(f"  VST шире LIVE в     : {100 * (d.vst > d.live).mean():.0f}% замеров")
    print(f"  VST шире ≥3×        : {100 * (d.ratio >= 3).mean():.0f}% замеров")

    print(f"\n=== НАЛОГ НА ВХОД+ВЫХОД (полспреда × 2 = спред) ===")
    print(f"  на боевом : {d.live.median():.4f}% за круг")
    print(f"  на VST    : {d.vst.median():.4f}% за круг")
    print(f"  ФАНТОМНАЯ надбавка: {d.vst.median() - d.live.median():+.4f}% за круг")
    print(f"  для сравнения: комиссия в наших замерах 0.35% за круг")
    extra = d.vst.median() - d.live.median()
    print(f"  → налог VST = {100 * extra / 0.35:.0f}% от той ставки, которой мы мерили эдж")

    print(f"\n=== ПО ЛИКВИДНОСТИ (квартили оборота) ===")
    d["q"] = pd.qcut(d.qv, 4, labels=["Q1 неликвид", "Q2", "Q3", "Q4 ликвид"])
    g = d.groupby("q", observed=True).agg(n=("live", "size"), live=("live", "median"),
                                          vst=("vst", "median"), ratio=("ratio", "median"))
    print(f"  {'группа':<14} {'n':>5} {'LIVE':>9} {'VST':>9} {'отношение':>11}")
    for k, v in g.iterrows():
        print(f"  {str(k):<14} {int(v.n):>5} {v.live:>8.4f}% {v.vst:>8.4f}% {v.ratio:>10.1f}×")

    print(f"\n=== СТАБИЛЬНОСТЬ ВО ВРЕМЕНИ (разовый снимок или система?) ===")
    for rd, gg in d.groupby("round"):
        print(f"  раунд {rd}: медиана LIVE {gg.live.median():.4f}% · VST {gg.vst.median():.4f}% "
              f"· отношение {gg.ratio.median():.1f}×")

    print(f"\n=== ХУДШИЕ 12 ПАР ПО РАЗНИЦЕ (усреднено по раундам) ===")
    p = d.groupby("symbol").agg(live=("live", "median"), vst=("vst", "median"),
                                ratio=("ratio", "median"), qv=("qv", "first"))
    p["extra"] = p.vst - p.live
    p = p.sort_values("extra", ascending=False)
    print(f"  {'пара':<16} {'LIVE':>9} {'VST':>9} {'разница':>9} {'×':>7} {'оборот$':>14}")
    for s, v in p.head(12).iterrows():
        print(f"  {s:<16} {v.live:>8.4f}% {v.vst:>8.4f}% {v.extra:>+8.4f}% {v.ratio:>6.1f}× "
              f"{v.qv:>13,.0f}")

    print(f"\n=== РАСХОЖДЕНИЕ ЦЕН (не только спред: одинаковы ли середины?) ===")
    d["px_diff"] = (d.px_vst - d.px_live) / d.px_live * 100
    print(f"  медиана |отклонения mid VST от LIVE|: {d.px_diff.abs().median():.4f}%")
    print(f"  доля пар с отклонением >0.5%: {100 * (d.px_diff.abs() > 0.5).mean():.1f}%")

    d.to_csv("scripts/_vst_spread.csv", index=False)
    print("\n[dump] → scripts/_vst_spread.csv")
    print("═" * 108)
    return 0


if __name__ == "__main__":
    sys.exit(main())
