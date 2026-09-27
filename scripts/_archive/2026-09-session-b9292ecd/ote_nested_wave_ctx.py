"""ote_nested + «прозрение» двухслойным волновым детектором (Егор 22.09: «ote_nested даёт поток, но слеп… дать ему
что-то для прозрения? двухслойный волновой детектор? только какие ТФ?»). Берём 10 261 сделку реплея ote_nested «как в бою»
(G:/oko_lab/out/ote_nested_replay) и для КАЖДОГО ТФ ядра (1h / 4h / 1d, импульсы из wave_phase_ctx) смотрим: вход в сторону
разворота после завершённой пятёрки / по импульсу / без импульса; качество (core_full/core/пятёрка); свежесть. Окна:
1h — 48 ч, 4h — 10 дн, 1d — 30 дн. Контроли — из реплея. python ote_nested_wave_ctx.py"""
import glob, pickle
from pathlib import Path
import numpy as np, pandas as pd
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
P = [pickle.load(open(f, "rb")) for f in glob.glob("G:/oko_lab/out/ote_nested_replay/*USDT.pkl")]
T = pd.DataFrame([r for p in P for r in p["rows"] if r.get("filled")]); T["entry_t"] = pd.to_datetime(T.entry_t); T["год"] = T.entry_t.dt.year
print("сделок ote_nested:", len(T), "монет", T.sym.nunique())
WIN = {"1h": 48, "4h": 240, "1d": 720}; TF_H = {"1h": 1, "4h": 4, "1d": 24}
for tf in ("1h", "4h", "1d"):
    d = Path("G:/oko_lab/out/wave_phase_ctx") / ("" if tf == "4h" else tf)
    S = {Path(f).stem: pickle.load(open(f, "rb")) for f in glob.glob(str(d / "*USDT.pkl"))}
    rel, q, fresh = [], [], []
    for r in T.itertuples():
        s = S.get(r.sym)
        if s is None or len(s) == 0:
            rel.append("нет импульса"); q.append("—"); fresh.append("—"); continue
        s = s.sort_values("tt"); st = s.time.values
        t_close = np.datetime64(r.entry_t) - np.timedelta64(TF_H[tf], "h")
        k = int(np.searchsorted(st, t_close, "right")) - 1
        if k < 0 or (np.datetime64(r.entry_t) - st[k]) > np.timedelta64(WIN[tf], "h"):
            rel.append("нет импульса"); q.append("—"); fresh.append("—"); continue
        x = s.iloc[k]
        rel.append("разворот после пятой" if r.side == x.side else "по импульсу")
        q.append("core_full" if x.core_full else ("core" if x.core else "пятёрка"))
        age = (pd.Timestamp(r.entry_t) - pd.Timestamp(x.top_time)).total_seconds() / 3600
        fresh.append("свежий" if age < 2 * TF_H[tf] * 6 else "старый")
    T[f"rel_{tf}"] = rel; T[f"q_{tf}"] = q; T[f"fresh_{tf}"] = fresh
T.to_pickle("G:/oko_lab/out/ote_nested_replay/trades_wave_ctx.pkl")
def agg(g):
    return g.agg(n=("pnl", "size"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"), мед=("pnl", "median"),
                 ctl_r=("ctl_rand", "mean"), ctl_t=("ctl_time", "mean"), сумма=("pnl", "sum")).assign(Δr=lambda x: (x["ср"] - x.ctl_r).round(2), Δt=lambda x: (x["ср"] - x.ctl_t).round(2)).round(2)
print("\n=== БАЗА"); print(agg(T.groupby("side")).to_string())
for tf in ("1h", "4h", "1d"):
    print(f"\n################ ТФ ядра {tf}: сторона × отношение к последней пятёрке"); print(agg(T.groupby(["side", f"rel_{tf}"])).to_string())
    print(f"--- {tf}: × качество (n≥30)"); g = agg(T[T[f"rel_{tf}"] != "нет импульса"].groupby(["side", f"rel_{tf}", f"q_{tf}"])); print(g[g.n >= 30].to_string())
    print(f"--- {tf}: разворот после пятой × свежесть"); print(agg(T[T[f"rel_{tf}"] == "разворот после пятой"].groupby(["side", f"fresh_{tf}"])).to_string())
    print(f"--- {tf}: разворот после пятой × год"); z = T[T[f"rel_{tf}"] == "разворот после пятой"]; print(z.groupby(["side", "год"]).pnl.agg(["size", "mean"]).round(2).unstack("год").to_string())
print("\n=== КОМБИНАЦИИ: разворот после пятой хотя бы на одном ТФ / на двух / ни на одном")
T["n_rev"] = sum((T[f"rel_{tf}"] == "разворот после пятой").astype(int) for tf in ("1h", "4h", "1d"))
T["n_cont"] = sum((T[f"rel_{tf}"] == "по импульсу").astype(int) for tf in ("1h", "4h", "1d"))
print(agg(T.groupby(["side", "n_rev"])).to_string()); print(agg(T.groupby(["side", "n_cont"])).to_string())
print("\n=== ПРАВИЛО: торговать ote_nested только при развороте после пятой (любой ТФ) и без «по импульсу» — по годам")
z = T[(T.n_rev >= 1) & (T.n_cont == 0)]; print(agg(z.groupby(["side"])).to_string()); print(z.groupby(["side", "год"]).pnl.agg(["size", "mean"]).round(2).unstack("год").to_string())
for s_, zz in z.groupby("side"):
    top = zz.pnl.nlargest(max(1, int(len(zz) * 0.1))).sum(); print(f"  хрупкость {s_}: n {len(zz)} · сумма {zz.pnl.sum():.0f} · без топ-10% {zz.pnl.sum() - top:.0f} · монет+ {(zz.groupby('sym').pnl.sum() > 0).mean() * 100:.0f}%")
