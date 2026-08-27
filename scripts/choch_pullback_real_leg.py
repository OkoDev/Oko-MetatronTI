# -*- coding: utf-8 -*-
"""ТА ЖЕ МЕХАНИКА, НО НА ЭТАЛОННОЙ НОГЕ OKO-SM (15.08.2026, Даат).

Егор: «расчёт ноги тут имеет место?! я всё никак не успокоюсь, т.к. это напрямую
влияет на зону OTE».

Он прав, и это могло обнулить весь замер. В `choch_pullback_atrflip_waveC.py` нога
считалась ГРУБО:
    a_lo = L[i-20:i+1].min()   # просто минимум за 20 баров
    a_hi = C[i]                # close на баре CHoCH
Это не структурная нога. От неё зависит ВСЁ: зона коррекции (где стоит лимит),
цель волны C и стоп. Ровно тот класс ошибки, что зафиксирован в
[[ote_detector_wrong_leg_measured]]: направление совпадало с эталоном в 62%,
зоны не пересекались в 66%.

Здесь нога берётся из ЭТАЛОНА — `core/smc/oko_sm_engine`:
    run_structure(df, swing_len=50, internal_len=5, record_legs=True)
    → st.leg_history[t] = current_leg ПОСЛЕ бара t (каузально: решение на t+1 по ноге t)
    → {"trend", "origin", "origin_i", "extreme", "extreme_i"}
Движок верифицирован метками графика (BTC 15/15, SOL 93%) — [[oko_sm_engine_ported]].
CHoCH берётся оттуда же (st.events), а не из compute_flags.

Печатается СРАВНЕНИЕ грубой ноги с эталонной: насколько расходятся длина и зона входа.

Запуск:  python scripts/choch_pullback_real_leg.py [--coins 100] [--tf 1h]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.smc.oko_sm_engine import run_structure, current_leg  # noqa: E402

DB = "ohlcv_cache.db"
RULE = {"1h": "1h", "4h": "4h", "1d": "1D"}
BAR_H = {"15m": 0.25, "1h": 1.0, "4h": 4.0, "1d": 24.0}
COST_LIMIT = 0.35
PB = 0.236
WAVE_K = [1.0, 1.272, 1.618, 2.0, 2.618]
# ~4 суток удержания в барах каждого ТФ (5m добавлен 17.08 по вопросу Егора)
TTL_BY_TF = {"5m": 1152, "15m": 384, "1h": 96, "4h": 24, "1d": 4}
# ~12ч ожидания коррекции в барах каждого ТФ
WAIT_BY_TF = {"5m": 144, "15m": 48, "1h": 12, "4h": 6, "1d": 3}


def resolve(H, L, C, j, side, entry, sl, tp, ttl):
    end = min(j + ttl, len(C) - 1)
    fl, fh = L[j + 1:end + 1], H[j + 1:end + 1]
    if len(fl) == 0:
        return None
    if side == "long":
        hs, ht = fl <= sl, fh >= tp
        lo, hi_ = (sl - entry) / entry * 100, (tp - entry) / entry * 100
        tail = (C[end] - entry) / entry * 100
    else:
        hs, ht = fh >= sl, fl <= tp
        lo, hi_ = (entry - sl) / entry * 100, (entry - tp) / entry * 100
        tail = (entry - C[end]) / entry * 100
    js = int(np.argmax(hs)) if hs.any() else 10 ** 9
    jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
    return lo if (js <= jt and js < 10 ** 9) else (hi_ if jt < 10 ** 9 else tail)


def stat(rows, days, cost=COST_LIMIT):
    if not rows or len(rows) < 40:
        return None
    pr = np.array([r[0] for r in rows], float)
    sp = np.array([r[1] for r in rows], float)
    net = pr - cost
    neg = abs(net[net < 0].sum())
    r = net / sp
    return dict(n=len(rows), wr=100 * (net > 0).mean(),
                pf=(net[net > 0].sum() / neg if neg > 0 else 99.0),
                pct=float(net.mean()), stop=float(np.median(sp)),
                freq=len(rows) / max(days, 1),
                r_day=float(r.mean()) * len(rows) / max(days, 1))


def show(nm, s):
    if not s:
        print(f"    {nm:<36} — мало данных")
        return
    mark = "🟢" if (s["wr"] > 50 and s["pct"] > 0) else ("✅" if s["wr"] > 50 else
                                                        ("💰" if s["pct"] > 0 else "  "))
    print(f"  {mark}{nm:<36} n={s['n']:>5} WR {s['wr']:>5.1f}% PF {s['pf']:>5.2f} "
          f"стоп {s['stop']:>5.2f}% {s['pct']:>+7.2f}%/сд {s['freq']:>5.2f}сд/дн "
          f"{s['r_day']:>+7.3f}R/дн")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=100)
    ap.add_argument("--since", type=int, default=2024)
    ap.add_argument("--tf", type=str, default="1h")
    ap.add_argument("--internal", action="store_true",
                    help="брать internal-CHoCH (len5) вместо swing-CHoCH (len50)")
    a = ap.parse_args()
    ttl, wait = TTL_BY_TF[a.tf], WAIT_BY_TF[a.tf]

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? AND time>=? "
        "GROUP BY symbol HAVING n>? ORDER BY n DESC LIMIT ?",
        ("5m" if a.tf == "5m" else "15m", t0, 20000 if a.tf == "5m" else 8000,
         a.coins)).fetchall()]
    con.close()

    print("═" * 120)
    print(f"CHoCH → КОРРЕКЦИЯ → ВОЛНА C · НОГА ИЗ ЭТАЛОНА OKO-SM · {a.tf} · {len(syms)} монет")
    print(f"нога: run_structure(swing_len=50, internal_len=5).leg_history — каузально")
    print(f"CHoCH: {'internal (len5)' if a.internal else 'swing (len50)'} · "
          f"откат {PB} · ждём {wait}б · держим {ttl}б · косты {COST_LIMIT}%")
    print("═" * 120)

    A = defaultdict(list)
    CNT = defaultdict(int)
    diffs = {"len": [], "entry": [], "dir_same": []}
    days = 1

    for si, sym in enumerate(syms, 1):
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        # 🔴 17.08: 5m берётся НАТИВНО из кэша (53М строк, 449 символов), а НЕ ресемплом
        # из 15m через ffill — тот «размножал» каждый бар втрое и ломал структуру.
        # Агрегация ВНИЗ (15m→1h→4h→1d) корректна, «размножение ВВЕРХ» — подделка.
        src_tf = "5m" if a.tf == "5m" else "15m"
        min_bars = 20000 if a.tf == "5m" else 8000
        raw = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                          "WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",
                          c, params=(sym, src_tf, t0))
        c.close()
        if len(raw) < min_bars:
            continue
        raw["ts"] = pd.to_datetime(raw.time, unit="ms", utc=True)
        base = raw.set_index("ts")[["open", "high", "low", "close", "volume"]]
        d = base if a.tf in ("5m", "15m") else base.resample(RULE[a.tf]).agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "volume": "sum"}).dropna()
        if len(d) < 300:
            continue
        days = max(days, (d.index.max() - d.index.min()).days)
        dd = d.reset_index(drop=True)
        try:
            st = run_structure(dd, swing_len=50, internal_len=5, record_legs=True)
        except Exception:
            continue
        legs = st.leg_history
        if not legs or len(legs) != len(dd):
            continue
        H, L, C = dd.high.values, dd.low.values, dd.close.values
        n = len(dd)

        for ev in st.events:
            if ev.kind != "CHoCH" or ev.internal != a.internal:
                continue
            i = int(ev.i)
            if i < 60 or i >= n - ttl - wait - 2:
                continue
            side = "long" if ev.bull else "short"
            leg = legs[i]
            if not leg:
                continue
            # эталонная нога должна совпадать по направлению со сломом
            if (leg["trend"] == "long") != ev.bull:
                diffs["dir_same"].append(0)
                continue
            diffs["dir_same"].append(1)
            CNT[(side, "CHoCH")] += 1

            origin, extreme = float(leg["origin"]), float(leg["extreme"])
            A_len = abs(extreme - origin)
            if A_len <= 0:
                continue
            # ── сравнение с ГРУБОЙ ногой (как было в прошлом скрипте) ──
            if side == "long":
                g_lo, g_hi = float(L[max(0, i - 20):i + 1].min()), float(C[i])
            else:
                g_hi, g_lo = float(H[max(0, i - 20):i + 1].max()), float(C[i])
            g_len = abs(g_hi - g_lo)
            if g_len > 0:
                diffs["len"].append(A_len / g_len)
            entry = extreme - A_len * PB if side == "long" else extreme + A_len * PB
            g_entry = (g_hi - g_len * PB) if side == "long" else (g_lo + g_len * PB)
            if entry > 0:
                diffs["entry"].append(abs(entry - g_entry) / entry * 100)

            # ── вход лимитом в коррекцию от эталонной ноги ──
            jf = None
            for j in range(i + 1, min(i + 1 + wait, n)):
                if (side == "long" and L[j] <= entry) or (side == "short" and H[j] >= entry):
                    jf = j; break
            if jf is None:
                continue
            CNT[(side, "коррекция")] += 1
            sl = origin * 0.999 if side == "long" else origin * 1.001   # стоп за НАЧАЛО ноги
            sp = abs(entry - sl) / entry * 100
            if sp <= 0 or sp > 25:
                continue
            for k in WAVE_K:
                tp = entry + A_len * k if side == "long" else entry - A_len * k
                pr = resolve(H, L, C, jf, side, entry, sl, tp, ttl)
                if pr is not None:
                    A[(side, f"волна C ×{k}")].append((pr, sp))
            risk = abs(entry - sl)
            for tg in (1.0, 2.0):
                tp = entry + tg * risk if side == "long" else entry - tg * risk
                pr = resolve(H, L, C, jf, side, entry, sl, tp, ttl)
                if pr is not None:
                    A[(side, f"цель {tg:.0f}R")].append((pr, sp))
        if si % 25 == 0:
            print(f"  … монет: {si}/{len(syms)}")

    print(f"\nокно {days} дней")
    if diffs["len"]:
        r = np.array(diffs["len"])
        e = np.array(diffs["entry"])
        ds = np.array(diffs["dir_same"])
        print(f"\n=== НАСКОЛЬКО ГРУБАЯ НОГА РАСХОДИТСЯ С ЭТАЛОННОЙ ===")
        print(f"  направление ноги совпало со сломом: {100 * ds.mean():.1f}% случаев")
        print(f"  длина эталонной / грубой: медиана {np.median(r):.2f}× · "
              f"p10 {np.percentile(r, 10):.2f}× · p90 {np.percentile(r, 90):.2f}×")
        print(f"  расхождение ЗОНЫ ВХОДА: медиана {np.median(e):.2f}% цены · "
              f"p90 {np.percentile(e, 90):.2f}%")
        print(f"  → грубая нога {'СИЛЬНО' if np.median(r) > 1.3 or np.median(r) < 0.77 else 'умеренно'} "
              f"отличается от структурной")

    for side in ("short", "long"):
        print(f"\n{'=' * 120}")
        print(f"=== {side.upper()} · CHoCH {CNT[(side, 'CHoCH')]} → "
              f"коррекция {CNT[(side, 'коррекция')]} "
              f"({100 * CNT[(side, 'коррекция')] / max(CNT[(side, 'CHoCH')], 1):.0f}%) ===")
        for k in WAVE_K:
            show(f"волна C ×{k}", stat(A[(side, f"волна C ×{k}")], days))
        for tg in (1.0, 2.0):
            show(f"цель {tg:.0f}R", stat(A[(side, f"цель {tg:.0f}R")], days))

    print("\n" + "═" * 120)
    print("Нога и стоп теперь структурные: origin = начало импульса по OKO-SM,")
    print("extreme = его конец. Стоп за origin (инвалидация ноги), а не за случайный минимум.")
    print("═" * 120)
    return 0


if __name__ == "__main__":
    sys.exit(main())
