# -*- coding: utf-8 -*-
"""ПРИ КАКОМ ГОРИЗОНТЕ И РАЗМЕРЕ ЦЕЛИ БАЗА ВЫХОДИТ В ПЛЮС (13.08.2026, Даат).

Вопрос Егора: «где деньги, нужен профессиональный взгляд на весь проект».

Установленный факт сессии — косты съедают цель тем сильнее, чем мельче ТФ:
    15m медиана стопа 1.04% → косты 0.35% = 34% цели → PF базы 0.62
    1h        1.88%         → 19%                    → PF 0.70
    4h        3.83%         →  9%                    → PF 0.77
Монотонно. Значит вопрос не «какой сигнал искать», а «какого размера движение ловить».

Здесь СПЛОШНОЙ скан без единого паттерна: ТФ × цель × горизонт удержания.
Метрика — % net с костами. Ищем ячейки, где даже ГОЛАЯ база (вход на каждом баре)
перестаёт терять. Если такие есть — туда и надо нести накопленные SMC-инструменты.
Если их нет нигде — проблема в костах, а не в стратегии.

Дополнительно печатается «сколько % движения нужно, чтобы косты были ≤N% цели».

Запуск:  python scripts/horizon_economics_scan.py [--coins 40]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DB = "ohlcv_cache.db"
COST = 0.35
TFS = ["15m", "1h", "4h", "1d"]
RULE = {"1h": "1h", "4h": "4h", "1d": "1D"}
# горизонты удержания в барах своего ТФ
TTLS = [24, 96, 192, 480]
TPS = [1.0, 2.0, 3.0, 5.0]
SL_LOOKBACK = 10


def agg(df, rule):
    return df.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()


def sim(df, tp_r, ttl, side="long"):
    n = len(df)
    H, L, C = df.high.values, df.low.values, df.close.values
    out = np.full(n, np.nan)
    sp = np.full(n, np.nan)
    step = max(1, ttl // 4)                 # прореживание: не перекрывать окна целиком
    for i in range(SL_LOOKBACK + 2, n - 2, step):
        e = C[i]
        end = min(i + ttl, n - 1)
        fl, fh = L[i + 1:end + 1], H[i + 1:end + 1]
        if len(fl) == 0:
            continue
        if side == "long":
            sl = L[i - SL_LOOKBACK:i + 1].min() * 0.999
            if sl >= e:
                continue
            sp[i] = (e - sl) / e * 100
            tp = e + tp_r * (e - sl)
            hs, ht = fl <= sl, fh >= tp
        else:
            sl = H[i - SL_LOOKBACK:i + 1].max() * 1.001
            if sl <= e:
                continue
            sp[i] = (sl - e) / e * 100
            tp = e - tp_r * (sl - e)
            hs, ht = fh >= sl, fl <= tp
        js = int(np.argmax(hs)) if hs.any() else 10 ** 9
        jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
        if js <= jt and js < 10 ** 9:
            r = -sp[i]
        elif jt < 10 ** 9:
            r = tp_r * sp[i]
        else:
            r = ((C[end] - e) if side == "long" else (e - C[end])) / e * 100
        out[i] = r
    return out, sp


def stat(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if len(v) == 0:
        return None
    neg = abs(v[v < 0].sum())
    return dict(n=len(v), wr=100 * (v > 0).mean(),
                pf=(v[v > 0].sum() / neg if neg > 0 else 99.0), mean=float(v.mean()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=40)
    ap.add_argument("--since", type=int, default=2023)
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? "
        "GROUP BY symbol HAVING n>8000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 116)
    print(f"ЭКОНОМИКА ГОРИЗОНТА · ГОЛАЯ БАЗА без единого паттерна · {len(syms)} монет с {a.since}")
    print(f"косты {COST}% round-trip · вход на каждом N-м баре · SL первым на баре")
    print("═" * 116)

    print(f"\n=== СКОЛЬКО НУЖНО ДВИЖЕНИЯ, ЧТОБЫ КОСТЫ НЕ СЪЕДАЛИ ЦЕЛЬ ===")
    print(f"{'доля костов в цели':<24} {'нужна цель':>12}")
    for share in (0.34, 0.20, 0.10, 0.05, 0.02):
        print(f"{f'{100*share:.0f}%':<24} {COST / share:>11.2f}%")

    # разрезы для 🟢-ячеек: сторона × год (защита от «крипта просто росла»)
    cuts = {}
    res = {}
    for tf in TFS:
        acc = {(tp, ttl): [] for tp in TPS for ttl in TTLS}
        sps = []
        for sym in syms:
            c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
            raw = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                              "WHERE symbol=? AND timeframe='15m' AND time>=? ORDER BY time",
                              c, params=(sym, t0))
            c.close()
            if len(raw) < 5000:
                continue
            raw["ts"] = pd.to_datetime(raw.time, unit="ms", utc=True)
            base = raw.set_index("ts")[["open", "high", "low", "close", "volume"]]
            d = base if tf == "15m" else agg(base, RULE[tf])
            if len(d) < 300:
                continue
            for tp in TPS:
                for ttl in TTLS:
                    if ttl > len(d) // 3:
                        continue
                    for side in ("long", "short"):
                        o, sp = sim(d, tp, ttl, side)
                        m = ~np.isnan(o)
                        acc[(tp, ttl)].extend(o[m].tolist())
                        # разрез по стороне/году/монете — для ячеек, вышедших в плюс
                        key = (tf, tp, ttl)
                        c_ = cuts.setdefault(key, {"net": [], "side": [], "yr": [], "sym": []})
                        c_["net"].extend((o[m] - COST).tolist())
                        c_["side"].extend([side] * int(m.sum()))
                        c_["yr"].extend(d.index.year.values[m].tolist())
                        c_["sym"].extend([sym] * int(m.sum()))
                        if tp == TPS[0] and ttl == TTLS[0] and side == "long":
                            sps.extend(sp[~np.isnan(sp)].tolist())
        res[tf] = (acc, sps)

        med_sp = float(np.median(sps)) if sps else float("nan")
        print(f"\n=== {tf} · медиана стопа {med_sp:.2f}% · косты = "
              f"{100 * COST / max(med_sp, 0.01):.0f}% от стопа ===")
        print(f"{'цель':<8}" + "".join(f"{f'TTL {t}б':>22}" for t in TTLS))
        for tp in TPS:
            line = f"{tp:.0f}R{'':<5}"
            for ttl in TTLS:
                s = stat([x - COST for x in acc[(tp, ttl)]])
                if s and s["n"] >= 200:
                    mark = "🟢" if s["mean"] > 0 else "  "
                    line += f"{mark}{s['mean']:>+7.3f}% PF{s['pf']:>5.2f}n{s['n']//1000:>3}k"
                else:
                    line += f"{'—':>22}"
            print(line)

    # ── РАЗРЕЗЫ ПЛЮСОВЫХ ЯЧЕЕК: главная защита от «крипта просто росла» ──
    print(f"\n" + "═" * 116)
    print("▌ РАЗРЕЗЫ ПЛЮСОВЫХ ЯЧЕЕК — LONG и SHORT отдельно, по годам")
    print("  если плюс только в LONG на растущих годах — это buy&hold, а не эдж")
    print("═" * 116)
    shown = 0
    for (tf, tp, ttl), c_ in sorted(cuts.items(), key=lambda kv: -np.mean(kv[1]["net"] or [0])):
        net = np.array(c_["net"]); side = np.array(c_["side"])
        yr = np.array(c_["yr"]); sy = np.array(c_["sym"])
        if len(net) < 400 or net.mean() <= 0:
            continue
        s_all = stat(net)
        print(f"\n▌ {tf} · TP={tp:.0f}R · TTL={ttl}б → всего {s_all['mean']:+.3f}%/сд "
              f"PF {s_all['pf']:.2f} n={s_all['n']}")
        for sd in ("long", "short"):
            s = stat(net[side == sd])
            if s and s["n"] >= 100:
                flag = "🟢" if s["mean"] > 0 else "🔴"
                print(f"   {flag} {sd.upper():<6} n={s['n']:>6} WR {s['wr']:>5.1f}% "
                      f"PF {s['pf']:>5.2f} {s['mean']:>+8.3f}%/сд")
        line = "   по годам: "
        for y in sorted(set(yr.tolist())):
            s = stat(net[yr == y])
            if s and s["n"] >= 60:
                line += f"{y}: {s['mean']:+.2f}%(PF{s['pf']:.2f})  "
        print(line)
        # только SHORT по годам — самая честная проверка
        line = "   SHORT по годам: "
        for y in sorted(set(yr.tolist())):
            s = stat(net[(yr == y) & (side == "short")])
            if s and s["n"] >= 40:
                line += f"{y}: {s['mean']:+.2f}%  "
        print(line)
        per = pd.Series(net).groupby(pd.Series(sy)).mean()
        srt = np.sort(net); cut = max(1, int(len(srt) * 0.10))
        print(f"   охват монет: плюс на {int((per > 0).sum())} из {len(per)} "
              f"({100 * (per > 0).mean():.0f}%) · безтоп10% {srt[:-cut].sum():+.1f}")
        shown += 1
        if shown >= 6:
            break

    print(f"\n" + "═" * 116)
    print("🟢 = голая база (вход на КАЖДОМ баре, без сигнала) уже не теряет денег.")
    print("Если такие ячейки есть — туда и нести SMC/конфлюэнцию: там сигнал добавляется")
    print("к нулевой базе, а не отыгрывает косты. Если 🟢 нет нигде — вопрос в костах.")
    print("═" * 116)
    return 0


if __name__ == "__main__":
    sys.exit(main())
