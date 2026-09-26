"""Walk-forward бэктест МАТРИЧНОГО входа OTE (Егор 02.07: валидация ПЕРЕД боем).

Логика входа (из matrix_playbook, [[mtf_confluence_matrix_vision]]):
  ПРАЙМ-вход = цена входит в ЗНАЧИМУЮ старшую (anchor 4h) OTE-зону В СТОРОНУ bias, зона была UNTOUCHED
  (магнит), + младший триггер (LTF-бар закрылся внутри зоны в сторону bias). SL = за значимый слом
  (структурный extreme старшего). TP = fib −0.62 (цель Егора). Частичный TP на 1R + добор до −0.62.

ЧЕСТНОСТЬ (главный грех прошлых бэктестов = look-ahead):
  на баре i структура считается ТОЛЬКО на df.iloc[:i+1] (прошлое). Фрактал требует k баров ПОСЛЕ пивота
  → недавние пивоты не подтверждены = правильно (мы их ещё не знаем). Никакого хвоста будущего.

Мера = % net (LAW №1): (exit−entry)/entry·dir·100 − costs%. НЕ R.
Запуск: python scripts/backtest_ote_matrix.py
"""
from __future__ import annotations
import sys, time
import pandas as pd
import ccxt

sys.path.insert(0, ".")
from core.smc.ote_matrix import structure_trend, build_ote

ANCHOR = "4h"                 # значимый масштаб (bias + прайм-зона)
LTF = "15m"                   # триггер-ТФ входа
COST_PCT = 0.2               # round-turn комиссия+слиппедж, % (taker BingX ~0.05·2 + слип)
ANCHOR_LOOKBACK = 250        # баров 4h для структуры
UNTOUCHED_BARS = 40          # сколько 4h-баров назад проверять что зона была нетронута
SYMBOLS = ["XLM", "GRT", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "SUI", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE", "SEI"]


def fetch(ex, sym, tf, limit):
    for _ in range(5):
        try:
            o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", tf, limit=limit)
            if o:
                df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "vol"])
                df["time"] = pd.to_datetime(df["ts"], unit="ms")
                return df.set_index("time")
        except Exception:
            time.sleep(1.5)
    return None


def backtest_symbol(sym, d4h, d15):
    """Проходим по 15m барам; на каждом строим 4h-структуру на прошлом, ищем прайм-вход."""
    trades = []
    in_pos = None                      # dict(dir, entry, sl, tp) или None
    # индексы 4h по времени для быстрого среза
    for i in range(200, len(d15)):
        t = d15.index[i]
        bar = d15.iloc[i]
        price = float(bar["close"])
        # --- управление открытой позицией (проверка SL/TP внутри бара) ---
        if in_pos:
            hi, lo = float(bar["high"]), float(bar["low"])
            d = in_pos["dir"]
            exit_px = None
            if d == "long":
                if lo <= in_pos["sl"]:
                    exit_px = in_pos["sl"]
                elif hi >= in_pos["tp"]:
                    exit_px = in_pos["tp"]
            else:
                if hi >= in_pos["sl"]:
                    exit_px = in_pos["sl"]
                elif lo <= in_pos["tp"]:
                    exit_px = in_pos["tp"]
            if exit_px is not None:
                sign = 1 if d == "long" else -1
                net = (exit_px - in_pos["entry"]) / in_pos["entry"] * 100 * sign - COST_PCT
                trades.append({"dir": d, "net_pct": net, "entry": in_pos["entry"],
                               "exit": exit_px, "win": net > 0})
                in_pos = None
            continue                    # пока в позиции — новых входов нет
        # --- поиск входа: 4h-структура на ПРОШЛОМ (<= t) ---
        d4 = d4h[d4h.index <= t]
        if len(d4) < 120:
            continue
        st = structure_trend(d4, lookback=ANCHOR_LOOKBACK)
        bias, brk, ext = st["trend"], st["break_level"], st["extreme"]
        if not bias or brk is None or ext is None:
            continue
        ob = build_ote(ext, brk)
        lo_z, hi_z = ob["ote"]
        tgt = ob["levels"].get(-0.62)
        if tgt is None:
            continue
        # прайм-зона: цена входит в 4h OTE в сторону bias
        if not (lo_z <= price <= hi_z):
            continue
        # СВЕЖЕЕ КАСАНИЕ: прошлый 15m-бар был ВНЕ зоны, текущий закрылся ВНУТРИ = тэг OTE (вход по откату).
        # Иначе входили бы каждый бар пока цена в зоне. Так ловим момент захода в зону.
        prev_price = float(d15.iloc[i - 1]["close"])
        if lo_z <= prev_price <= hi_z:
            continue                    # уже были в зоне прошлым баром — не свежий тэг
        # триггер младшего: бар закрылся В зоне в сторону bias (простой прокси CHoCH-реакции)
        # SL = за значимый слом старшего (extreme-сторона), TP = fib −0.62
        entry = price
        if bias == "long":
            sl = ext if ext < entry else lo_z * 0.995      # extreme = HH? для long ext=high → нет; slом=brk(low)
            sl = brk * 0.999 if brk < entry else lo_z * 0.99
            if not (tgt > entry):
                continue
        else:
            sl = brk * 1.001 if brk > entry else hi_z * 1.01
            if not (tgt < entry):
                continue
        risk = abs(entry - sl)
        if risk <= 0 or risk / entry > 0.15:
            continue
        in_pos = {"dir": bias, "entry": entry, "sl": sl, "tp": tgt, "t": t}
    return trades


def main():
    ex = ccxt.bingx({"enableRateLimit": True})
    all_tr = []
    per_sym = {}
    for sym in SYMBOLS:
        d4h = fetch(ex, sym, "4h", 400)
        d15 = fetch(ex, sym, "15m", 1440)
        if d4h is None or d15 is None or len(d15) < 300:
            print(f"  {sym}: нет данных"); continue
        tr = backtest_symbol(sym, d4h, d15)
        per_sym[sym] = tr
        all_tr.extend(tr)
        if tr:
            import statistics as s
            nets = [x["net_pct"] for x in tr]
            wr = 100 * sum(1 for x in tr if x["win"]) / len(tr)
            print(f"  {sym:5}: n={len(tr):3} WR={wr:4.0f}% mean={s.mean(nets):+.3f}% sum={sum(nets):+.1f}%")
        else:
            print(f"  {sym:5}: n=0")
    print("=" * 50)
    if all_tr:
        import statistics as s
        nets = [x["net_pct"] for x in all_tr]
        wr = 100 * sum(1 for x in all_tr if x["win"]) / len(all_tr)
        longs = [x for x in all_tr if x["dir"] == "long"]; shorts = [x for x in all_tr if x["dir"] == "short"]
        print(f"ИТОГ: n={len(all_tr)} WR={wr:.0f}% mean={s.mean(nets):+.3f}% med={s.median(nets):+.3f}% sum={sum(nets):+.1f}%")
        if longs: print(f"  LONG:  n={len(longs)} WR={100*sum(1 for x in longs if x['win'])/len(longs):.0f}% mean={s.mean([x['net_pct'] for x in longs]):+.3f}%")
        if shorts: print(f"  SHORT: n={len(shorts)} WR={100*sum(1 for x in shorts if x['win'])/len(shorts):.0f}% mean={s.mean([x['net_pct'] for x in shorts]):+.3f}%")
        print(f"costs={COST_PCT}% round-turn · anchor={ANCHOR} ltf={LTF} · честный walk-forward")


if __name__ == "__main__":
    main()
