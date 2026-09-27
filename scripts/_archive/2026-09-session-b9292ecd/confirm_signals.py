# -*- coding: utf-8 -*-
"""ПРИЗНАКИ ПОДТВЕРЖДЕНИЯ РАЗВОРОТА ПО СЛОЯМ (запрос Егора 09.09.2026).

OB · FVG · iFVG (overlap) · breaker · снятая ликвидность (sweep) · объём · CHoCH · дивергенции.
Вопрос: подтверждают ли они разворот, и на каких ОКНАХ это работает.

Ставится на фоне уже найденного: разворот структуры платит только с окна ≥180 мин
(+0.61% → +3.23%), а на мелких окнах даёт ноль. Проверяем, ведут ли себя так же
признаки подтверждения — и добавляют ли они что-то ПОВЕРХ разворота.

🔴 Контроль обязателен: матч по монете и квинтилю ATR. Признаки срабатывают на движении,
а движение само даёт форвард.
"""
import os, sys, glob, json, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TFS = [30, 90, 240]          # окна, где разворот структуры работает
NSYM = 14
RNG = np.random.default_rng(20260909)

# (имя_bull, имя_bear, ярлык) — сторона задаёт ожидаемое направление
PAIRS = [
    ("bull_ob", "bear_ob", "OB свежий"),
    ("bull_ob_near", "bear_ob_near", "OB · цена в зоне"),
    ("bull_ob_mitigated", "bear_ob_mitigated", "OB отработан"),
    ("bull_breaker", "bear_breaker", "breaker"),
    ("bull_fvg", "bear_fvg", "FVG свежий"),
    ("bull_fvg_in", "bear_fvg_in", "FVG · цена внутри"),
    ("bull_fvg_overlap", "bear_fvg_overlap", "FVG overlap (iFVG)"),
    ("bull_fvg_overlap_held", "bear_fvg_overlap_held", "FVG overlap удержан"),
    ("eql_sweep", "eqh_sweep", "снятие EQL/EQH"),
    ("liq_sweep_dn", "liq_sweep_up", "снятие ликвидности"),
    ("bull_choch", "bear_choch", "CHoCH swing"),
    ("bull_choch_i", "bear_choch_i", "CHoCH internal"),
    ("bull_bos", "bear_bos", "BOS swing"),
    ("wt_div_bull_regular", "wt_div_bear_regular", "WT дивергенция"),
    ("rsi_div_bull_regular", "rsi_div_bear_regular", "RSI дивергенция"),
    ("bull_mom", "bear_mom", "моментум"),
    ("ote_long", "ote_short", "OTE зона"),
]
NEUTRAL = ["vol_spike", "atr_vol_high", "liq_void_bull", "inducement_bull"]
FWD = {"1x": 1, "3x": 3}      # горизонт в ОКНАХ слоя (окно = 10 баров ТФ)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last(),
                         "volume": r["volume"].sum()}).dropna()


from core.calculators.combinator_core import compute_flags

rows = []
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} | слои: {TFS} мин\n", flush=True)
store = {tf: [] for tf in TFS}
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    for tf in TFS:
        d = resample(d1, tf)
        d.index.name = "ts"
        try:
            fl = compute_flags(d, label="x")
        except Exception as e:
            print(f"  {sym} {tf}m: {type(e).__name__}: {e}", flush=True); continue
        fl.columns = [c[:-2] if c.endswith("_x") else c for c in fl.columns]
        c = d["close"].values
        atr = ((d["high"] - d["low"]) / d["close"]).rolling(200, min_periods=50).mean().values
        n = len(d)
        fwd = {}
        for nm, mult in FWD.items():
            h = int(mult * 10)                      # окно слоя = 10 баров
            v = np.full(n, np.nan)
            v[:-h] = (c[h:] - c[:-h]) / c[:-h] * 100
            fwd[nm] = v
        store[tf].append((sym, fl, fwd, atr))
    print(f"[{fi}/{len(files)}] {sym}", flush=True)


pool_cache = {}
for tf in TFS:
    for sym, fl, fwd, atr in store[tf]:
        v = fwd["1x"]
        ok = ~np.isnan(atr) & ~np.isnan(v)
        q = np.zeros(len(atr), np.int8)
        if ok.sum() > 100:
            q[ok] = np.digitize(atr[ok], np.nanpercentile(atr[ok], [20, 40, 60, 80]))
        pool_cache[(sym, tf)] = {int(b): np.where(ok & (q == b))[0] for b in range(5)}
print(f"пулов контроля: {len(pool_cache)}", flush=True)


def qbin(a):
    ok = ~np.isnan(a)
    q = np.zeros(len(a), np.int8)
    if ok.sum() > 100:
        q[ok] = np.digitize(a[ok], np.nanpercentile(a[ok], [20, 40, 60, 80]))
    return q


print("\n=== ПОДТВЕРЖДЕНИЕ РАЗВОРОТА: форвард 1 окно слоя, минус контроль по ATR ===")
print(f"{'признак':>22} {'окно':>6} {'n bull':>8} {'bull−ctl':>9} "
      f"{'n bear':>8} {'bear−ctl':>9} {'сумма':>8} {'мон+':>6}")
res = []
for bull, bear, lbl in PAIRS:
    for tf in TFS:
        agg = {}
        for side, col in [(1, bull), (-1, bear)]:
            tot_n, diffs, per_sym = 0, [], []
            for sym, fl, fwd, atr in store[tf]:
                if col not in fl.columns:
                    continue
                m = fl[col].values.astype(bool)
                v = fwd["1x"]
                q = qbin(atr)
                sel = m & ~np.isnan(v)
                if sel.sum() < 30:
                    continue
                ev = np.nanmean(v[sel]) * side
                # контроль: пулы по квинтилю ATR предвычислены один раз на монету
                pools = pool_cache.get((sym, tf))
                cs = []
                idx = np.where(sel)[0]
                for _ in range(3):
                    pick = np.empty(len(idx), np.int64)
                    bad = False
                    for j, i in enumerate(idx):
                        pl = pools.get(int(q[i]))
                        if pl is None or len(pl) == 0:
                            bad = True; break
                        pick[j] = pl[RNG.integers(len(pl))]
                    if bad:
                        continue
                    cs.append(np.nanmean(v[pick]) * side)
                if not cs:
                    continue
                d_ = ev - float(np.mean(cs))
                diffs.append(d_ * sel.sum()); tot_n += sel.sum(); per_sym.append(d_)
            if tot_n:
                agg[side] = (tot_n, sum(diffs) / tot_n,
                             sum(1 for x in per_sym if x > 0), len(per_sym))
        if 1 in agg and -1 in agg:
            nb, db, gb, tb = agg[1]; nr, dr, gr, tr = agg[-1]
            res.append((lbl, tf, nb, db, nr, dr, db + dr, gb + gr, tb + tr))
            print(f"{lbl:>22} {tf*10:>5}m {nb:>8,} {db:+8.4f}% {nr:>8,} {dr:+8.4f}% "
                  f"{db+dr:+7.4f}% {gb+gr:>3}/{tb+tr}")

print("\n=== ЛУЧШИЕ ПО СУММЕ ОБЕИХ СТОРОН ===")
for r in sorted(res, key=lambda r: -r[6])[:12]:
    print(f"  {r[0]:>22} окно {r[1]*10:>5} мин | bull {r[3]:+.4f}% (n={r[2]:,}) | "
          f"bear {r[5]:+.4f}% (n={r[4]:,}) | сумма {r[6]:+.4f}% | монет+ {r[7]}/{r[8]}")

json.dump([{"lbl": r[0], "win": r[1]*10, "nb": int(r[2]), "db": r[3],
            "nr": int(r[4]), "dr": r[5], "sum": r[6], "good": r[7], "tot": r[8]}
           for r in res], open(D + r"\confirm_signals.json", "w", encoding="utf-8"),
          ensure_ascii=False)
print("\nсохранено: confirm_signals.json")
