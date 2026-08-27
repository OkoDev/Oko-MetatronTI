"""
long_revival_watch.py — ВАХТА ЗА ВОЗВРАЩЕНИЕМ ЛОНГА.

Повод (Егор, 21.08.2026): «жалко что всё-таки 15m long не нашёлся».

Точная формулировка находки: лонг на 15m НЕ «не существует» — он БЫЛ и УМЕР.
    до 2024:  PF 2.41 · охват 80% · безтоп10% ПЛЮС
    с 2025:   PF 0.64 · охват 29%
Проверено восемь семей признаков и вся матрица 146 признаков: 20 прошли обучающую
половину, ноль пережили отложенную. Развалилась САМА БАЗА, а не фильтры —
значит никакой признак его не вернёт, вернуть может только смена режима.

Этот скрипт нужен, чтобы возвращение было ЗАМЕЧЕНО, а не пропущено. Раз в неделю
меряет лонг на свежем окне и сравнивает с порогом оживления.

    python scripts/long_revival_watch.py            # разовый прогон
    python scripts/long_revival_watch.py --weeks 8  # окно наблюдения

Что считается оживлением (все условия сразу, иначе это шум):
    PF > 1.5 · безтоп10% ПОЛОЖИТЕЛЬНЫЙ · охват монет > 45% · не менее 60 сделок
Порог взят не с потолка: база 2022-24, когда лонг был живым, давала 2.41/80%,
а мёртвая база 2025-26 — 0.64/29%. Полтора и 45% лежат между ними с запасом.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

DB = str(ROOT / "ohlcv_cache.db")
COST, PEN = 0.35, 0.15
WAIT, HOLD = 48, 384
NL = "\n"
# Порог оживления — см. докстроку.
MIN_PF, MIN_COV, MIN_N = 1.5, 45.0, 60


def measure(n_symbols: int, weeks: int) -> dict | None:
    from core.smc.impulse_fib import _atr, find_impulses, is_junk
    import hashlib, random

    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as c:
        rows = c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' "
                         "GROUP BY symbol HAVING n>12000 ORDER BY n DESC").fetchall()
    syms = [s for s, _ in rows if not is_junk(s)]
    random.Random(19).shuffle(syms)
    t0 = pd.Timestamp.now(tz="UTC") - pd.Timedelta(weeks=weeks)
    res = []
    for sym in syms[:n_symbols]:
        with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as c:
            d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                            "WHERE symbol=? AND timeframe='15m' ORDER BY time", c, params=(sym,))
        if len(d) < 6000:
            continue
        d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
        df = d.set_index("ts")[["open", "high", "low", "close", "volume"]]
        dd = df.reset_index(drop=True)
        H, L, C, V = dd.high.values, dd.low.values, dd.close.values, dd.volume.values
        n = len(dd)
        aa = _atr(dd); atr = aa.values; rgv = (aa / aa.rolling(100).mean()).values
        ema = dd.close.ewm(span=200, adjust=False).mean().values
        vm = pd.Series(V).rolling(120).mean().values
        for a, b, up in find_impulses(H, L, C, atr, n):
            if not up: continue                      # только лонг
            if b < 400 or b >= n - HOLD - WAIT - 2: continue
            if df.index[b] < t0: continue            # только свежее окно
            x_ = float(C[b]); amp = abs(x_ - float(C[a]))
            if amp <= 0: continue
            vr = float(V[a:b+1].sum() / (b-a+1) / vm[b]) if vm[b] > 0 else 0
            r_ = float(rgv[b]) if not np.isnan(rgv[b]) else 1
            if not (1.0 <= vr < 1.5 and C[b] > ema[b] and r_ >= 1.1): continue
            e = x_ - 0.382*amp; tp = x_ + 1.618*amp; sl = e - 2.5*atr[b]
            if sl >= e: continue
            sp = abs(e - sl) / e * 100
            if not (1.5 <= sp <= 3.234): continue
            deep = e * (1 - PEN/100)
            w = range(b+1, min(b+1+WAIT, n))
            jf = next((q for q in w if L[q] <= e), None)
            jd = next((q for q in w if L[q] <= deep), None)
            if jf is None or jd is None: continue
            end = min(jf+HOLD, n-1); fh, fl = H[jf+1:end+1], L[jf+1:end+1]
            if len(fh) == 0: continue
            jt = next((k for k in range(len(fh)) if fh[k] >= tp), 10**9)
            js = next((k for k in range(len(fl)) if fl[k] <= sl), 10**9)
            if js <= jt and js < 10**9: r = (sl-e)/e*100
            elif jt < 10**9:            r = (tp-e)/e*100
            else:                       r = (float(C[end])-e)/e*100
            res.append({"sym": sym, "pnl": r - COST})
    if not res:
        return None
    R = pd.DataFrame(res)
    p = R.pnl.values
    w = p[p > 0]; gl = -p[p <= 0].sum(); s = np.sort(p)[::-1]
    per = R.groupby("sym").pnl.sum()
    return dict(n=len(p), wr=len(w)/len(p)*100, pf=(w.sum()/gl if gl else 0.0),
                bt=s[int(len(s)*0.1):].sum(), cov=(per > 0).mean()*100,
                coins=R.sym.nunique())


def main() -> int:
    ap = argparse.ArgumentParser(description="Вахта за возвращением лонга на 15m")
    ap.add_argument("--weeks", type=int, default=12, help="окно наблюдения, недель")
    ap.add_argument("--symbols", type=int, default=60)
    a = ap.parse_args()

    st = measure(a.symbols, a.weeks)
    print(f"ЛОНГ НА 15m · окно {a.weeks} недель · {a.symbols} монет")
    if st is None or st["n"] < MIN_N:
        got = 0 if st is None else st["n"]
        print(f"  сделок {got} — мало для вывода (нужно {MIN_N}). Ждём.")
        return 0
    print(f"  n={st['n']}  монет {st['coins']}  WR {st['wr']:.1f}%  PF {st['pf']:.2f}  "
          f"безтоп10% {st['bt']:+.0f}  охват {st['cov']:.0f}%")
    print()
    print("  для сравнения — историческая база:")
    print("    до 2024 (лонг был жив):  PF 2.41 · охват 80% · безтоп10% ПЛЮС")
    print("    2025-26 (лонг мёртв):    PF 0.64 · охват 29%")
    print()
    alive = st["pf"] > MIN_PF and st["bt"] > 0 and st["cov"] > MIN_COV

    # 🔔 ОПОВЕЩЕНИЕ ТОЛЬКО ПРИ СМЕНЕ СОСТОЯНИЯ (Егор: «могу пропустить телеграм»).
    # Три пути: Telegram (узнать сразу) · TASKS.md (не потерять) · шина событий
    # через watch_bridge (узнают остальные сферы Куба).
    state = "ALIVE" if alive else ("NEAR" if st["pf"] > 1.2 else "DEAD")
    try:
        from scripts._alert import notify
        res = notify(
            "long_watch", state,
            title="Лонг на 15m",
            tg_text=("*Лонг на 15m: " + state + "*" + NL
                     + f"PF {st['pf']:.2f} · WR {st['wr']:.1f}% · охват {st['cov']:.0f}% · "
                     + f"безтоп10% {st['bt']:+.0f} (n={st['n']})" + NL + NL
                     + "было живо до 2024: PF 2.41 / охват 80%" + NL
                     + "мёртво 2025-26: PF 0.64 / охват 29%"),
            task_detail=(f"PF {st['pf']:.2f} · охват {st['cov']:.0f}% · безтоп10% {st['bt']:+.0f}. "
                         + ("**Перемерить полным протоколом** (research_harness, слепой отбор), "
                            "затем обсудить `trading.impulse_fib_15m.sides`"
                            if alive else "Наблюдение продолжается")),
        )
        if res["tg"] or res["tasks"]:
            print(f"  🔔 состояние сменилось {res['prev']} → {state}: "
                  f"telegram={'✅' if res['tg'] else '—'} · TASKS.md={'✅' if res['tasks'] else '—'}")
    except Exception as e:                                       # noqa: BLE001
        print(f"  ⚠️ оповещение не удалось: {type(e).__name__}: {e}")

    if alive:
        print(f"  🟢🟢 ЛОНГ ОЖИЛ: PF {st['pf']:.2f} > {MIN_PF} · безтоп10% "
              f"{st['bt']:+.0f} > 0 · охват {st['cov']:.0f}% > {MIN_COV:.0f}%")
        print("  → перемерить полным протоколом (research_harness, слепой отбор),")
        print("     затем обсудить включение long-стороны в trading.impulse_fib_15m.sides")
    else:
        miss = []
        if st["pf"] <= MIN_PF: miss.append(f"PF {st['pf']:.2f} ≤ {MIN_PF}")
        if st["bt"] <= 0: miss.append(f"безтоп10% {st['bt']:+.0f} ≤ 0")
        if st["cov"] <= MIN_COV: miss.append(f"охват {st['cov']:.0f}% ≤ {MIN_COV:.0f}%")
        print(f"  ⚪ ещё не ожил: {' · '.join(miss)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
