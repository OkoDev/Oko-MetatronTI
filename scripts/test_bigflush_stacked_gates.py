# -*- coding: utf-8 -*-
"""П.7 ОЧЕРЕДИ: СОВМЕСТНАЯ УСТОЙЧИВОСТЬ гейтов bigflush15 (12.08.2026).

Повод: в бою bigflush15 дал 3 сделки за две недели вместо расчётных ~36/мес.
Воронка по логам показала: кластер-гейт режет 143 из 144 (99.3%), хотя в бэктесте
«терял 12%». Каждый гейт калибровался ОТДЕЛЬНО на своей базе; их произведение
не мерили ни разу ([[bigflush_frequency_collapse_stacked_gates]]).

Здесь гейты накладываются ПОСЛЕДОВАТЕЛЬНО, и на каждом шаге печатается не только
качество, но и ЧАСТОТА. Цель = частота × медиана (%/мес), а не медиана.

Сетап 1:1 как в бою (взят из test_bos_gate_bigflush.py): ATRTrend(43,1.25)↑ +
WT(10,21)<−60 растущий + SL=min(low[-3:])*0.997, стоп 4-12%, ликвидная половина,
TP1R, TTL 24 бара. Косты 0.35% round-trip (ЗАКОН №1: мерить % net).

Запуск:  python scripts/test_bigflush_stacked_gates.py [n_монет=40]
"""
import datetime as dt
import sqlite3
import sys
import warnings
from collections import defaultdict, deque

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.oko_sm_engine import run_structure

DB = "ohlcv_cache.db"
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 40
COST = 0.35
BAD_HOURS = set(range(8, 21))       # бой: НЕ торгуем 08:00-21:00 UTC
WIN_BOS = 20                        # 5ч на 15m


def load(sym, tf, t0):
    c = sqlite3.connect(DB)
    df = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                     "AND timeframe=? AND time>=? ORDER BY time", c, params=(sym, tf, t0))
    c.close()
    return df.reset_index(drop=True)


def wt(df, n1=10, n2=21):
    hlc = (df.high + df.low + df.close) / 3
    esa = hlc.ewm(span=n1).mean()
    d = (hlc - esa).abs().ewm(span=n1).mean()
    return ((hlc - esa) / (0.015 * d.replace(0, np.nan))).ewm(span=n2).mean().fillna(0).values


def atrt(df, period=43, factor=1.25):
    h, l, c = df.high, df.low, df.close
    hl2 = ((h + l) / 2).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean().values
    up = hl2 - factor * atr; dn = hl2 + factor * atr
    n = len(c); cv = c.values
    u = np.zeros(n); d_ = np.zeros(n); dirn = np.zeros(n)
    u[0], d_[0], dirn[0] = up[0], dn[0], 1
    for i in range(1, n):
        u[i] = max(up[i], u[i-1]) if cv[i-1] > u[i-1] else up[i]
        d_[i] = min(dn[i], d_[i-1]) if cv[i-1] < d_[i-1] else dn[i]
        dirn[i] = 1 if cv[i] > d_[i-1] else (-1 if cv[i] < u[i-1] else dirn[i-1])
    return dirn


def ex_tp1r(i, H, L, C, sl, ttl=24):
    e = C[i]; tp = e + (e - sl); end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if L[j] <= sl: return (sl - e) / e * 100
        if H[j] >= tp: return (tp - e) / e * 100
    return (C[end] - e) / e * 100


SINCE_Y = int(sys.argv[2]) if len(sys.argv) > 2 else 2024   # рой (Model A): проверить на 2023 OOS
TF = sys.argv[3] if len(sys.argv) > 3 else "15m"   # DS: прогнать тот же сигнал на 1h — дело в ТФ или в механике?
BARS_PER_MONTH = {"15m": 2920, "1h": 730, "4h": 182}.get(TF, 2920)
t0 = int(dt.datetime(SINCE_Y, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute(
    "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? AND time>=? "
    "GROUP BY symbol HAVING n>? ORDER BY n DESC LIMIT ?", (TF, t0, BARS_PER_MONTH*6, NCOIN)).fetchall()]
c.close()

DATA, turn = {}, {}
for s in syms:
    d = load(s, TF, t0)
    if len(d) >= BARS_PER_MONTH * 4:
        DATA[s] = d
        turn[s] = float(np.nanmedian((d.close * d.volume).values))
mt = np.nanmedian(list(turn.values()))
liq = [s for s in DATA if turn[s] >= mt]

# ── ИНВЕНТАРИЗАЦИЯ ОКНА (протокол: печатать, а не помнить) ──────────────
any_df = DATA[liq[0]]
ts = pd.to_datetime(any_df.time, unit="ms")
print(f"ТФ={TF} · монет всего {len(DATA)}, ликвидных {len(liq)} · окно {ts.min():%Y-%m-%d} → {ts.max():%Y-%m-%d}")
months = (ts.max() - ts.min()).days / 30.44
print(f"длина окна: {months:.1f} мес · косты {COST}% · сетап bigflush15 1:1 как в бою\n")

# ── СБОР СЫРЫХ СИГНАЛОВ ─────────────────────────────────────────────────
sig = []          # (bar_time_ms, sym, year, pnl, bos_dn, hour_utc)
for s in liq:
    d = DATA[s]
    st = run_structure(d, swing_len=50, internal_len=5)
    ev_by_bar = defaultdict(list)
    for e in st.events:
        ev_by_bar[int(e.i)].append(e)
    w = wt(d); tr_ = atrt(d)
    H, L, C = d.high.values, d.low.values, d.close.values
    tt = d.time.values
    yr = pd.to_datetime(d.time, unit="ms").dt.year.values
    hr = pd.to_datetime(d.time, unit="ms").dt.hour.values
    recent, cnt = deque(), defaultdict(int)
    for i in range(120, len(d) - 1):
        for e in ev_by_bar.get(i, []):
            k = (e.kind, bool(e.bull), bool(e.internal))
            recent.append((i, k)); cnt[k] += 1
        while recent and recent[0][0] < i - WIN_BOS:
            _, k = recent.popleft(); cnt[k] -= 1
        if not (tr_[i] > 0 and w[i] < -60 and w[i] > w[i - 1]):
            continue
        e_ = C[i]; sl = L[max(0, i - 3):i + 1].min() * 0.997
        if sl >= e_:
            continue
        dist = (e_ - sl) / e_ * 100
        if not (4.0 < dist <= 12.0):
            continue
        sig.append((int(tt[i]), s, int(yr[i]), ex_tp1r(i, H, L, C, sl), cnt[("BOS", False, True)], int(hr[i])))

print(f"сырых сигналов (WT<−60 + ATRTrend↑ + стоп 4-12%, ликвидная половина): {len(sig)}")

# 🔴 КУЛДАУН МОНЕТЫ 6ч — как в бою (`cooldown_h: 6` + `_last_fire_sym`).
# Без него бэктест считает ОДНУ дислокацию несколько раз (условие WT<−60 держится
# несколько баров подряд) и завышает частоту. Живой луп так не делает.
COOL_MS = 6 * 3600 * 1000
sig.sort()
last_fire = {}
sig_cd = []
for x in sig:
    t, s = x[0], x[1]
    if t - last_fire.get(s, -10**18) < COOL_MS:
        continue
    last_fire[s] = t
    sig_cd.append(x)
print(f"после кулдауна монеты 6ч (как в бою): {len(sig_cd)} "
      f"— отсеяно {len(sig)-len(sig_cd)} повторов той же дислокации\n")
sig = sig_cd

# кластер: сколько РАЗНЫХ монет дали сигнал на одном баре
by_bar = defaultdict(set)
for t, s, *_ in sig:
    by_bar[t].add(s)

n_liq = max(1, len(liq))


def rep(name, rows):
    """Печатает КАЧЕСТВО и ЧАСТОТУ вместе — цель = частота × медиана."""
    if len(rows) < 30:
        print(f"  {name:<34} n={len(rows):<5} — мало")
        return
    r = np.array([x[3] for x in rows]) - COST
    srt = np.sort(r); cut = max(1, len(r) // 10)
    med = float(np.median(r))
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted({x[1] for x in rows})
    pos = sum(1 for cn in coins if np.median([x[3] - COST for x in rows if x[1] == cn]) > 0)
    per_month = len(r) / months                 # сделок в месяц НА ВСЮ вселенную
    per_coin = per_month / n_liq                # на монету
    pct_month = per_month * med                 # 🔑 ЦЕЛЬ: частота × медиана
    # рой (4/6): «частота × медиана» не учитывает риск. Добавляем Шарп-подобную оценку:
    # среднее/разброс на сделку, нормированное на частоту → сопоставимо между режимами.
    sharpe = (r.mean() / r.std() * np.sqrt(per_month)) if r.std() > 0 else 0.0
    years = sorted({x[2] for x in rows})
    ys = {y: [x[3] - COST for x in rows if x[2] == y] for y in years}
    fy = lambda a: f"{np.median(a):+.2f}" if len(a) > 15 else "  ?  "
    ystr = " ".join(f"{y%100}:{fy(ys[y])}" for y in years)
    print(f"  {name:<34} n={len(r):<5} WR{100*(r>0).mean():3.0f}% МЕД{med:+6.2f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+8.0f}% монет+{pos:2}/{len(coins):<3} "
          f"| сд/мес {per_month:6.1f} → **{pct_month:+7.1f}%/мес** Sh{sharpe:5.2f} | {ystr}")


print("═══ ПОСЛЕДОВАТЕЛЬНОЕ НАЛОЖЕНИЕ БОЕВЫХ ГЕЙТОВ ═══")
print("   Каждый гейт калиброван ОТДЕЛЬНО. Смотрим, что делает их ПРОИЗВЕДЕНИЕ.\n")

base = sig
rep("0. база (без гейтов)", base)

g_bos = [x for x in base if x[4] >= 1]
rep("1. +BOS≥1", g_bos)

g_ses = [x for x in g_bos if x[5] not in BAD_HOURS]
rep("2. +сессия (вне 08-21 UTC)", g_ses)

g_clu = [x for x in g_ses if len(by_bar[x[0]]) >= 2]
rep("3. +кластер≥2 (по СЫРЫМ, как мерили)", g_clu)

# 🔴 БОЕВОЕ определение: в rangefade_loop кандидат попадает в cand[src] ПОСЛЕ всех
# фильтров, и кластер ищется среди УЖЕ ОТФИЛЬТРОВАННЫХ. Это другое множество.
by_bar_f = defaultdict(set)
for x in g_ses:
    by_bar_f[x[0]].add(x[1])
g_clu_live = [x for x in g_ses if len(by_bar_f[x[0]]) >= 2]
rep("3'. +кластер≥2 ПО-БОЕВОМУ", g_clu_live)
print(f"      сырое определение оставляет {len(g_clu)} из {len(g_ses)} "
      f"({100*len(g_clu)/max(1,len(g_ses)):.0f}%), боевое — {len(g_clu_live)} "
      f"({100*len(g_clu_live)/max(1,len(g_ses)):.0f}%)")

print("\n═══ ВКЛАД КАЖДОГО ГЕЙТА ПО ОТДЕЛЬНОСТИ (от базы) ═══")
rep("только BOS≥1", g_bos)
rep("только сессия", [x for x in base if x[5] not in BAD_HOURS])
rep("только кластер≥2", [x for x in base if len(by_bar[x[0]]) >= 2])

print("\n═══ ЧТО ЕСЛИ ОСЛАБИТЬ КЛАСТЕР (проверка, а не рекомендация) ═══")
for k in (2, 3):
    rep(f"стопка, кластер≥{k}", [x for x in g_ses if len(by_bar[x[0]]) >= k])
rep("стопка БЕЗ кластера", g_ses)

print("\n═══ ЕСТЬ ЛИ ЗАЛИВЫ: доля кластерных сигналов ПО ГОДАМ ═══")
print("   Живой бот за 2 недели августа дал 143 одиночки и 1 кластер (0.7%).")
print("   Если в бэктесте доля кластеров падает к 2026 — заливов стало меньше, гейт ни при чём.\n")
for y in sorted({x[2] for x in sig}):
    ys_ = [x for x in sig if x[2] == y]
    if not ys_:
        continue
    clus = sum(1 for x in ys_ if len(by_bar[x[0]]) >= 2)
    bars = len({x[0] for x in ys_})
    print(f"  {y}  сигналов {len(ys_):5}  на {bars:5} разных барах  "
          f"в кластерах {clus:5} ({100*clus/len(ys_):5.1f}%)  "
          f"среднее монет на баре {len(ys_)/max(1,bars):.2f}")

print("\n═══ ПОДГОНКА ИЛИ СМЕНА РЕЖИМА: сессия по ГОДАМ × ЧАСАМ (на базе +BOS≥1) ═══")
print("   Если запрещённое окно 08-21 в 2026 перестало быть плохим — гейт УСТАРЕЛ,")
print("   а не подогнан. Если оно плохое всегда, а хорошее окно просто ослабло — режим.\n")
print(f"  {'год':<6} {'окно 08-21 (ЗАПРЕЩЕНО)':<34} {'окно 21-08 (РАЗРЕШЕНО)':<34} Δмед")
for y in sorted({x[2] for x in sig}):
    bad = [x[3] - COST for x in g_bos if x[2] == y and x[5] in BAD_HOURS]
    good = [x[3] - COST for x in g_bos if x[2] == y and x[5] not in BAD_HOURS]
    if len(bad) < 15 or len(good) < 15:
        print(f"  {y:<6} n_bad={len(bad)} n_good={len(good)} — мало")
        continue
    mb, mg = float(np.median(bad)), float(np.median(good))
    print(f"  {y:<6} n={len(bad):<4} МЕД{mb:+6.2f}% WR{100*np.mean(np.array(bad)>0):3.0f}%      "
          f"n={len(good):<4} МЕД{mg:+6.2f}% WR{100*np.mean(np.array(good)>0):3.0f}%      {mg-mb:+6.2f}")
print("\n  Δмед = насколько разрешённое окно ЛУЧШЕ запрещённого. Гейт оправдан, пока Δ>0 во ВСЕ годы.")

print("\n═══ ПОМЕСЯЧНО: не держится ли выигрыш сессии на 1-2 месяцах? ═══")
mon = defaultdict(lambda: [[], []])
for x in g_bos:
    key = pd.Timestamp(x[0], unit="ms").strftime("%Y-%m")
    mon[key][0 if x[5] in BAD_HOURS else 1].append(x[3] - COST)
wins = 0; tot = 0
for k in sorted(mon):
    b, g = mon[k]
    if len(b) < 8 or len(g) < 8:
        continue
    d = float(np.median(g)) - float(np.median(b))
    tot += 1; wins += (d > 0)
    print(f"  {k}  Δмед={d:+6.2f}  (n_bad={len(b):3} n_good={len(g):3})")
if tot:
    print(f"\n  Сессия помогала в {wins} из {tot} месяцев ({100*wins/tot:.0f}%). "
          f"{'Устойчиво.' if wins/tot > 0.6 else 'НЕустойчиво — держится на отдельных месяцах.'}")

print("\nНЕ проверено: funding-сайзинг ×1.5, гибрид-выход (две ноги), max_open/капы, "
      "проскальзывание и лимитное исполнение; вселенная = кэш Binance, не BingX.")
