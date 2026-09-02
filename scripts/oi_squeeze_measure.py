# -*- coding: utf-8 -*-
"""
ARCH-129: есть ли предсказательная сила у метки СКВИЗА (OI×цена)? (01.09.2026)

Повод: метка `short_squeeze` / `long_flush` заведена в Сферу 19 по канону и по разбору
HYPE 30.08 («пробой при падающем OI — это закрытие шортов, а не сила»). Канон
правдоподобен, но НЕ ИЗМЕРЕН. Ставить в бой неизмеренное нельзя.

🔴 ЧЕСТНАЯ ИНВЕНТАРИЗАЦИЯ ДАННЫХ (печатается прогоном, окно НЕ копировалось):
  · `oi_snapshots`: 18 символов, 2026-07-02 → 2026-09-01 — истории OI больше НЕТ
    физически (Binance отдаёт ~30 дней, копим с июля);
  · цены 15m в кэше до 2026-08-23 → рабочее пересечение ≈ 52 дня;
  · 18 монет — это КРУПНЯК, не ядро 97. Вердикт заведомо не переносится на альты.

Метод:
  · квадрант считается на ЗАКРЫТОМ часе (Δцены и ΔOI за прошедший час) — причинно;
  · forward-доходность после метки на 1ч / 4ч / 24ч, в % net с костами;
  · контроль — базовая доходность на тех же барах без метки;
  · срезы: сторона · неделя · монета · сила движения.

Запуск: python scripts/oi_squeeze_measure.py
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FEED = "oko_feed/external_data.db"
OHLCV = "ohlcv_cache.db"
COST = 0.35          # лимитный круг, как в остальных замерах проекта
HORIZONS = (1, 4, 24)        # часы


def load_oi(sym: str) -> pd.DataFrame:
    c = sqlite3.connect(f"file:{FEED}?mode=ro", uri=True)
    try:
        d = pd.read_sql("SELECT ts, oi_coins FROM oi_snapshots WHERE symbol=? ORDER BY ts",
                        c, params=(sym,))
    finally:
        c.close()
    if d.empty:
        return d
    d["hour"] = (d.ts // 3600) * 3600
    return d.groupby("hour", as_index=False).oi_coins.last()


def load_px(sym: str) -> pd.DataFrame:
    c = sqlite3.connect(f"file:{OHLCV}?mode=ro", uri=True)
    try:
        d = pd.read_sql("SELECT time, close FROM ohlcv_cache WHERE symbol=? "
                        "AND timeframe='1h' ORDER BY time", c, params=(f"{sym}/USDT",))
    finally:
        c.close()
    if d.empty:
        return d
    d["hour"] = d.time // 1000
    return d[["hour", "close"]]


def quadrant(dpx: float, doi: float, flat: float = 0.1) -> str:
    """Метка как у радара: три состояния на ось, флэт по порогу."""
    p = "PUP" if dpx > flat else ("PDN" if dpx < -flat else "PFL")
    o = "OIUP" if doi > flat else ("OIDN" if doi < -flat else "OIFL")
    return f"{p}+{o}"


def stat(v: np.ndarray) -> dict | None:
    if len(v) < 30:
        return None
    w, gl = v[v > 0], -v[v <= 0].sum()
    srt = np.sort(v)[::-1]
    return dict(n=len(v), wr=100 * (v > 0).mean(), pf=(w.sum() / gl if gl else 99.0),
                avg=float(v.mean()), med=float(np.median(v)),
                bt=float(srt[int(len(srt) * 0.1):].sum()))


def line(nm: str, v: np.ndarray, base: dict | None = None) -> None:
    s = stat(v)
    if not s:
        print(f"    {nm:<26} n={len(v)} — мало")
        return
    lift = f" ×{s['pf'] / base['pf']:.2f}" if base and base["pf"] else ""
    print(f"    {nm:<26} n={s['n']:>6} WR {s['wr']:>4.1f}% PF {s['pf']:>5.2f}{lift:>7} "
          f"ср {s['avg']:>+6.3f}% мед {s['med']:>+6.3f}% безтоп10% {s['bt']:>+8.0f}")


def main() -> int:
    c = sqlite3.connect(f"file:{FEED}?mode=ro", uri=True)
    syms = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM oi_snapshots ORDER BY 1")]
    c.close()

    rows = []
    for sym in syms:
        oi, px = load_oi(sym), load_px(sym)
        if oi.empty or px.empty:
            continue
        m = px.merge(oi, on="hour", how="inner").sort_values("hour")
        if len(m) < 100:
            continue
        m["dpx"] = m.close.pct_change() * 100
        m["doi"] = m.oi_coins.pct_change() * 100
        for h in HORIZONS:
            m[f"fwd{h}"] = (m.close.shift(-h) / m.close - 1) * 100
        m = m.dropna(subset=["dpx", "doi"])
        for _, r in m.iterrows():
            rows.append(dict(sym=sym, hour=int(r.hour), q=quadrant(r.dpx, r.doi),
                             dpx=r.dpx, doi=r.doi,
                             **{f"fwd{h}": r.get(f"fwd{h}") for h in HORIZONS}))

    if not rows:
        print("🔴 НОЛЬ строк — пустой замер, стоп")
        return 1
    D = pd.DataFrame(rows)
    t0 = datetime.fromtimestamp(D.hour.min(), timezone.utc)
    t1 = datetime.fromtimestamp(D.hour.max(), timezone.utc)
    print("=" * 108)
    print(f"СКВИЗ ПО OI — ЕСТЬ ЛИ ПРЕДСКАЗАТЕЛЬНАЯ СИЛА · {D.sym.nunique()} монет · "
          f"{len(D):,} часов")
    print(f"окно {t0:%Y-%m-%d} → {t1:%Y-%m-%d} ({(t1 - t0).days} дней) · косты {COST}%")
    print("🔴 18 КРУПНЫХ монет, ~52 дня, ОДНА фаза рынка — на альты и на другие эпохи")
    print("   вердикт НЕ переносится. Больше данных физически нет (OI копится с июля).")
    print("=" * 108)

    print("\nРАСПРЕДЕЛЕНИЕ КВАДРАНТОВ:")
    for q, n in D.q.value_counts().items():
        print(f"    {q:<12} {n:>6} ({100 * n / len(D):5.1f}%)")

    for h in HORIZONS:
        col = f"fwd{h}"
        sub = D.dropna(subset=[col])
        if sub.empty:
            continue
        print(f"\n{'=' * 108}\nГОРИЗОНТ {h}ч — доходность ПОСЛЕ метки (long-сторона, % net)")
        print("=" * 108)
        base_v = sub[col].values - COST
        base = stat(base_v)
        line("БАЗА (все часы)", base_v)
        for q in ("PUP+OIDN", "PDN+OIDN", "PUP+OIUP", "PDN+OIUP", "PUP+OIFL", "PDN+OIFL"):
            v = sub[sub.q == q][col].values - COST
            tag = {"PUP+OIDN": " ← short_squeeze", "PDN+OIDN": " ← long_flush"}.get(q, "")
            line(f"{q}{tag}", v, base)
        # 🔑 Канон утверждает: после short_squeeze движение ВВЕРХ не продолжается.
        # Значит проверять надо SHORT-сторону: доходность шорта = минус доходность лонга.
        print(f"\n  ЗЕРКАЛО — SHORT после метки (доходность = −forward):")
        for q in ("PUP+OIDN", "PDN+OIUP"):
            v = -sub[sub.q == q][col].values - COST
            line(f"  short после {q}", v, stat(-base_v))

    # ── срезы протокола ────────────────────────────────────────────────────
    col = "fwd4"
    sub = D.dropna(subset=[col])
    print(f"\n{'=' * 108}\nСРЕЗЫ (горизонт 4ч, метка short_squeeze = PUP+OIDN)\n{'=' * 108}")
    sq = sub[sub.q == "PUP+OIDN"]
    print("\n  ПО НЕДЕЛЯМ:")
    wk = pd.to_datetime(sq.hour, unit="s", utc=True).dt.to_period("W")
    for w, g in sq.groupby(wk.values):
        line(f"  {w}", -g[col].values - COST)
    print("\n  ПО МОНЕТАМ (топ-6 по числу):")
    for s_, g in sorted(sq.groupby("sym"), key=lambda x: -len(x[1]))[:6]:
        line(f"  {s_}", -g[col].values - COST)
    print("\n  ПО СИЛЕ ДВИЖЕНИЯ (|Δцены| за час):")
    for lo, hi in ((0.1, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 100.0)):
        g = sq[(sq.dpx.abs() >= lo) & (sq.dpx.abs() < hi)]
        line(f"  Δцены {lo}-{hi}%", -g[col].values - COST)

    print("\n🔑 НЕ проверено: альты вне 18 крупных · другие фазы рынка · связка с боевыми")
    print("   гейтами · сила на горизонтах >24ч · интрабар-исполнение.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
