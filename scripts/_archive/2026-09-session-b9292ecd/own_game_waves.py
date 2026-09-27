"""«СВОЯ ИГРА» КАК ВЕС ДЛЯ waves_long (план 19.09, п.3): единственный признак монеты, переживший OOS на пробоях уровней
(низкая корреляция к BTC за 30 дн + обгон BTC за 30 дн: WR 29 → 36%, минус в ноль). Проверяем там, где эдж уже есть —
сделки ядра волн 4h (tf_sweep, боевые правила, 2020-06→2026-09), обе стороны, контроли tf_sweep (ctl_4h.pkl).
Признаки монеты — каузально, на закрытом дне перед вершиной пятой: coin_corr30_btc, coin_beta30_btc, coin_ret30_vs_btc,
coin_vol30, оборот 30 дн. Пороги — только по IS (чётные монеты × ≤2023), OOS — нечётные × ≥2024, плюс полный срез по годам.
Запуск: python own_game_waves.py
"""
import sys, pickle, hashlib
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf
import tf_sweep as T

OUT = Path("G:/oko_lab/out/own_game_waves"); OUT.mkdir(parents=True, exist_ok=True)


def coin_daily(sym, btc):
    d = load_tf(sym, "1d")
    r = np.log(d.close).diff(); rb = np.log(btc.close).diff().reindex(r.index)
    f = pd.DataFrame(index=d.index)
    f["corr30"] = r.rolling(30).corr(rb)
    f["beta30"] = r.rolling(30).cov(rb) / rb.rolling(30).var()
    f["ret30_vs_btc"] = ((d.close / d.close.shift(30) - 1) - (btc.close / btc.close.shift(30) - 1).reindex(d.index)) * 100
    f["vol30"] = r.rolling(30).std() * 100
    f["dol30"] = (d.close * d.volume).rolling(30).mean() / 1e6
    return f


def main():
    rows = [r for r in T.rows_of("4h") if r.get("entered")]
    d = pd.DataFrame(rows)
    c = pickle.load(open(T.OUT / "ctl_4h.pkl", "rb")); d = d.merge(c[["sym", "key", "ctl_rand", "ctl_time"]], on=["sym", "key"], how="left")
    btc = load_tf("BTCUSDT", "1d")
    feats = {}; vals = []
    for r in d.itertuples():
        try:
            if r.sym not in feats:
                feats[r.sym] = coin_daily(r.sym, btc)
            f = feats[r.sym]
            day = pd.Timestamp(r.top_time).tz_localize(None).floor("D") if getattr(pd.Timestamp(r.top_time), "tzinfo", None) else pd.Timestamp(r.top_time).floor("D")
            i = f.index.searchsorted(day) - 1                                # закрытый день ДО вершины пятой
            vals.append(f.iloc[i].to_dict() if i >= 0 else {})
        except Exception:
            vals.append({})
    F = pd.DataFrame(vals, index=d.index); d = pd.concat([d, F], axis=1)
    d["год"] = pd.to_datetime(d.top_time).dt.year
    d["oos"] = d.sym.apply(lambda s: int(hashlib.md5(s.encode()).hexdigest(), 16) % 2 == 1)
    d.to_pickle(OUT / "waves_own_game.pkl")
    pd.set_option("display.width", 250)

    def agg(g):
        return g.agg(n=("pnl", "size"), монет=("sym", "nunique"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"),
                     мед=("pnl", "median"), ctl_r=("ctl_rand", "mean"), ctl_t=("ctl_time", "mean")).assign(
            Δr=lambda x: (x["ср"] - x.ctl_r).round(2), Δt=lambda x: (x["ср"] - x.ctl_t).round(2)).round(2)

    print(f"сделок ядра 4h: {len(d)} · с признаками {int(d.corr30.notna().sum())} · монет {d.sym.nunique()} · {d['год'].min()}→{d['год'].max()}")
    print("\n=== база: сторона × год"); print(agg(d.groupby(["side", "год"])).to_string())
    for col in ("corr30", "beta30", "ret30_vs_btc", "vol30", "dol30"):
        z = d.dropna(subset=[col]).copy()
        z["к"] = pd.qcut(z[col], 3, labels=["низ", "сред", "верх"], duplicates="drop")
        print(f"\n=== {col}: сторона × терциль (знач. медиана: " + ", ".join(f"{k} {v:.2f}" for k, v in z.groupby("к", observed=True)[col].median().items()) + ")")
        print(agg(z.groupby(["side", "к"], observed=True)).to_string())
    # «своя игра»: пороги по IS, проверка на OOS
    q = d.dropna(subset=["corr30", "ret30_vs_btc"]).copy()
    IS = q[(~q.oos) & (q["год"] <= 2023)]; OOS = q[(q.oos) & (q["год"] >= 2024)]
    thr_c, thr_r = IS.corr30.quantile(0.33), IS.ret30_vs_btc.quantile(0.67)
    print(f"\n=== «СВОЯ ИГРА» (corr30 ≤ {thr_c:.2f} и обгон BTC ≥ {thr_r:.1f}%, пороги с IS: чётные монеты × ≤2023)")
    for nm, Z in (("IS", IS), ("OOS (нечётные × ≥2024)", OOS), ("ВСЁ", q)):
        own = Z[(Z.corr30 <= thr_c) & (Z.ret30_vs_btc >= thr_r)]; rest = Z.drop(own.index)
        print(f"--- {nm}")
        for side in ("LONG", "SHORT"):
            for lbl, W in (("своя игра", own), ("остальные", rest)):
                y = W[W.side == side]
                if len(y) >= 10:
                    top = y.pnl.nlargest(max(1, int(len(y) * 0.1))).sum()
                    print(f"  {side:5s} {lbl:9s}: n {len(y):5d} монет {y.sym.nunique():3d} WR {(y.pnl > 0).mean() * 100:5.1f}% ср {y.pnl.mean():+6.2f} мед {y.pnl.median():+6.2f} "
                          f"Δr {(y.pnl - y.ctl_rand).mean():+5.2f} Δt {(y.pnl - y.ctl_time).mean():+5.2f} безтоп10 {y.pnl.sum() - top:+7.0f} монет+ {(y.groupby('sym').pnl.sum() > 0).mean() * 100:3.0f}%")
    # по годам для лонга «своя игра»
    own = q[(q.corr30 <= thr_c) & (q.ret30_vs_btc >= thr_r) & (q.side == "LONG")]
    print("\n=== LONG «своя игра» по годам"); print(agg(own.groupby("год")).to_string())


if __name__ == "__main__":
    main()
