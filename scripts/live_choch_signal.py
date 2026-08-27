# -*- coding: utf-8 -*-
"""ЖИВОЙ СИГНАЛ ПО МЕХАНИКЕ CHoCH → ОТКАТ → ВОЛНА C (18.08.2026, Даат).

Механика прошла OOS ([[choch_pullback_waveC_oos_passed]]) + усилители
([[choch_boosters_exits_oos]]). РЕАЛЬНЫЙ расчёт на текущих данных боевого домена BingX.

🔴 Скрипт НИЧЕГО НЕ ОТПРАВЛЯЕТ на биржу. Только читает публичные свечи и печатает.

19.08: расчёт вынесен в `core/smc/choch_wavec.py` — тот же калькулятор, что у боевого
лупа `bot/loops/choch_wavec_loop.py` ([[principle_reuse_not_duplication]]). Раньше
формулы дублировались здесь; расхождение скрипта с ботом было бы невидимым.

Запуск:  python scripts/live_choch_signal.py GRT [SOL ...]
         python scripts/live_choch_signal.py --scan 150     # скан вселенной
"""
from __future__ import annotations

import argparse
import sys
import time

import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import ccxt  # noqa: E402

from core.smc.choch_wavec import (ATR_HIGH, BLOCK_CLEAN, PULLBACK,  # noqa: E402
                                  SHIELD_LIGHT, TARGET_K, WAIT_BARS,
                                  boosters, find_setup, is_junk)


def analyze(ex, sym: str) -> dict:
    try:
        o1 = ex.fetch_ohlcv(sym, timeframe="1h", limit=1000)
    except Exception as e:                                     # noqa: BLE001
        return {"symbol": sym, "err": str(e)[:60]}
    if not o1 or len(o1) < 300:
        return {"symbol": sym, "err": "мало данных"}
    d = pd.DataFrame(o1, columns=["time", "open", "high", "low", "close", "volume"])
    d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
    d = d.set_index("ts")[["open", "high", "low", "close", "volume"]]
    # drop_last=True внутри find_setup отбросит незакрытый бар
    return find_setup(d, symbol=sym)


def report(r: dict) -> None:
    if "err" in r:
        print(f"  {r['symbol']:<12} ошибка: {r['err']}")
        return
    if "reason" in r:
        print(f"  {r['symbol']:<12} нет сетапа: {r['reason']}")
        return
    b = boosters(r)
    print(f"\n{'─' * 92}")
    print(f"  {r['symbol']}   цена {r['price']:.6g}")
    print(f"{'─' * 92}")
    print(f"  слом вниз: {r['choch_ts']} UTC · {r['age']} баров назад")
    print(f"  нога: {r['origin']:.6g} → {r['extreme']:.6g}  "
          f"(длина {r['leg_len'] / r['entry'] * 100:.2f}%)")
    print(f"  лимит на продажу: {r['entry']:.6g}   "
          f"({(r['entry'] - r['price']) / r['price'] * 100:+.2f}% от цены)")
    print(f"  стоп:             {r['sl']:.6g}   (риск {r['stop_pct']:.2f}%)")
    print(f"  цель (волна C):   {r['tp']:.6g}   "
          f"(потенциал {(r['entry'] - r['tp']) / r['entry'] * 100:.2f}%)")
    print(f"  соотношение риск/прибыль: 1 : "
          f"{(r['entry'] - r['tp']) / (r['sl'] - r['entry']):.2f}")
    print("\n  СТАТУС:")
    if r["invalid"]:
        print(f"    🔴 СЕТАП НЕДЕЙСТВИТЕЛЕН — цена уже была выше стопа {r['sl']:.6g}")
    elif r["filled"]:
        print(f"    ⚠️  лимит уже отрабатывался (цена доходила до {r['entry']:.6g}) — вход упущен")
    elif r["age"] > WAIT_BARS:
        print(f"    ⚠️  слом старый ({r['age']} баров, механика ждёт откат {WAIT_BARS}) — протух")
    else:
        print("    🟢 ЖИВОЙ: лимит ещё не тронут, слом свежий")
    # Коридор стопа 8-15% — замер 19.08 на 198 монетах: PF 1.07 → 1.21, плюс в каждом году.
    print("\n  ФИЛЬТР РАЗМЕРА (сильнейший, замер 19.08):")
    sp = r["stop_pct"]
    print(f"    стоп {sp:.2f}%  "
          f"{'🟢 в коридоре 8-15% (PF 1.21)' if 8 <= sp <= 15 else ('🔴 мелкий — косты съедают цель (PF 1.01)' if sp < 8 else '🔴 крупный (PF 0.88)')}")
    print("\n  УСИЛИТЕЛИ (OOS-числа 18.08):")
    print(f"    помеха на пути к цели: {r['block']:.1f}  "
          f"{f'🟢 чисто (PF 1.50)' if b['clean_path'] else 'зажато'}")
    print(f"    уровни у стопа:        {r['shield']:.1f}  "
          f"{'🟢 мало (PF 1.32)' if b['light_shield'] else 'много'}")
    print(f"    волатильность ATR:     {r['atr_pct']:.2f}%  "
          f"{'🟢 высокая (PF 1.29)' if b['high_atr'] else 'обычная'}")
    print(f"    цена под недельным S1: {'🟢 да (PF 1.84)' if b['under_s1w'] else 'нет'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*", help="например GRT SOL")
    ap.add_argument("--scan", type=int, default=0,
                    help="сканировать N пар по обороту (0 = все крипто-пары)")
    ap.add_argument("--no-junk-filter", action="store_true",
                    help="НЕ отсеивать синтетику (акции/индексы/сырьё)")
    a = ap.parse_args()

    ex = ccxt.bingx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    print("═" * 92)
    print(f"CHoCH → ОТКАТ {PULLBACK} → ВОЛНА C ×{TARGET_K} · 1h · SHORT")
    print("данные: боевой домен BingX, последний НЕзакрытый бар отброшен")
    print("🔴 скрипт ничего не отправляет на биржу — только читает и считает")
    print("═" * 92)

    if a.symbols:
        for s in a.symbols:
            sym = s if "/" in s else f"{s.upper()}/USDT:USDT"
            report(analyze(ex, sym))
            time.sleep(ex.rateLimit / 1000)
        return 0

    tk = ex.fetch_tickers()
    allp = [(s, float(t.get("quoteVolume") or 0)) for s, t in tk.items()
            if s.endswith(":USDT") and (t.get("quoteVolume") or 0) > 0]
    if a.no_junk_filter:
        rows, cut = allp, []
    else:
        rows = [(s, v) for s, v in allp if not is_junk(s)]
        cut = [s for s, _ in allp if is_junk(s)]
    rows.sort(key=lambda x: -x[1])
    limit = a.scan if a.scan > 0 else len(rows)
    print(f"\nвсего пар на бирже: {len(allp)} · отсеяно синтетики: {len(cut)} · "
          f"крипто-пар: {len(rows)} · сканируем: {min(limit, len(rows))}\n")

    live = []
    for i, (sym, _) in enumerate(rows[:limit], 1):
        r = analyze(ex, sym)
        if "err" not in r and "reason" not in r and r["live"]:
            live.append(r)
        if i % 30 == 0:
            print(f"  … проверено {i}/{limit} · живых {len(live)}")
        time.sleep(ex.rateLimit / 1000)

    # Сортировка по силе: сперва попавшие в коридор стопа, затем по чистоте пути.
    live.sort(key=lambda r: (not (8 <= r["stop_pct"] <= 15), r["block"], -r["atr_pct"]))
    print(f"\nЖИВЫХ СЕТАПОВ: {len(live)} · из них в коридоре стопа 8-15%: "
          f"{sum(1 for r in live if 8 <= r['stop_pct'] <= 15)}")
    for r in live[:12]:
        report(r)
    print("\n" + "═" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
