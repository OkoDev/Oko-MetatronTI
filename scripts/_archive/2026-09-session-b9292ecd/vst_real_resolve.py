"""ФОРВАРД ПО РЕАЛЬНОМУ РЫНКУ БЕЗ РЕАЛЬНОГО СЧЁТА (Егор 20.09: «мини-реальный счёт пока не могу»).
Каждую заявку бота (simulated_trades, VST, включая CANCELLED = лимит не исполнился и OPEN) переигрываем на ПУБЛИЧНЫХ 5m klines
BingX (реальный перпетуал): лимит по entry_price, окно фила = TTL источника (реестр source_registry), стоп до фила = нет сделки,
после фила — стоп/цель по касанию (стоп приоритетнее в одном баре), выход по времени через HOLD источника по close.
Это та же логика, что журналы impulse_shadow/choch_shadow (_resolve), но для ВСЕХ источников и по внешним данным.
TSL/BE/гибрид бота НЕ моделируются — это мера ГЕОМЕТРИИ сигнала на реальных ценах, а не копия управления позицией.
Косты 0.10% на сделку. python vst_real_resolve.py [дней]"""
import sys, sqlite3, json, time, urllib.request
import numpy as np, pandas as pd
DB = r"E:/MTF BOT/CURSOR/crypto_volume_bot/subscriptions.db"; COST = 0.10
pd.set_option("display.width", 250)
TTL_H = {"impulse_fib": 12, "impulse_fib_15m": 12, "choch_wavec": 12, "ote_nested": 4}
HOLD_H = {"impulse_fib": 96, "impulse_fib_15m": 24, "choch_wavec": 96, "ote_nested": 72, "rangefade": 72, "rangefade4h": 72, "bigflush15": 72, "waves_long": 240, "radar_pump": 24}
_cache = {}


def klines5(base, t0, t1):
    """5m klines реального рынка [t0, t1]; кэш по монете; куски ≤1440 баров = 5 дней."""
    key = base
    if key in _cache and _cache[key].index[0] <= t0 and _cache[key].index[-1] >= t1 - pd.Timedelta(minutes=10):
        return _cache[key]
    # 🔴 5m отдаёт максимум 1000 баров на запрос и ПОСЛЕДНИЕ 1000 окна (проверено 20.09) → куски по 1000 баров = 83 ч
    out = []; start = int(t0.timestamp() * 1000); end = int(t1.timestamp() * 1000); step = 1000 * 5 * 60_000
    while start < end:
        ce = min(start + step, end)
        u = f"https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol={base}-USDT&interval=5m&startTime={start}&endTime={ce}&limit=1000"
        d = []
        for _ in range(3):
            try:
                d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "oko"}), timeout=10)).get("data", []); break
            except Exception:
                time.sleep(1.5)
        out += d; start = ce + 300_000; time.sleep(0.12)
    if not out:
        return None
    k = pd.DataFrame(out).drop_duplicates("time"); k["t"] = pd.to_datetime(k.time.astype(int), unit="ms")
    for c in ("open", "high", "low", "close"):
        k[c] = k[c].astype(float)
    k = k.sort_values("t").set_index("t")
    _cache[key] = k if key not in _cache else pd.concat([_cache[key], k]).loc[lambda x: ~x.index.duplicated()].sort_index()
    return _cache[key]


def resolve(k, t0, long_, e, sl, tp, ttl_h, hold_h):
    w = k[k.index >= t0]
    if w.empty or w.index[0] > t0 + pd.Timedelta(minutes=10):
        return {"real": "нет данных"}                       # история 5m начинается позже заявки — не судим
    hi, lo, cl, idx = w.high.values, w.low.values, w.close.values, w.index
    n_ttl = int(ttl_h * 12); fill = None
    for j in range(min(n_ttl, len(w))):
        if (lo[j] <= sl) if long_ else (hi[j] >= sl):
            return {"real": "стоп до фила"}
        if (lo[j] <= e) if long_ else (hi[j] >= e):
            fill = j; break
    if fill is None:
        return {"real": "нет фила"}
    n_hold = int(hold_h * 12)
    for j in range(fill + 1, min(fill + 1 + n_hold, len(w))):
        if (lo[j] <= sl) if long_ else (hi[j] >= sl):
            return {"real": "SL", "pnl": ((sl - e) / e * 100) * (1 if long_ else -1) - COST, "fill_t": idx[fill], "exit_t": idx[j]}
        if (hi[j] >= tp) if long_ else (lo[j] <= tp):
            return {"real": "TP", "pnl": ((tp - e) / e * 100) * (1 if long_ else -1) - COST, "fill_t": idx[fill], "exit_t": idx[j]}
    j = min(fill + n_hold, len(w) - 1)
    if j < fill + n_hold:
        if idx[j] < pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(minutes=20):
            return {"real": "нет данных"}                   # ряд оборвался до конца удержания
        return {"real": "открыта", "pnl": ((cl[j] - e) / e * 100) * (1 if long_ else -1) - COST, "fill_t": idx[fill], "exit_t": idx[j]}
    return {"real": "время", "pnl": ((cl[j] - e) / e * 100) * (1 if long_ else -1) - COST, "fill_t": idx[fill], "exit_t": idx[j]}


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    c = sqlite3.connect(DB)
    q = pd.read_sql(f"""SELECT id, symbol, direction, signal_type, status, created_at, closed_at, entry_price, actual_entry_price,
                        COALESCE(original_sl, stop_loss) AS sl, take_profit, profit_pct
                        FROM simulated_trades WHERE execution_mode='VST' AND created_at >= datetime('now', '-{days} days')
                        AND signal_type IN ('impulse_fib','impulse_fib_15m','choch_wavec','ote_nested','rangefade','rangefade4h','bigflush15','waves_long','radar_pump')
                        AND entry_price > 0 AND stop_loss > 0 AND take_profit > 0 ORDER BY created_at""", c)
    q["created_at"] = pd.to_datetime(q.created_at, utc=True).dt.tz_localize(None)
    now = pd.Timestamp.utcnow().tz_localize(None); rows = []
    for i, r in enumerate(q.itertuples(), 1):
        base = r.symbol.split("/")[0]; long_ = r.direction == "LONG"
        ttl = TTL_H.get(r.signal_type, 0.5); hold = HOLD_H.get(r.signal_type, 72)
        t1 = min(now, r.created_at + pd.Timedelta(hours=ttl + hold + 1))
        k = klines5(base, r.created_at - pd.Timedelta(minutes=5), t1)
        res = {"real": "нет klines"} if k is None else resolve(k, r.created_at, long_, float(r.entry_price), float(r.sl), float(r.take_profit), ttl, hold)
        rows.append({"id": r.id, "sym": base, "src": r.signal_type, "dir": r.direction, "vst": r.status, "vst_pnl": r.profit_pct, "created": r.created_at,
                     "real": res.get("real"), "real_pnl": res.get("pnl", np.nan), "fill_t": res.get("fill_t"), "exit_t": res.get("exit_t")})
        if i % 50 == 0:
            print(f"  {i}/{len(q)}", flush=True)
    R = pd.DataFrame(rows); R.to_pickle("G:/oko_lab/out/vst_real_resolve.pkl")
    R["vst_filled"] = R.vst.isin(["TP", "SL", "TSL", "EXPIRED", "OPEN"]); R["real_filled"] = R.real.isin(["SL", "TP", "время", "открыта"])
    print(f"\nзаявок VST за {days} дн: {len(R)} · без данных: {(R.real == 'нет klines').sum()}")
    print("\n=== по источникам: VST (исполнено / ср pnl закрытых) против РЕАЛЬНОГО рынка (исполнено / ср pnl)")
    g = R.groupby("src").apply(lambda z: pd.Series({
        "заявок": len(z), "VST_исп": int(z.vst_filled.sum()), "VST_ср": z[z.vst.isin(["TP", "SL", "TSL", "EXPIRED"])].vst_pnl.mean(),
        "VST_сумма": z[z.vst.isin(["TP", "SL", "TSL", "EXPIRED"])].vst_pnl.sum(),
        "РЕАЛ_исп": int(z.real_filled.sum()), "РЕАЛ_ср": z[z.real.isin(["SL", "TP", "время"])].real_pnl.mean(),
        "РЕАЛ_сумма": z[z.real.isin(["SL", "TP", "время"])].real_pnl.sum(), "РЕАЛ_WR": (z[z.real.isin(["SL", "TP", "время"])].real_pnl > 0).mean() * 100,
        "стоп_до_фила": int((z.real == "стоп до фила").sum()), "нет_фила": int((z.real == "нет фила").sum())}), include_groups=False).round(2)
    print(g.to_string())
    print("\n=== матрица: статус VST × исход на реальном рынке")
    print(pd.crosstab(R.src + " " + R.vst, R.real).to_string())
    both = R[R.vst.isin(["TP", "SL", "TSL", "EXPIRED"]) & R.real.isin(["SL", "TP", "время"])]
    print(f"\n=== сделки, закрытые в обоих контурах: {len(both)} · VST ср {both.vst_pnl.mean():+.2f} · реал ср {both.real_pnl.mean():+.2f} · медиана разницы {(both.vst_pnl - both.real_pnl).median():+.2f}")
    print(both.groupby("src").agg(n=("id", "size"), VST=("vst_pnl", "mean"), реал=("real_pnl", "mean")).round(2).to_string())
