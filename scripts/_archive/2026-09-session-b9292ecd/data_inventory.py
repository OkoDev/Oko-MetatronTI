"""Инвентаризация данных перед докачкой (Егор 16.09: «докачать по всем ТФ до актуальных с максимальным покрытием монет»).
Печатает: что лежит в 1m-паркетах и до какой даты · вселенная BingX (боевая) · что из неё есть на Binance UM · чего не хватает."""
import json, urllib.request
from pathlib import Path
import pandas as pd

PARQ = Path("C:/oko_history/1m")


def http(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


have = {}
for p in sorted(PARQ.glob("*.parquet")):
    d = pd.read_parquet(p, columns=["close"])
    have[p.stem] = (d.index[0], d.index[-1], len(d))
last = pd.Series({k: v[1] for k, v in have.items()})
print(f"1m-паркеты: {len(have)} монет · {sum(v[2] for v in have.values()) / 1e6:.1f} млн баров")
print(f"  начало: {min(v[0] for v in have.values()):%Y-%m-%d} … конец: {last.max():%Y-%m-%d %H:%M} (самый свежий)")
print(f"  отставание последнего бара: медиана {(last.max() - last).median()} · максимум {(last.max() - last).max()}")
print("  монеты с отставанием > 3 дней:", (last < last.max() - pd.Timedelta(days=3)).sum())

bx = http("https://open-api.bingx.com/openApi/swap/v2/quote/contracts")
bingx = sorted({c["symbol"].replace("-", "").replace("USDT", "") + "USDT" for c in bx.get("data", [])
                if c.get("symbol", "").endswith("-USDT")})
bn = http("https://fapi.binance.com/fapi/v1/exchangeInfo")
binance = sorted({s["symbol"] for s in bn["symbols"]
                  if s.get("contractType") == "PERPETUAL" and s.get("status") == "TRADING" and s["symbol"].endswith("USDT")})
print(f"\nвселенная BingX (боевая): {len(bingx)} пар · Binance UM PERPETUAL: {len(binance)}")


def norm(s):
    """BINGX BTCUSDT ↔ Binance BTCUSDT / 1000SHIBUSDT — сопоставление по базовому активу."""
    b = s[:-4]
    for cand in (b + "USDT", "1000" + b + "USDT", b.replace("1000", "") + "USDT"):
        if cand in binance:
            return cand
    return None


pairs = {s: norm(s) for s in bingx}
avail = {s: v for s, v in pairs.items() if v}
print(f"  из BingX есть на Binance UM: {len(avail)} · нет: {len(pairs) - len(avail)}")
new = sorted(s for s in avail if s not in have)
extra = sorted(s for s in have if s not in avail)
print(f"  уже скачано из них: {len(avail) - len(new)} · НЕ скачано: {len(new)}")
print(f"  скачано, но вне BingX сейчас (делистинг/переименование): {len(extra)} {extra[:8]}")
print("\nновые монеты к загрузке:", ", ".join(f"{s}({avail[s]})" if avail[s] != s else s for s in new[:40]))
if len(new) > 40:
    print(f"  … и ещё {len(new) - 40}")
json.dump({"targets": {s: avail[s] for s in avail}, "new": new,
           "last": {k: str(v[1]) for k, v in have.items()}},
          open(Path(__file__).with_name("data_targets.json"), "w"), indent=0)
print("\nцели сохранены в data_targets.json")
