"""Аудит цен VST против РЕАЛЬНОГО рынка BingX (публичные 1m klines, без ключей).
Закрытые сделки VST с 15.09: exit_price сверяется с [low, high] реального рынка в минуту closed_at (±3 мин);
вход (actual_entry_price) — с диапазоном реального рынка между created_at и closed_at (лимит: фил где-то внутри).
python vst_price_audit.py [дней]"""
import sys, sqlite3, json, time, urllib.request
import numpy as np, pandas as pd
DB = r"E:/MTF BOT/CURSOR/crypto_volume_bot/subscriptions.db"
pd.set_option("display.width", 250)


def klines(base, interval, t0, t1):
    """BingX на окно длиннее limit отдаёт ПОСЛЕДНИЕ 1440 баров (проверено 20.09) → режем окно на куски ≤1440 мин
    и идём от начала; куски с недобором баров помечаем (coverage)."""
    out = []; start = int(t0.timestamp() * 1000); end = int(t1.timestamp() * 1000); step = 1440 * 60_000
    while start < end:
        chunk_end = min(start + step, end)
        u = (f"https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol={base}-USDT&interval={interval}"
             f"&startTime={start}&endTime={chunk_end}&limit=1440")
        d = []
        for _try in range(3):
            try:
                d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "oko"}), timeout=10)).get("data", [])
                break
            except Exception:
                time.sleep(1.5)
        out += d
        start = chunk_end + 60_000
        time.sleep(0.12)
    if not out:
        return None
    k = pd.DataFrame(out).drop_duplicates("time"); k["t"] = pd.to_datetime(k.time.astype(int), unit="ms")
    for c in ("open", "high", "low", "close"):
        k[c] = k[c].astype(float)
    return k.sort_values("t").set_index("t")


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    c = sqlite3.connect(DB)
    q = pd.read_sql(f"""SELECT id, symbol, direction, signal_type, status, created_at, closed_at, actual_entry_price, exit_price, stop_loss, profit_pct
                        FROM simulated_trades WHERE execution_mode='VST' AND exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM'
                        AND actual_entry_price > 0 AND status IN ('TP','SL','TSL','EXPIRED') AND closed_at >= datetime('now', '-{days} days')
                        ORDER BY closed_at""", c)
    q["created_at"] = pd.to_datetime(q.created_at, utc=True).dt.tz_localize(None); q["closed_at"] = pd.to_datetime(q.closed_at, utc=True).dt.tz_localize(None)
    rows = []
    for r in q.itertuples():
        base = r.symbol.split("/")[0]
        k = klines(base, "1m", r.created_at - pd.Timedelta(minutes=2), r.closed_at + pd.Timedelta(minutes=4))
        if k is None or len(k) < 3:
            rows.append({"id": r.id, "sym": base, "note": "нет klines"}); continue
        need = (r.closed_at - r.created_at).total_seconds() / 60 + 6; cov = len(k) / max(need, 1)
        if cov < 0.95:
            rows.append({"id": r.id, "sym": base, "note": f"покрытие {cov*100:.0f}%"}); continue
        w = k[(k.index >= r.closed_at - pd.Timedelta(minutes=3)) & (k.index <= r.closed_at + pd.Timedelta(minutes=3))]
        lo, hi = (w.low.min(), w.high.max()) if len(w) else (np.nan, np.nan)
        ex_dev = 0.0 if (lo <= r.exit_price <= hi) else (min(abs(r.exit_price / lo - 1), abs(r.exit_price / hi - 1)) * 100 if lo == lo else np.nan)
        wi = k[(k.index >= r.created_at - pd.Timedelta(minutes=2)) & (k.index <= r.closed_at)]
        lo2, hi2 = (wi.low.min(), wi.high.max()) if len(wi) else (np.nan, np.nan)
        en_dev = 0.0 if (lo2 <= r.actual_entry_price <= hi2) else (min(abs(r.actual_entry_price / lo2 - 1), abs(r.actual_entry_price / hi2 - 1)) * 100 if lo2 == lo2 else np.nan)
        rows.append({"id": r.id, "sym": base, "src": r.signal_type, "dir": r.direction, "st": r.status, "closed": r.closed_at, "exit": r.exit_price, "рынок_low": lo, "рынок_high": hi,
                     "выход_вне_%": round(ex_dev, 2), "вход": r.actual_entry_price, "вход_вне_%": round(en_dev, 2), "pnl": r.profit_pct})
    R = pd.DataFrame(rows); R.to_pickle("G:/oko_lab/out/vst_price_audit.pkl")
    ok = R[R["выход_вне_%"].notna()]
    print(f"закрытых VST-сделок за {days} дн: {len(q)} · проверено {len(ok)} (без данных/неполное покрытие: {R.note.notna().sum() if 'note' in R else 0}) · "
          f"выход ВНЕ реального диапазона минуты: {(ok['выход_вне_%'] > 0.05).sum()} · вход вне диапазона окна: {(ok['вход_вне_%'] > 0.05).sum()} · вход вне >1%: {(ok['вход_вне_%'] > 1).sum()}")
    bad = ok[(ok["выход_вне_%"] > 0.05) | (ok["вход_вне_%"] > 0.05)]
    print(bad.to_string())
    print("\nпо источникам (доля сделок с выходом вне рынка):")
    print(ok.groupby("src").agg(n=("id", "size"), выход_вне=("выход_вне_%", lambda x: (x > 0.05).mean() * 100), вход_вне=("вход_вне_%", lambda x: (x > 0.05).mean() * 100), pnl=("pnl", "mean")).round(1).to_string())
