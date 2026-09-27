"""Ширина рыночного слива как НЕЗАВИСИМЫЙ от сетапов индикатор (не считаем сами пятёрки): доля монет базы, у которых
доходность за последние 72 ч (по закрытым 4h-барам к моменту детекции) ниже порога. Срез сделок v2 по ширине."""
import glob, contextlib, io, sys
import numpy as np, pandas as pd
sys.path.insert(0, ".")
import wave5_sm
from wave5_sm import load

rng = np.random.default_rng(11)
SIDE = sys.argv[1] if len(sys.argv) > 1 else "down"
syms = [s.strip() for s in open("base_syms.txt", encoding="utf-8") if s.strip()]
cl = {}
for s in syms:
    d = load(s, "4h")
    if len(d):
        cl[s] = d.close
C = pd.DataFrame(cl)
C.index = C.index + pd.Timedelta(hours=4)                     # индекс = время ЗАКРЫТИЯ бара
R72 = C / C.shift(18) - 1                                      # 18 баров = 72 ч
valid = R72.notna().sum(axis=1)
B = {thr: (R72 < thr).sum(axis=1) / valid.replace(0, np.nan) for thr in (-0.10, -0.20)}
f = pd.concat([pd.read_pickle(p) for p in sorted(glob.glob(f"v2_{SIDE}_*.pkl"))], ignore_index=True)
T = f[f.v != "__setup__"].copy(); S = f[f.v == "__setup__"]
# момент детекции: из строки сетапа нет tdet → берём день детекции + восстанавливаем по ts входа pkl нельзя; используем 'day' и ближайший 4h-close ≤ конца дня
# точнее: h5 (часы от пятой до входа) не даёт tdet. Берём ширину на последнем закрытом 4h-баре ДО начала дня детекции (консервативно, без будущего)
T["t_ref"] = pd.to_datetime(T.day).dt.tz_localize("UTC")
for thr, b in B.items():
    bb = b.dropna()
    idx = np.searchsorted(bb.index.values, T.t_ref.values, side="right") - 1
    T[f"br{int(-thr*100)}"] = np.where(idx >= 0, bb.values[np.clip(idx, 0, None)], np.nan)
print(f"=== {'ЛОНГ' if SIDE == 'down' else 'ШОРТ'} · ширина = доля монет базы с ходом за 72 ч ниже порога, на закрытии 4h до начала дня детекции")
for col in ("br10", "br20"):
    qs = T.drop_duplicates(["sym", "ts"])[col].quantile([.33, .66, .9]).values
    T["g"] = pd.cut(T[col], [-1, qs[0], qs[1], qs[2], 2], labels=[f"низ ≤{qs[0]:.2f}", f"сред ≤{qs[1]:.2f}", f"выс ≤{qs[2]:.2f}", f"топ-10% >{qs[2]:.2f}"])
    print(f"\n--- {col}")
    for v in ("CH · откат 0.5 · стоп 0.886", "noCH · откат 0.5 · стоп 0.886"):
        for sub, mask in (("все", T.v == v), ("ядро fc", (T.v == v) & T.fc)):
            for gname, g in T[mask].groupby("g", observed=True):
                dd = (g["Y0"] - g["ctlT Y0"]).dropna()
                if len(dd) < 10:
                    continue
                by = dd.groupby(g.loc[dd.index, "day"]).mean().values
                bs = [rng.choice(by, len(by)).mean() for _ in range(2000)]; lo, hi = np.percentile(bs, [5, 95])
                s_ = g.loc[dd.index, "Y0"]
                yrs = " ".join(f"{str(y)[2:]}:{x.mean():+.1f}/{len(x)}" for y, x in s_.groupby(g.loc[dd.index, "year"]))
                print(f"  {v[:22]:22} {sub:8} {gname:16} n={len(dd):3} сигн {s_.mean():+.2f} ктрВр {g.loc[dd.index, 'ctlT Y0'].mean():+.2f} ΔВр {dd.mean():+.2f} "
                      f"CI90 [{lo:+.2f};{hi:+.2f}] WR {(s_ > 0).mean()*100:.0f}% без топ10 {s_.sort_values(ascending=False).iloc[int(len(s_)*.1):].mean():+.2f} дн {len(by)} | {yrs}")
