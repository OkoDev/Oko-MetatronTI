# -*- coding: utf-8 -*-
"""LEG-VERIFY — учительский цикл детекции ноги (23.07, Егор: «как тебя научить детектить?!»).

Протокол: я детекчу значимую ногу (structure_trend, правило Егора) на свежих 4h → таблица
(+ уровни для TW) → Егор глазом: «та нога / не та (правильная: X→Y)» → вердикты в
tests/etalons/legs.yaml → детектор обязан проходить ВСЕ эталоны (как тесты Сферы Фазы).
Итерируем до ~90% совпадения → только потом большой бэктест на ногах.

Запуск: python scripts/leg_verify.py [--syms BTC,ETH,SOL,...]  (дефолт: 10 ликвидных)
"""
import sys, json, time, urllib.request
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from datetime import datetime, timezone

import pandas as pd

from core.smc.ote_matrix import structure_trend

DEFAULT = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "LINK", "AVAX", "SUI", "LTC"]
WINDOW = 200   # 4h-баров для structure_trend (как phase_watch)


def _kl4h(base, lim=200):
    url = (f"https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol={base}-USDT"
           f"&interval=4h&limit={lim}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "oko-leg"})
        d = json.load(urllib.request.urlopen(req, timeout=15)).get("data", [])
    except Exception:
        return None
    if not d:
        return None
    df = pd.DataFrame([(int(k["time"]), float(k["open"]), float(k["high"]), float(k["low"]),
                        float(k["close"])) for k in d],
                      columns=["time", "open", "high", "low", "close"]).sort_values("time").reset_index(drop=True)
    return df if len(df) >= 60 else None


def _dt(ms):
    if not ms:
        return "?"
    try:
        return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).strftime("%d.%m %H:%M")
    except Exception:
        return "?"


def main():
    syms = DEFAULT
    if "--syms" in sys.argv:
        syms = [s.strip().upper() for s in sys.argv[sys.argv.index("--syms") + 1].split(",")]
    print(f"🎓 LEG-VERIFY · свежие 4h×{WINDOW} BingX · structure_trend (правило Егора)")
    print(f"   Сверь с глазом на TW (4h): ТА ли нога? Вердикт: символ ✅ / символ ❌ origin→extreme\n")
    print(f"   {'symbol':7} {'нога':6} {'origin (начало импульса)':>28} {'extreme (конец)':>26} {'слом':>14}")
    print("   " + "─" * 88)
    out = []
    for base in syms:
        df = _kl4h(base)
        if df is None:
            print(f"   {base:7} — нет данных"); continue
        w = df.tail(WINDOW).reset_index(drop=True)
        st = structure_trend(w)
        tr = st.get("trend")
        if not tr:
            print(f"   {base:7} {'—':6} нет чистой ноги (боковик)")
            continue
        o, e = st.get("impulse_origin"), st.get("extreme")
        bl = st.get("break_level")
        # origin_ts/extreme_ts = ИНДЕКСЫ баров окна → мапим в time (мс)
        def _ts(i):
            try:
                return int(w["time"].iloc[int(i)]) if i is not None else None
            except Exception:
                return None
        ots, ets = _ts(st.get("origin_ts")), _ts(st.get("extreme_ts"))
        px = float(df["close"].iloc[-1])
        # позиция цены в ноге (0=origin,1=extreme)
        pos = (px - o) / (e - o) if (o and e and e != o) else None
        print(f"   {base:7} {tr.upper():6} {f'{o:.6g} ({_dt(ots)})':>28} {f'{e:.6g} ({_dt(ets)})':>26} "
              f"{f'{bl:.6g}' if bl else '—':>14}   px={px:.6g}"
              + (f" pos={pos:.2f}" if pos is not None else ""))
        out.append({"symbol": base, "trend": tr, "origin": o, "extreme": e,
                    "break_level": bl, "origin_ts": ots, "extreme_ts": ets})
    # уровни для быстрого копирования в TW / эталонный файл
    print("\n   → вердикты пришли мне текстом; каждый ❌ станет эталоном в tests/etalons/legs.yaml")


if __name__ == "__main__":
    main()
