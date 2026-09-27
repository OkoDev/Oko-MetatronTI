"""Анализ экспорта канала JewTrade: анатомия постов, сигналы, заявленные результаты, монеты, время.
python tg_jewtrade_analyze.py [overview|signals|verify]"""
import sys, re
import numpy as np, pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
OUT = Path("G:/oko_lab/out/tg_jewtrade")
d = pd.read_pickle(OUT / "posts.pkl"); t = d[d.text.str.len() > 0].copy()
t["ticker"] = t.text.str.extract(r"\$([A-Z0-9]{2,12})")[0]
t["sig"] = t.text.str.contains(r"буду пробовать|при закрепе|при закреплении|пробуем|захожу|зашел|зашёл|вход|лимитк|тейк|стоп", case=False, regex=True)
t["plus"] = t.text.str.contains(r"\+\s?\d+([.,]\d+)?\s?%", regex=True)
t["neg"] = t.text.str.contains(r"(^|\s)[−-]\s?\d+([.,]\d+)?\s?%|по стопу|стоп сработал|минус|убыт|слил", case=False, regex=True)
t["ad"] = t.text.str.contains(r"реф|промокод|бонус|VIP|курс|обучени|регистрац", case=False, regex=True)
t["pct"] = t.text.str.extract(r"\+\s?(\d+(?:[.,]\d+)?)\s?%")[0].str.replace(",", ".").astype(float)
t["year"] = t.dt.dt.year
mode = sys.argv[1] if len(sys.argv) > 1 else "overview"
pd.set_option("display.width", 220)
if mode == "overview":
    print(f"постов {len(d)} · с текстом {len(t)} · с тикером {int(t.ticker.notna().sum())} · с «+X%» {int(t.plus.sum())} · стоп/минус {int(t.neg.sum())} · реклама/VIP/курс {int(t.ad.sum())}")
    g = t.groupby("year").agg(n=("text", "size"), тикер=("ticker", lambda x: x.notna().sum()), plus=("plus", "sum"), neg=("neg", "sum"), ad=("ad", "sum"), мед_плюс=("pct", "median"))
    print(g.to_string())
    print("\nтоп тикеров 2026:", t[t.year == 2026].ticker.value_counts().head(25).to_dict())
    print("топ тикеров всего:", t.ticker.value_counts().head(15).to_dict())
    print("\nсигналы-шаблоны 2026 (примеры):")
    for r in t[t.sig & t.ticker.notna() & (t.dt >= "2026-08-15")].head(16).itertuples():
        print(f"  [{r.dt:%d.%m %H:%M}] {r.text[:150]!r}")
    print("\nпосты с минусом/стопом 2026:")
    for r in t[t.neg & (t.dt >= "2026-06-01")].head(10).itertuples():
        print(f"  [{r.dt:%d.%m %H:%M}] {r.text[:150]!r}")
    print("\nчасы публикаций (UTC+3) для постов с тикером 2026:", t[(t.year == 2026) & t.ticker.notna()].dt.dt.hour.value_counts().sort_index().to_dict())
elif mode == "signals":
    s = t[t.ticker.notna()].copy()
    pat = re.compile(r"(при закрепе|при закреплении)\s*(уровня|цены)?\s*([0-9]+(?:[.,][0-9]+)?)\s*\$?\s*.*?(LONG|SHORT|лонг|шорт)", re.I | re.S)
    rows = []
    for r in s.itertuples():
        m = pat.search(r.text)
        if m:
            rows.append({"dt": r.dt, "ticker": r.ticker, "level": float(m.group(3).replace(",", ".")), "side": m.group(4).upper().replace("ЛОНГ", "LONG").replace("ШОРТ", "SHORT"), "text": r.text[:120]})
    S = pd.DataFrame(rows); S.to_pickle(OUT / "signals.pkl")
    print(f"сигналов «при закрепе уровня X → LONG/SHORT»: {len(S)} · {S.dt.min()} → {S.dt.max()} · монет {S.ticker.nunique()} · LONG {int((S.side=='LONG').sum())} / SHORT {int((S.side=='SHORT').sum())}")
    print(S.groupby(S.dt.dt.to_period("M")).size().to_string())
    print(S.tail(20).to_string())
