"""
СВОБОДА ОТ DEDUP — straddle-тест OTE (11.06.2026).

Гипотеза (юзер): pull (+2.206) и cont (+2.062) — оба проверенные эджи. Сейчас dedup
(trade_mode='ote_nested') пускает на пару ТОЛЬКО первого по tier-порядку → cont-ракета
режется pull'ом. Что если СНЯТЬ dedup и открывать ОБЕ стороны одновременно (straddle)?
Асимметрия: компактные SL ×10 с двух сторон, cont→далёкая цель, pull→ближняя.

Метод:
  1. Прогон OTESignalGenerator по сетке времён на истории (срез dfs до точки T).
  2. Собрать все FIRE (type pull/cont, direction, entry, sl, tp_runner, tier, ts, ltf).
  3. Forward-симуляция каждого FIRE: до tp_runner (win, R=rr) или sl (loss, R=-1),
     иначе mark-to-market по close. (SINGLE+runner, как ote_trade_edits.)
  4. ДВА портфеля на одном списке событий:
       DEDUP   = на пару одна ote (первый занимает символ до закрытия) — ТЕКУЩЕЕ
       FREEDOM = открываем каждый setup независимо (встречные РАЗРЕШЕНЫ)
  5. Сравнить: total R, n, by type/direction, на co-FIRE подмножестве.

Вывод: data/research/2026-06-11--straddle-freedom/result.md
"""
import sys, time
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.smc.ote_signal_generator import OTESignalGenerator

H5, H15, H1 = Path("data/history/5m"), Path("data/history/15m"), Path("data/history/1h")
import os
STEP = int(os.environ.get("STR_STEP", 12))       # шаг сетки в 5m-барах (1ч)
TAIL_5M = int(os.environ.get("STR_TAIL", 4000))  # ~14 дней истории на пару
HORIZON = 288        # макс forward 5m-баров (24ч) до mark-to-market
MAX_PAIRS = int(os.environ.get("STR_PAIRS", 14))


def _norm(df):
    df.columns = [c.lower() for c in df.columns]
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    return df


def load(base, tf):
    d = {"5m": H5, "15m": H15, "1h": H1}[tf]
    for cand in (f"{base}USDT", base):
        p = d / f"{cand}.parquet"
        if p.exists():
            return _norm(pd.read_parquet(p))
    return None


def build_dfs_full(base):
    d5, d15, d1 = load(base, "5m"), load(base, "15m"), load(base, "1h")
    if d5 is None or d1 is None:
        return None
    d5 = d5.tail(TAIL_5M)
    full = {"5m": d5, "15m": d15, "1h": d1}
    b = d1
    full["4h"] = pd.DataFrame({"open": b["open"].resample("4h").first(), "high": b["high"].resample("4h").max(),
        "low": b["low"].resample("4h").min(), "close": b["close"].resample("4h").last()}).dropna()
    full["1d"] = pd.DataFrame({"open": b["open"].resample("1D").first(), "high": b["high"].resample("1D").max(),
        "low": b["low"].resample("1D").min(), "close": b["close"].resample("1D").last()}).dropna()
    return full


def sim_forward(ltf_df, entry_ts, entry, sl, tp_runner, direction):
    """R сделки: tp_runner(win)/sl(loss) что раньше; иначе mark-to-market по close."""
    risk = abs(entry - sl)
    if risk <= 0:
        return None, None
    rr = abs(tp_runner - entry) / risk
    fut = ltf_df[ltf_df.index > entry_ts].head(HORIZON)
    if len(fut) == 0:
        return None, None
    hi, lo, cl, idx = fut["high"].values, fut["low"].values, fut["close"].values, fut.index
    for k in range(len(fut)):
        if direction == "long":
            if lo[k] <= sl:  return -1.0, idx[k]
            if hi[k] >= tp_runner:  return rr, idx[k]
        else:
            if hi[k] >= sl:  return -1.0, idx[k]
            if lo[k] <= tp_runner:  return rr, idx[k]
    # не дошло — mark-to-market
    mtm = (cl[-1] - entry) / risk if direction == "long" else (entry - cl[-1]) / risk
    return float(np.clip(mtm, -1, rr)), idx[-1]


def collect_fires(gen, base, full):
    """Прогон по сетке → список FIRE-событий с forward-R."""
    d5 = full["5m"]
    n = len(d5)
    events = []
    seen = {}   # (setup_id) -> last_close_ts: не плодить дубль того же setup пока открыт
    for i in range(300, n, STEP):
        T = d5.index[i]
        dfs = {}
        for tf, df in full.items():
            if df is None:
                continue
            sl = df[df.index <= T]
            if len(sl) >= 60:
                dfs[tf] = sl
        if "1h" not in dfs or "5m" not in dfs:
            continue
        try:
            sigs = gen.generate(base, dfs)
        except Exception:
            continue
        for s in sigs:
            if s.status != "FIRE":
                continue
            # не дублируем тот же setup пока «открыт»
            if s.setup_id in seen and T <= seen[s.setup_id]:
                continue
            ltf_df = full.get(s.ltf)
            if ltf_df is None:
                continue
            R, close_ts = sim_forward(ltf_df, s.entry_ts, s.entry, s.sl, s.tp_runner, s.direction)
            if R is None:
                continue
            seen[s.setup_id] = close_ts
            events.append({"symbol": base, "ts": T, "setup_id": s.setup_id, "type": s.type,
                           "direction": s.direction, "tier": s.tier, "R": R, "close_ts": close_ts})
    return events


def portfolio(events, dedup):
    """Прогон портфеля. dedup=True → на символ одна ote (первый занимает).
    dedup=False → каждый setup_id независимо (встречные разрешены)."""
    events = sorted(events, key=lambda e: e["ts"])
    busy = {}   # key -> close_ts
    taken = []
    for e in events:
        key = e["symbol"] if dedup else (e["symbol"], e["setup_id"])
        # занят ли?
        if dedup:
            # любой ote на символе открыт?
            blocked = any(k == e["symbol"] and ct > e["ts"] for k, ct in busy.items())
        else:
            blocked = key in busy and busy[key] > e["ts"]
        if blocked:
            continue
        busy[key] = e["close_ts"]
        taken.append(e)
    return taken


def stats(name, taken):
    if not taken:
        return f"{name}: n=0"
    R = [t["R"] for t in taken]
    avg = sum(R) / len(R)
    wr = 100 * sum(1 for x in R if x > 0) / len(R)
    return (f"{name}: n={len(R)} sumR={sum(R):+.1f} avgR={avg:+.3f} "
            f"medR={np.median(R):+.3f} WR={wr:.0f}%")


def by_type(taken):
    out = []
    for t in ("pull", "cont"):
        sub = [x for x in taken if x["type"] == t]
        out.append("    " + stats(t, sub))
    return "\n".join(out)


def main():
    t0 = time.time()
    gen = OTESignalGenerator()
    bases = sorted({p.stem.replace("USDT", "") for p in H5.glob("*.parquet")})[:MAX_PAIRS]
    print(f"пары: {len(bases)} · enabled-сетапов: {len(gen.setups)} · STEP={STEP} HORIZON={HORIZON}")
    all_events = []
    for b in bases:
        full = build_dfs_full(b)
        if full is None:
            continue
        ev = collect_fires(gen, b, full)
        all_events += ev
        print(f"  {b}: FIRE={len(ev)}  ({time.time()-t0:.0f}s)")

    dedup_taken = portfolio(all_events, dedup=True)
    free_taken = portfolio(all_events, dedup=False)

    # co-FIRE: символы/окна где открылись встречные (freedom взял оба направления)
    free_dirs = {}
    for e in free_taken:
        free_dirs.setdefault((e["symbol"], e["ts"].floor("1h")), set()).add(e["direction"])
    cofire = sum(1 for v in free_dirs.values() if len(v) > 1)

    out = ["# СВОБОДА ОТ DEDUP — straddle OTE (11.06.2026)\n",
           f"Пары: {len(bases)} · FIRE-событий всего: {len(all_events)} · STEP={STEP}(1ч) HORIZON={HORIZON}(24ч)\n",
           "## ПОРТФЕЛЬ: DEDUP (текущее) vs FREEDOM (обе стороны)",
           stats("DEDUP  (на пару одна ote)", dedup_taken),
           by_type(dedup_taken),
           stats("FREEDOM(встречные разрешены)", free_taken),
           by_type(free_taken),
           f"\n  co-FIRE окон (открыты ОБЕ стороны): {cofire}",
           f"\n  delta sumR (freedom - dedup): {sum(t['R'] for t in free_taken) - sum(t['R'] for t in dedup_taken):+.1f}R"]
    txt = "\n".join(out)
    od = Path("data/research/2026-06-11--straddle-freedom")
    od.mkdir(parents=True, exist_ok=True)
    (od / "result.md").write_text(txt, encoding="utf-8")    # запись ДО print (print может упасть на cp1251)
    try:
        print("\n" + txt)
    except Exception:
        pass
    print(f"\n-> {od/'result.md'}  ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
