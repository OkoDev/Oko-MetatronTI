# -*- coding: utf-8 -*-
"""СОКРАЩЕНИЕ СТОПА НА ШОРТ-КЛЕТКЕ: пивоты / ATRTrend / ордер-блоки (11.08.2026, Егор).

Егор: «MTF пивоты/WT/ATRTrend как подтверждение для входа и СОКРАЩЕНИЯ СТОПА + зоны
POB/Demand, ордер-блоки».

Две половины этой мысли РАЗНОГО качества:
· «подтверждение для ВХОДА» — провалилось 8 раз подряд (дивергенция 4h, гейт ATRChange,
  LTF-кросс в HTF-зоне, SMC-зона снизу, закрытие в верхних 30%, DivergenceDetector,
  триггер len5-CHoCH, бычий CHoCH PF 0.78). «Подтверждение = опоздание». 9-ю не делаем.
· «СОКРАЩЕНИЕ СТОПА» — НИКОГДА не проверялось. Другой вопрос: не КОГДА входить,
  а ГДЕ СТОЯТЬ. Здесь структура может дать реальное.

🔴 ЛОВУШКА, которую обходим: наш эдж требует стопа >6% ([[ote_short_size_law_beats_phase]]) —
мелкие сетапы мертвы, косты съедают цель. Если просто подтянуть стоп при TP=1R, ЦЕЛЬ сожмётся
вместе с ним и сетап провалится в мёртвую зону. Поэтому **цель ФИКСИРУЕМ на исходной**
(1R от origin-стопа), а двигаем только стоп. Тогда риск падает, размер цели сохраняется.

Кандидаты стопа (обязаны лежать МЕЖДУ ценой входа и origin — то есть быть ТУЖЕ):
  A) origin ×1.003          — база, как сейчас
  B) ближайший свинг-хай     — структурный пивот (свинги того же движка oko_sm_engine)
  C) линия ATRTrend(43,1.25) — то, за чем следит штатный TSL бота
  D) ближайший медвежий OB   — core/smc/order_blocks (detect_structure → detect_order_blocks)
Причинно: все детекторы считаются на окне ДО текущего бара."""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.oko_sm_engine import run_structure, pivot_points
from core.smc.impulse_assembly import assemble_impulse, ote_zone
from core.smc.structure import detect_structure
from core.smc.order_blocks import detect_order_blocks
DB = "ohlcv_cache.db"
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 60
MIN_STOP = 6.0
MONTHS = 31.0


def load(sym, tf, t0):
    c = sqlite3.connect(DB)
    df = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                     "AND timeframe=? AND time>=? ORDER BY time", c, params=(sym, tf, t0))
    c.close()
    return df.reset_index(drop=True)


def atrt_line(df, period=43, factor=1.25):
    h, l, c = df.high, df.low, df.close
    hl2 = ((h + l) / 2).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().values
    up = hl2 - factor * atr; dn = hl2 + factor * atr
    tu = up.copy(); td = dn.copy(); tr_ = np.ones(len(hl2)); line = up.copy()
    for i in range(1, len(hl2)):
        tu[i] = max(up[i], tu[i - 1]) if hl2[i - 1] > tu[i - 1] else up[i]
        td[i] = min(dn[i], td[i - 1]) if hl2[i - 1] < td[i - 1] else dn[i]
        tr_[i] = 1 if hl2[i] > td[i - 1] else (-1 if hl2[i] < tu[i - 1] else tr_[i - 1])
        line[i] = tu[i] if tr_[i] > 0 else td[i]
    return line


def sim_short(i, H, L, C, sl, tp, ttl=72):
    e = C[i]; end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if H[j] >= sl: return (e - sl) / e * 100
        if L[j] <= tp: return (e - tp) / e * 100
    return (e - C[end]) / e * 100


def rep(name, rows, cost=0.35, ncoins=60):
    if len(rows) < 25:
        print(f"    {name:32} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - cost
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - cost for x in rows if x[2] == cn]) > 0)
    y = lambda yy: [x[1] - cost for x in rows if x[0] == yy]
    fmt = lambda a: f"{np.median(a):+.2f}" if len(a) > 12 else "  ?  "
    rr = np.mean([x[3] for x in rows]) if len(rows[0]) > 3 else 0
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:32} n={len(r):4} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+7.0f}% монет+{pos:3}/{len(coins):3} стоп{rr:5.2f}% | "
          f"24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                                "AND time>=? GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?",
                                (t0, NCOIN)).fetchall()]
c.close()
print(f"монет {len(syms)} · ШОРТ-клетка (n_bos≥1, стоп>{MIN_STOP}%) · "
      f"ЦЕЛЬ ФИКСИРОВАНА, двигаем только стоп\n")
R = defaultdict(list)
nfound = defaultdict(int)
for si, sym in enumerate(syms):
    d4 = load(sym, "4h", t0); d1 = load(sym, "1h", t0)
    if len(d4) < 1200 or len(d1) < 5000:
        continue
    t4 = d4.time.values; t1 = d1.time.values
    H1 = d1.high.values; L1 = d1.low.values; C1 = d1.close.values
    yr1 = pd.to_datetime(d1.time, unit="ms").dt.year.values
    line1 = atrt_line(d1)
    seen = None
    for b in range(1050, len(d4) - 1, 6):
        win = d4.iloc[max(0, b - 1000):b + 1].reset_index(drop=True)
        try:
            st = run_structure(win, swing_len=50, internal_len=5)
        except Exception:
            continue
        imp = assemble_impulse(st, win["high"], win["low"], internal=True)
        if not imp or imp["n_bos"] < 1 or imp["is_long"]:
            continue
        key = (round(imp["origin"], 10), round(imp["extreme"], 10))
        if key == seen:
            continue
        z_lo, z_hi = ote_zone(imp["origin"], imp["extreme"], False)
        j0 = int(np.searchsorted(t1, t4[b])); j1 = min(j0 + 24, len(d1) - 2)
        for j in range(max(j0, 1), j1):
            px = C1[j]
            if not (z_lo <= px <= z_hi):
                continue
            sl_o = imp["origin"] * 1.003
            if sl_o <= px:
                break
            dist = (sl_o - px) / px * 100
            if not (MIN_STOP < dist < 25):
                break
            y = int(yr1[j])
            TP = px - (sl_o - px)          # ЦЕЛЬ ФИКСИРОВАНА на исходной 1R
            alts = {"A) origin (база)": sl_o}
            # B) ближайший свинг-хай между ценой и origin
            try:
                sw = [p for (_ci, _si, p, is_top) in pivot_points(win["high"], win["low"], 5) if is_top]
                cand = [p for p in sw if px * 1.002 < p < sl_o]
                if cand:
                    alts["B) свинг-хай (len5)"] = min(cand) * 1.003
            except Exception:
                pass
            # C) линия ATRTrend на 1h
            lv = line1[j]
            if not np.isnan(lv) and px * 1.002 < lv < sl_o:
                alts["C) линия ATRTrend"] = lv * 1.003
            # D) ближайший медвежий ордер-блок
            try:
                sa = detect_structure(win)
                ob = detect_order_blocks(win, sa)
                tops = [o.top for o in ob.active_bear if px * 1.002 < o.top < sl_o]
                if tops:
                    alts["D) ордер-блок (медв.)"] = min(tops) * 1.003
            except Exception:
                pass
            for nm, sl_a in alts.items():
                d_pct = (sl_a - px) / px * 100
                pnl = sim_short(j, H1, L1, C1, sl_a, TP)
                R[nm].append((y, pnl, sym, d_pct))
                nfound[nm] += 1
                if nm != "A) origin (база)":
                    R[f"{nm} · и база на тех же"].append(
                        (y, sim_short(j, H1, L1, C1, sl_o, TP), sym, dist))
            seen = key
            break
    if (si + 1) % 15 == 0:
        print(f"  ... {si+1}/{len(syms)}")
print(f"\nнайдено альтернатив: {dict(nfound)}")
print("\n═══ КОСТЫ 0.35% · цель зафиксирована, меняется только стоп ═══")
for nm in ("A) origin (база)", "B) свинг-хай (len5)", "C) линия ATRTrend", "D) ордер-блок (медв.)"):
    rep(nm, R.get(nm, []), ncoins=len(syms))
print("\n  ── честное сравнение: база НА ТЕХ ЖЕ сделках, где альтернатива нашлась ──")
for nm in ("B) свинг-хай (len5)", "C) линия ATRTrend", "D) ордер-блок (медв.)"):
    rep(f"{nm[:2]} база на тех же", R.get(f"{nm} · и база на тех же", []), ncoins=len(syms))
