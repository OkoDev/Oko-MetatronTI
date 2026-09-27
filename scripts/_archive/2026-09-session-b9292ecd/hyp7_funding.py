# -*- coding: utf-8 -*-
"""HYP-7: ФАНДИНГ КАК ОСЬ — первые данные НЕ из производных цены (10.09.2026).

Весь гиперкуб построен из преобразований одного ценового ряда, и потолок информации
там измерен: 0.0055 бит, точность 55.6% против необходимых 62.9%. Фандинг — другой
класс данных: прямая мера ПЕРЕКОСА позиционирования (кто кому платит).

Положительный фандинг = лонги платят шортам = перекос в лонги = их ликвидации ниже.
Гипотеза: экстремальный фандинг предсказывает движение ПРОТИВ перекоса.

Данные: funding_rates 1.56 млн записей, 450 символов, 2022-01…2026-06 (4.5 года —
вдвое шире окна куба, есть и бычьи, и медвежьи фазы).

🔴 Каузально: фандинг известен на момент выплаты, форвард считается ПОСЛЕ.
🔴 Зеркальность обязательна: экстремум вверх и вниз должны работать симметрично.
"""
import os, sys, sqlite3
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
DB = "ohlcv_cache.db"
FWD_H = [8, 24, 72]
RNG = np.random.default_rng(20260910)

cn = sqlite3.connect(DB)
fr = pd.read_sql("SELECT symbol, time, rate, interval_hours FROM funding_rates "
                 "ORDER BY symbol, time", cn)
fr["ts"] = pd.to_datetime(fr["time"], unit="ms", utc=True)
print(f"фандинг: {len(fr):,} записей · {fr.symbol.nunique()} символов · "
      f"{fr.ts.min():%Y-%m} → {fr.ts.max():%Y-%m}")
print(f"ставка: медиана {fr.rate.median()*100:.4f}% · "
      f"p1 {fr.rate.quantile(.01)*100:+.4f}% · p99 {fr.rate.quantile(.99)*100:+.4f}%\n")

rows = []
for sym, g in fr.groupby("symbol"):
    if len(g) < 500:
        continue
    px = pd.read_sql("SELECT time, close FROM ohlcv_cache WHERE symbol=? "
                     "AND timeframe='1h' ORDER BY time", cn, params=(sym,))
    if len(px) < 5000:
        continue
    px.index = pd.to_datetime(px["time"], unit="ms", utc=True)
    c = px["close"].values
    ti = px.index.values
    # перцентиль ставки внутри монеты — режимы фандинга сравнимы между монетами
    q = g["rate"].rank(pct=True).values
    idx = np.searchsorted(ti, g["ts"].values, "right") - 1
    ok = idx >= 0
    for k, (i0, r_, qq) in enumerate(zip(idx, g["rate"].values, q)):
        if i0 < 0 or i0 >= len(c) - max(FWD_H) - 1:
            continue
        rec = [sym, float(r_), float(qq), int(k >= len(g) // 2)]
        for h in FWD_H:
            rec.append((c[i0 + h] - c[i0]) / c[i0] * 100)
        rows.append(tuple(rec))
cn.close()

R = pd.DataFrame(rows, columns=["sym", "rate", "q", "half"] + [f"f{h}" for h in FWD_H])
R.to_pickle(D + r"\hyp7_funding.pkl")
print(f"наблюдений: {len(R):,} · монет: {R.sym.nunique()}\n")


def mi(x, y, nx, ny=2):
    m = (x >= 0) & (y >= 0)
    a, b = x[m], y[m]
    n = len(a)
    j = np.bincount(a * ny + b, minlength=nx * ny).reshape(nx, ny) / n
    px_ = j.sum(1, keepdims=True); py = j.sum(0, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = j * np.log2(j / (px_ * py))
    return float(np.nansum(t))


print("=== A. ИНФОРМАЦИЯ ФАНДИНГА (сравнение с потолком куба 0.0055 бит) ===")
print(f"{'горизонт':>9} {'корзин':>7} {'I, бит':>10} {'контроль':>10} {'сверх':>10} "
      f"{'экв. точность':>14}")
qb = np.digitize(R["q"].values, [.05, .20, .40, .60, .80, .95])
for h in FWD_H:
    y = (R[f"f{h}"].values > 0).astype(int)
    ok = ~np.isnan(R[f"f{h}"].values)
    yy = np.where(ok, y, -1)
    I = mi(qb, yy, 7)
    yp = yy.copy(); v = yp[ok]; RNG.shuffle(v); yp[ok] = v
    c_ = mi(qb, yp, 7)
    p = y[ok].mean()
    HY = -(p * np.log2(p) + (1 - p) * np.log2(1 - p))
    lo_, hi_ = .5, .99
    for _ in range(40):
        m_ = (lo_ + hi_) / 2
        Hm = -(m_ * np.log2(m_) + (1 - m_) * np.log2(1 - m_))
        if HY - Hm > I - c_:
            hi_ = m_
        else:
            lo_ = m_
    print(f"{h:>8}ч {7:>7} {I:10.5f} {c_:10.5f} {I-c_:+10.5f} "
          f"{(lo_+hi_)/2*100:13.2f}%")

print("\n=== B. ЭКСТРЕМУМЫ ФАНДИНГА → ЧТО ПОСЛЕ (зеркальность) ===")
print(f"{'перцентиль':>14} {'n':>9} " + " ".join(f"{h:>10}ч" for h in FWD_H)
      + f" {'мед 24ч':>10}")
for lo_q, hi_q, lbl in [(0.00, 0.05, "p0-5 (шорты)"), (0.05, 0.20, "p5-20"),
                        (0.20, 0.80, "середина"), (0.80, 0.95, "p80-95"),
                        (0.95, 1.01, "p95-100 (лонги)")]:
    m = (R.q >= lo_q) & (R.q < hi_q)
    if m.sum() < 2000:
        continue
    g = R[m]
    vals = " ".join(f"{g[f'f{h}'].mean():+10.3f}" for h in FWD_H)
    print(f"{lbl:>14} {m.sum():>9,} {vals} {g['f24'].median():+10.3f}")

print("\n=== C. ПОЛНЫЙ ПРОТОКОЛ ДЛЯ КРАЙНИХ (24ч) ===")
print(f"{'группа':>16} {'n':>9} {'ход':>9} {'мед':>9} {'IS':>9} {'OOS':>9} "
      f"{'перенос':>8} {'монет+':>9}")
for lo_q, hi_q, lbl, sgn in [(0.00, 0.05, "фандинг p<5", 1),
                             (0.95, 1.01, "фандинг p>95", -1)]:
    g = R[(R.q >= lo_q) & (R.q < hi_q)]
    if len(g) < 1000:
        continue
    v = g["f24"] * sgn
    i_, o_ = v[g.half == 0], v[g.half == 1]
    tag = "✓" if i_.mean() * o_.mean() > 0 and i_.mean() > 0 else "✗"
    per = g.assign(v=v).groupby("sym").v.mean()
    print(f"{lbl:>16} {len(g):>9,} {v.mean():+8.3f}% {v.median():+8.3f}% "
          f"{i_.mean():+8.3f}% {o_.mean():+8.3f}% {tag:>8} "
          f"{int((per>0).sum())}/{len(per)}")
print("\n  (знак: при отрицательном фандинге ставим LONG, при положительном SHORT —")
print("   то есть против перекоса позиционирования)")
