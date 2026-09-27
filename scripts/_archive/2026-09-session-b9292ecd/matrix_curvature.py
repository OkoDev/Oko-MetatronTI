# -*- coding: utf-8 -*-
"""МАТРИЦА ЧЕРЕЗ ГИПЕРКУБ: масштаб кривизны детекторов (постановка Егора 09.09.2026).

Замер ДИАГНОСТИЧЕСКИЙ, не поисковый: меряется свойство ПРИБОРА, а не рынка,
поэтому множественное тестирование здесь не работает против нас.

Эталон, измеренный сегодня на 30 000 пар слоёв: при R ≈ 1 структура совпадает
сама с собой на 95-97%, события структуры — на 66%. Признак, совпадающий с собой
заметно хуже, кривой.

Три метрики кривизны:
  A. ЧАСТОТНЫЙ ДРЕЙФ — фрактальный признак срабатывает одинаково часто В ЕДИНИЦАХ
     СВОЕГО ОКНА. Падение частоты с ростом окна = внутри абсолютная константа
     (порог в %, период в барах), которая между масштабами не переносится.
  B. САМОСОГЛАСОВАННОСТЬ — совпадает ли признак на слое k с собой же на слое k+1
     при R ≈ 1 (соседние ТФ лестницы). Сравнивать с эталоном 66%.
  C. ОХВАТ — на скольких слоях признак вообще жив (частота ≥ 0.05%). Признак,
     живущий на одном масштабе, в MTF-матрице бесполезен.
"""
import os, sys, glob, json, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

SRC = r"C:\oko_history\1m"
D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
# лестница слоёв: ТФ в минутах, шаг ≈ ×3
TFS = [3, 10, 30, 90, 240]
NSYM = 6


def resample(d1, tf):
    if tf == 1:
        return d1
    r = d1.resample(f"{tf}min", label="left", closed="left")
    o = pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                      "low": r["low"].min(), "close": r["close"].last(),
                      "volume": r["volume"].sum()}).dropna()
    return o


def load_flags(df, tf):
    from core.calculators.combinator_core import compute_flags
    d = df.copy()
    d.index.name = "ts"
    f = compute_flags(d, label=f"t{tf}")
    f.columns = [c.rsplit(f"_t{tf}", 1)[0] for c in f.columns]
    return f


files = sorted(glob.glob(SRC + r"\*.parquet"))[:NSYM]
print(f"монет: {len(files)} | слои (ТФ, мин): {TFS}", flush=True)

freq = {}        # feat -> {tf: частота}
agree = {}       # feat -> {tf: доля совпадения со следующим слоем}
kinds = {}
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    lay = {}
    for tf in TFS:
        d = resample(d1, tf)
        try:
            fl = load_flags(d, tf)
        except Exception as e:
            print(f"  {sym} {tf}m: ОШИБКА {type(e).__name__}: {e}", flush=True)
            continue
        lay[tf] = (d.index, fl)
        for c in fl.columns:
            v = fl[c]
            if v.dtype == bool or set(pd.unique(v.dropna())) <= {0, 1, True, False}:
                kinds[c] = "bool"
                freq.setdefault(c, {}).setdefault(tf, []).append(float(np.nanmean(v.values.astype(float))))
            else:
                kinds[c] = "num"
    # самосогласованность: слой k против слоя k+1 (булевы)
    for a, b in zip(TFS[:-1], TFS[1:]):
        if a not in lay or b not in lay:
            continue
        ia, fa = lay[a]; ib, fb = lay[b]
        j = np.searchsorted(ib.values, ia.values, "right") - 1     # каузально
        ok = j >= 0
        for c in fa.columns:
            if kinds.get(c) != "bool" or c not in fb.columns:
                continue
            va = fa[c].values.astype(bool)[ok]
            vb = fb[c].values.astype(bool)[j[ok]]
            if va.sum() < 30:
                continue
            agree.setdefault(c, {}).setdefault(a, []).append(float(vb[va].mean()))
    print(f"[{fi}/{len(files)}] {sym}: слоёв {len(lay)}, признаков {len(kinds)}", flush=True)

rows = []
for c in sorted(kinds):
    if kinds[c] != "bool":
        continue
    fr = {tf: float(np.mean(v)) for tf, v in freq.get(c, {}).items() if v}
    if len(fr) < 3:
        continue
    ag = {tf: float(np.mean(v)) for tf, v in agree.get(c, {}).items() if v}
    alive = sum(1 for v in fr.values() if v >= 0.0005)
    lo_tf, hi_tf = min(fr), max(fr)
    drift = (fr[hi_tf] + 1e-9) / (fr[lo_tf] + 1e-9)
    rows.append(dict(feat=c, alive=alive, nlayers=len(fr),
                     f_lo=fr[lo_tf], f_hi=fr[hi_tf], drift=drift,
                     agree=float(np.mean(list(ag.values()))) if ag else None,
                     freq={str(k): round(v, 5) for k, v in sorted(fr.items())}))

json.dump(dict(tfs=TFS, nsym=len(files), rows=rows),
          open(D + r"\matrix_curvature.json", "w", encoding="utf-8"), ensure_ascii=False)
print(f"\nбулевых признаков с ≥3 слоями: {len(rows)}\n")

print("=== A. ЧАСТОТНЫЙ ДРЕЙФ: во сколько раз частота на 240m против 3m ===")
print("   (фрактальный признак → около 1; сильное отклонение = абсолютная константа внутри)")
srt = sorted([r for r in rows if r["f_lo"] > 0.0002], key=lambda r: r["drift"])
print(f"\n  СХЛОПЫВАЮТСЯ с ростом окна (признак умирает на старших слоях):")
print(f"{'признак':>34} {'3m':>9} {'240m':>9} {'×':>8} {'жив на':>8}")
for r in srt[:14]:
    print(f"{r['feat']:>34} {r['f_lo']*100:8.3f}% {r['f_hi']*100:8.3f}% "
          f"{r['drift']:8.3f} {r['alive']:>4}/{r['nlayers']}")
print(f"\n  РАЗБУХАЮТ с ростом окна:")
for r in srt[-10:]:
    print(f"{r['feat']:>34} {r['f_lo']*100:8.3f}% {r['f_hi']*100:8.3f}% "
          f"{r['drift']:8.3f} {r['alive']:>4}/{r['nlayers']}")
print(f"\n  МАСШТАБНО УСТОЙЧИВЫЕ (0.7 < × < 1.4):")
st = [r for r in rows if 0.7 < r["drift"] < 1.4 and r["f_lo"] > 0.002]
for r in sorted(st, key=lambda r: -r["f_lo"])[:12]:
    print(f"{r['feat']:>34} {r['f_lo']*100:8.3f}% {r['f_hi']*100:8.3f}% "
          f"{r['drift']:8.3f} {r['alive']:>4}/{r['nlayers']}")

print("\n=== B. САМОСОГЛАСОВАННОСТЬ со СЛЕДУЮЩИМ слоем (эталон событий = 66%) ===")
ags = [r for r in rows if r["agree"] is not None and r["f_lo"] > 0.002]
ags.sort(key=lambda r: r["agree"])
print(f"\n  ХУЖЕ ВСЕГО переносятся через масштаб:")
print(f"{'признак':>34} {'совпало':>9} {'частота 3m':>12}")
for r in ags[:14]:
    print(f"{r['feat']:>34} {r['agree']*100:8.1f}% {r['f_lo']*100:11.3f}%")
print(f"\n  ЛУЧШЕ ВСЕГО:")
for r in ags[-10:]:
    print(f"{r['feat']:>34} {r['agree']*100:8.1f}% {r['f_lo']*100:11.3f}%")

print("\n=== D. ПО СЕМЬЯМ · SMC против остальных ===")
FAM = [("FVG", ("fvg",)), ("OB / breaker", ("ob_", "breaker")),
       ("структура BOS/CHoCH", ("bos", "choch")),
       ("ликвидность EQH/EQL", ("eqh", "eql", "liq")),
       ("OTE / premium", ("ote", "premium", "discount")),
       ("inducement / void", ("induc", "void")),
       ("swing HH/HL/LH/LL", ("hh", "hl", "lh", "ll", "swing")),
       ("Elliott", ("elliott",)),
       ("— WT", ("wt_",)), ("— RSI", ("rsi",)), ("— ATR", ("atr",)),
       ("— пивоты", ("piv", "pp_", "r1", "r2", "s1", "s2"))]


def fam_of(name):
    n = name.lower()
    for lbl, pref in FAM:
        if any(n.startswith(p) or ("_" + p) in n for p in pref):
            return lbl
    return "прочее"


print(f"{'семья':>22} {'призн.':>7} {'дрейф мед':>10} {'совпад.':>9} "
      f"{'жив на всех':>12} {'схлопыв.':>9}")
fam_rows = {}
for r in rows:
    fam_rows.setdefault(fam_of(r["feat"]), []).append(r)
for lbl, _ in FAM + [("прочее", ())]:
    g = fam_rows.get(lbl, [])
    if not g:
        continue
    dr = np.median([r["drift"] for r in g])
    ag = [r["agree"] for r in g if r["agree"] is not None]
    full = sum(1 for r in g if r["alive"] == r["nlayers"])
    coll = sum(1 for r in g if r["drift"] < 0.34)
    print(f"{lbl:>22} {len(g):>7} {dr:>10.3f} "
          f"{(f'{np.mean(ag)*100:.1f}%' if ag else '—'):>9} "
          f"{full:>6}/{len(g):<5} {coll:>9}")

print("\n=== D2. SMC ПОШТУЧНО: где ломается (частота по слоям) ===")
smc_fams = {"FVG", "OB / breaker", "структура BOS/CHoCH", "ликвидность EQH/EQL",
            "OTE / premium", "inducement / void", "swing HH/HL/LH/LL", "Elliott"}
smc = [r for r in rows if fam_of(r["feat"]) in smc_fams]
smc.sort(key=lambda r: r["drift"])
print(f"  признаков SMC с ≥3 слоями: {len(smc)}")
print(f"{'признак':>32} {'дрейф':>8} {'совпад':>8}  частота по слоям")
for r in smc[:12] + smc[-8:]:
    ag = f"{r['agree']*100:.0f}%" if r["agree"] is not None else "—"
    print(f"{r['feat']:>32} {r['drift']:8.3f} {ag:>8}  "
          + " ".join(f"{k}m:{v*100:.2f}" for k, v in r["freq"].items()))

print("\n=== C. МЁРТВЫЕ НА СТАРШИХ СЛОЯХ (жив менее чем на половине) ===")
dead = [r for r in rows if r["alive"] < r["nlayers"] / 2 + 0.5]
print(f"  таких: {len(dead)} из {len(rows)}")
for r in sorted(dead, key=lambda r: r["alive"])[:16]:
    print(f"   {r['feat']:>32} жив {r['alive']}/{r['nlayers']} | "
          + " ".join(f"{k}m:{v*100:.2f}%" for k, v in r["freq"].items()))
print("\nсохранено: matrix_curvature.json")
