# -*- coding: utf-8 -*-
"""🔴 СУРРОГАТНЫЙ ТЕСТ (IAAFT) — есть ли в находках хоть что-то, кроме спектра ряда (11.09.2026).

Требование пришло от независимого субагента и совпало с нашим протоколом вердикта:
«прогнать ВЕСЬ пайплайн на фазово-рандомизированном ряде, сохраняющем спектр и распределение.
Пайплайн всё равно выдаст лучшую ячейку с убедительной историей. Эффект на реальных данных
должен превысить 95-й перцентиль суррогатного распределения. Без этого вердикта нет».

КАК СТРОИТСЯ СУРРОГАТ (честно):
  · берётся БАЗОВЫЙ 1m ряд лог-доходностей монеты;
  · IAAFT: итеративно накладываются исходный амплитудный спектр и исходное распределение
    амплитуд, фазы рандомизированы ⇒ сохранены автокорреляция, суточная сезонность, дрейф
    и форма распределения; разрушена нелинейная структура (тренды, уровни, память режима);
  · цена восстанавливается кумулятивно, ВСЯ ЛЕСТНИЦА строится из неё ресемплингом —
    так же, как в реальном прогоне.

🔴 ЧЕСТНОСТЬ СРАВНЕНИЯ: в РЕАЛЬНОЙ ветке OHLC старших ТФ тоже собирается из 1m CLOSE
(O=H=L=C на 1m), иначе реальные high/low несли бы внутриминутные экстремумы, которых у
суррогата нет по построению. Обе ветки идентичны по конструкции.

МЕТРИКИ «НАХОДКИ» (пайплайн выбирает лучшее — как делали мы всю сессию):
  M1  лучшая ячейка (k × сторона) по превышению над базой той же серии
  M2  |наклон| регрессии нетто на число согласных слоёв k — «градиент по согласию»
  M3  лучшая ячейка по безтоп10% (наш критерий устойчивости)
Каждая метрика на реальных данных сравнивается с распределением тех же метрик по суррогатам.
"""
import os, sys, glob, bisect, warnings, time
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
LADDER = [5, 15, 60, 240]
TF_CTX, TF_IN, MA_LEN = 60, 15, 43
OS_, OB_, LIFE, TIMEOUT, COST = -60.0, 60.0, 12, 300, 0.35
NSYM, NSUR, IAAFT_IT = 20, 25, 12
RNG = np.random.default_rng(20260911)
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет {len(files)} · суррогатов {NSUR} · лестница {LADDER} · "
      f"IAAFT итераций {IAAFT_IT}\n", flush=True)


def iaaft(x, iters=IAAFT_IT, rng=RNG):
    """Iterative Amplitude Adjusted Fourier Transform: сохраняет спектр И распределение."""
    n = len(x)
    xs = np.sort(x)
    amp = np.abs(np.fft.rfft(x))
    y = rng.permutation(x)
    for _ in range(iters):
        Y = np.fft.rfft(y)
        ang = np.angle(Y)
        y = np.fft.irfft(amp * np.exp(1j * ang), n)
        y = xs[np.argsort(np.argsort(y))]
    return y


def bars_from_close(close_1m, index_1m, tf):
    """OHLC из 1m CLOSE — одинаково для реальной и суррогатной ветки."""
    s = pd.Series(close_1m, index=index_1m)
    r = s.resample(f"{tf}min", label="left", closed="left")
    d = pd.DataFrame({"open": r.first(), "high": r.max(), "low": r.min(),
                      "close": r.last()}).dropna()
    return d


def run_pipeline(close_1m, index_1m):
    """Тот же пайплайн, что мы гоняли: контекст-зона на 1h → вход по медиане на 15m →
    выход в противоположной зоне; ось анализа — число согласных слоёв лестницы."""
    L = {}
    for tf in LADDER:
        dd = bars_from_close(close_1m, index_1m, tf)
        if len(dd) < 600:
            return None
        w = calculate_wt(dd.reset_index(drop=True))
        w1, w2 = w["wt1"].values, w["wt2"].values
        n_ = len(w1)
        cu = np.zeros(n_, bool); cd = np.zeros(n_, bool)
        cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
        cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
        ma = pd.Series(w1).ewm(span=MA_LEN, adjust=False).mean().to_numpy()
        L[tf] = dict(above=w1 > ma,
                     arrow_up=cu & (w1 < OS_), arrow_dn=cd & (w1 > OB_),
                     up=np.concatenate(([False], (w1[:-1] <= ma[:-1]) & (w1[1:] > ma[1:]))),
                     dn=np.concatenate(([False], (w1[:-1] >= ma[:-1]) & (w1[1:] < ma[1:]))),
                     touch_up=w1 >= OB_, touch_dn=w1 <= OS_,
                     ct=(dd.index + pd.Timedelta(minutes=tf)).values,
                     cl=dd.close.values, op=dd.open.values)
    I_, C_ = L[TF_IN], L[TF_CTX]
    n = len(I_["cl"])
    agree_up = np.zeros(n, np.int16)
    for tf in LADDER:
        j = np.clip(np.searchsorted(L[tf]["ct"], I_["ct"], "right") - 1,
                    0, len(L[tf]["above"]) - 1)
        agree_up += L[tf]["above"][j].astype(np.int16)
    nlad = len(LADDER)

    def exit_at(ii, side):
        zone = I_["touch_up"] if side == 1 else I_["touch_dn"]
        lim = min(ii + TIMEOUT, n - 1)
        j = np.where(zone[ii + 1:lim + 1])[0]
        return (ii + 1 + int(j[0])) if len(j) else lim

    ctx = []
    for arr, sd in ((C_["arrow_up"], 1), (C_["arrow_dn"], -1)):
        for k in np.where(arr)[0]:
            if k + LIFE < len(C_["ct"]):
                ctx.append((C_["ct"][k], C_["ct"][k + LIFE], sd))
    if not ctx:
        return None
    ctx.sort(); st = [x[0] for x in ctx]
    out = []
    busy = {1: -1, -1: -1}
    for i in range(max(120, MA_LEN + 5), n - 5):
        for sig, side in ((I_["up"][i], 1), (I_["dn"][i], -1)):
            if not sig:
                continue
            t_now = I_["ct"][i]
            q = bisect.bisect_right(st, t_now) - 1
            if not any(ctx[z][2] == side and ctx[z][0] <= t_now <= ctx[z][1]
                       for z in range(max(0, q - 4), q + 1) if 0 <= z < len(ctx)):
                continue
            ii = i + 1
            if ii >= n - 3 or ii <= busy[side]:
                continue
            jx = exit_at(ii, side)
            busy[side] = jx
            e = I_["op"][ii]
            ag = int(agree_up[i] if side == 1 else nlad - agree_up[i])
            out.append((side, ag, (I_["cl"][jx] - e) / e * 100 * side - COST))
    # контроль-база той же геометрии
    base = []
    for side in (1, -1):
        for ii in range(120, n - 4, 60):
            jx = exit_at(ii, side)
            e = I_["op"][ii]
            base.append((side, (I_["cl"][jx] - e) / e * 100 * side - COST))
    return out, base


def metrics(rows, base):
    """M1 лучшая ячейка над базой · M2 |наклон| по k · M3 лучший безтоп10%."""
    R = pd.DataFrame(rows, columns=["side", "k", "pnl"])
    B = pd.DataFrame(base, columns=["side", "pnl"])
    bm = B.groupby("side").pnl.mean()
    m1, m3, slopes = -9e9, -9e9, []
    for side in (1, -1):
        g0 = R[R.side == side]
        if len(g0) < 200:
            continue
        b = float(bm.get(side, np.nan))
        xs, ys = [], []
        for k in sorted(g0.k.unique()):
            g = g0[g0.k == k]
            if len(g) < 80:
                continue
            m1 = max(m1, g.pnl.mean() - b)
            v = np.sort(g.pnl.values)[::-1]
            m3 = max(m3, v[int(len(v) * .1):].mean())
            xs.append(k); ys.append(g.pnl.mean())
        if len(xs) >= 3:
            slopes.append(abs(np.polyfit(xs, ys, 1)[0]))
    return m1, (max(slopes) if slopes else 0.0), m3


# ── данные в память один раз
data = []
for f in files:
    d = pd.read_parquet(f)
    if len(d) < 200000:
        continue
    c = d["close"].to_numpy(float)
    data.append((os.path.basename(f)[:-8], c, d.index))
print(f"загружено {len(data)} монет\n", flush=True)

t0 = time.time()
real_rows, real_base = [], []
for sym, c, idx in data:
    r = run_pipeline(c, idx)
    if r:
        real_rows += r[0]; real_base += r[1]
R1, R2, R3 = metrics(real_rows, real_base)
print(f"РЕАЛЬНЫЕ ДАННЫЕ ({time.time()-t0:.0f}с): сделок {len(real_rows):,}")
print(f"  M1 лучшая ячейка над базой : {R1:+.3f} п.п.")
print(f"  M2 |наклон| по k           : {R2:.4f} п.п./слой")
print(f"  M3 лучший безтоп10%        : {R3:+.3f}%\n", flush=True)

S1, S2, S3 = [], [], []
for s in range(NSUR):
    ts = time.time()
    rows, base = [], []
    for sym, c, idx in data:
        lr = np.diff(np.log(c))
        sur = iaaft(lr)
        cs = np.empty(len(c)); cs[0] = c[0]
        cs[1:] = c[0] * np.exp(np.cumsum(sur))
        r = run_pipeline(cs, idx)
        if r:
            rows += r[0]; base += r[1]
    if len(rows) < 500:
        print(f"  суррогат {s+1}: мало сделок ({len(rows)}), пропуск", flush=True)
        continue
    a, b, cc = metrics(rows, base)
    S1.append(a); S2.append(b); S3.append(cc)
    print(f"  суррогат {s+1:>2}/{NSUR} ({time.time()-ts:.0f}с): сделок {len(rows):,} · "
          f"M1 {a:+.3f} · M2 {b:.4f} · M3 {cc:+.3f}", flush=True)

np.savez(D + r"\surrogate_iaaft.npz", real=[R1, R2, R3],
         S1=np.array(S1), S2=np.array(S2), S3=np.array(S3))

print("\n" + "=" * 78)
print("=== ВЕРДИКТ: РЕАЛЬНОЕ ПРОТИВ СУРРОГАТНОГО РАСПРЕДЕЛЕНИЯ ===")
print("=" * 78)
NAMES = ["M1 лучшая ячейка над базой", "M2 |наклон| по числу согласных слоёв",
         "M3 лучший безтоп10%"]
for nm, real, sur in zip(NAMES, [R1, R2, R3], [S1, S2, S3]):
    if not sur:
        continue
    a = np.array(sur)
    pct = (a < real).mean() * 100
    p95 = np.percentile(a, 95)
    verdict = "✅ БЬЁТ суррогат" if real > p95 else "🔴 НЕ БЬЁТ — в пределах спектра ряда"
    print(f"\n{nm}")
    print(f"  реальное      : {real:+.4f}")
    print(f"  суррогаты     : медиана {np.median(a):+.4f} · среднее {a.mean():+.4f} · "
          f"σ {a.std():.4f}")
    print(f"  диапазон      : [{a.min():+.4f} … {a.max():+.4f}]  (n={len(a)})")
    print(f"  95-й перцентиль: {p95:+.4f}")
    print(f"  перцентиль реального: {pct:.1f}%   →  {verdict}")
