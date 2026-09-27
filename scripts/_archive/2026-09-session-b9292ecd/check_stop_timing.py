"""ЧТЕНИЕ: когда стоп был ЗАДЕТ на реальном рынке против того, когда его зафиксировал бот.
8 шортов impulse_fib_15m закрылись 25.09 в 13:59:30-35 UTC — проверяем, не проспал ли симулятор."""
import sqlite3, sys, time
from pathlib import Path
import pandas as pd, requests

ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))

BASE = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"


def klines(sym: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """5m бары окна; BingX отдаёт ПОСЛЕДНИЕ limit баров окна → режем кусками."""
    out, step = [], 1000 * 5 * 60_000
    t = start_ms
    while t < end_ms:
        p = {"symbol": sym.split("/")[0] + "-USDT", "interval": "5m",
             "startTime": t, "endTime": min(t + step, end_ms), "limit": 1000}
        r = requests.get(BASE, params=p, timeout=20).json()
        d = r.get("data") or []
        out += d
        t += step
        time.sleep(0.25)
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out)
    for c in ("time", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c])
    df["ts"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df.sort_values("ts").drop_duplicates("ts")


c = sqlite3.connect(ROOT / "subscriptions.db")
rows = c.execute(
    "select symbol, entry_price, stop_loss, exit_price, created_at, closed_at "
    "from simulated_trades where signal_type='impulse_fib_15m' "
    "and closed_at like '2026-09-25T13:59%' order by symbol").fetchall()

print(f"{'монета':<18}{'вход UTC':<17}{'стоп задет РЕАЛЬНО':<22}{'бот зафиксировал':<18}{'опоздание'}")
for sym, entry, sl, ex, opened, closed in rows:
    t0 = pd.Timestamp(opened).tz_convert("UTC")
    t1 = pd.Timestamp(closed).tz_convert("UTC")
    df = klines(sym, int(t0.timestamp() * 1000), int((t1 + pd.Timedelta(hours=1)).timestamp() * 1000))
    if df.empty:
        print(f"{sym:<18}нет данных")
        continue
    hit = df[df.high >= sl]
    if hit.empty:
        print(f"{sym:<18}{str(t0)[:16]:<17}{'НЕ ЗАДЕТ на рынке':<22}{str(t1)[11:19]:<18}—")
        continue
    th = hit.iloc[0].ts
    late = (t1 - th).total_seconds() / 3600
    print(f"{sym:<18}{str(t0)[5:16]:<17}{str(th)[5:16]:<22}{str(t1)[5:16]:<18}{late:+.1f} ч")
