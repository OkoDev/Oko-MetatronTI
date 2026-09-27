"""КВОТНАЯ СХЕМА (Егор 16.09: «не резать всё что меньше 70%, а уметь подстраиваться» + «квотную схему тоже прогнать»).
Вместо жёсткого порога — РАНЖИРОВАНИЕ: каждый день считаем вес сетапов и берём топ-N под доступные слоты.
Веса — как в бою (`TradingIntelligence.update_signal_weights`, Сфера 11): EMA фактического результата признака,
half-life 50 сделок, и СЧИТАЮТСЯ ТОЛЬКО ПО ПРОШЛЫМ сделкам (иначе это заглядывание).
Данные: сетапы 4h + вход по слому swing 15m (`choch_entry`).
Запуск: python quota_lab.py
"""
import glob, pickle
from pathlib import Path
import numpy as np, pandas as pd
import sys
sys.path.insert(0, str(Path(__file__).parent))
import tf_sweep as T

OUT = Path("G:/oko_lab/out/choch_entry")
HALF_LIFE = 50          # сделок — как в боевом update_signal_weights
WARMUP = 200            # сделок на обучение весов, до этого не торгуем


def load():
    rows = [r for f in glob.glob(str(OUT / "4h_*.pkl")) for r in pickle.load(open(f, "rb"))]
    d = pd.DataFrame(rows)
    d = d[d.trigger == "CHoCH_swing"].copy()
    base = pd.DataFrame(T.rows_of("4h"))[["sym", "key", "depth5", "imp_pct"]].drop_duplicates(["sym", "key"])
    d = d.merge(base, on=["sym", "key"], how="left")
    d["t"] = pd.to_datetime(d.entry_t)
    d["день"] = pd.to_datetime(d.top_time).dt.floor("D")
    d = d.sort_values("t").reset_index(drop=True)
    d["в_день"] = d.groupby(["день", "side"]).key.transform("size")
    # признаки — те же оси, что показали разницу в срезах
    d["f_ядро"] = d.core_full.astype(bool)
    d["f_импульс"] = d.imp_pct.between(15, 50)
    d["f_стоп"] = d.risk_pct >= 6
    d["f_глубина"] = d.depth5.between(0.8, 1.0)
    d["f_лонг"] = d.side == "LONG"
    d["f_кластер"] = d["в_день"] >= 4
    return d


FEATS = ["f_ядро", "f_импульс", "f_стоп", "f_глубина", "f_лонг", "f_кластер"]


def run():
    d = load()
    alpha = 1 - 0.5 ** (1 / HALF_LIFE)
    w = {f: 0.0 for f in FEATS}          # EMA среднего результата сделок с этим признаком
    seen = 0
    scores = np.full(len(d), np.nan)
    for i, r in enumerate(d.itertuples()):
        if seen >= WARMUP:
            scores[i] = sum(w[f] for f in FEATS if getattr(r, f))
        # обучение ПОСЛЕ того, как сделка сыграла (веса на момент решения — только из прошлого)
        for f in FEATS:
            if getattr(r, f):
                w[f] += alpha * (r.pnl - w[f])
        seen += 1
    d["скор"] = scores
    live = d[d["скор"].notna()].copy()
    print(f"сделок в замере {len(live)} (первые {WARMUP} ушли на обучение весов) · "
          f"{live.t.min():%m.%Y} … {live.t.max():%m.%Y}")
    print("итоговые веса признаков (EMA результата):", {k: round(v, 2) for k, v in w.items()}, "\n")
    мес = (live.t.max() - live.t.min()).days / 30.44
    out = []
    for N in (1, 2, 3, 5, 10, 10**6):
        take = (live.sort_values("скор", ascending=False).groupby("день").head(N)
                if N < 10**6 else live)
        out.append({"квота/день": "без квоты" if N > 1000 else N, "n": len(take),
                    "сд/мес": round(len(take) / мес, 1), "WR%": round((take.pnl > 0).mean() * 100, 1),
                    "ср%": round(take.pnl.mean(), 2), "СУММА п.п.": round(take.pnl.sum()),
                    "мед%": round(take.pnl.median(), 2),
                    "безтоп10": round((take.pnl.sum() - take.pnl.nlargest(max(1, len(take) // 10)).sum()) / len(take), 2)})
    print(pd.DataFrame(out).to_string(index=False))
    print("\nдля сравнения — ЖЁСТКИЙ ПОРОГ (те же сделки, фильтры вместо ранжирования):")
    hard = live[live.f_ядро & live.f_импульс & live.f_стоп & live.f_лонг]
    print(f"  ядро+импульс+стоп+лонг: n={len(hard)} · {len(hard)/мес:.1f} сд/мес · WR {(hard.pnl>0).mean()*100:.1f}% · "
          f"ср {hard.pnl.mean():+.2f}% · СУММА {hard.pnl.sum():+.0f} п.п.")
    print("\nквота по годам (N=3):")
    take3 = live.sort_values("скор", ascending=False).groupby("день").head(3)
    take3["год"] = take3.t.dt.year
    print(take3.groupby("год").agg(n=("pnl", "size"), WR=("pnl", lambda x: (x > 0).mean() * 100),
                                   ср=("pnl", "mean"), сумма=("pnl", "sum")).round(2).to_string())


if __name__ == "__main__":
    run()
