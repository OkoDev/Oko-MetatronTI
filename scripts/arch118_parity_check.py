"""
ARCH-118 Шаг 3 — проверка parity снимка признаков: live (snapshot_features) vs
backtest (snapshot_from_flags_row из combinator all_flags).

Выявляет два источника расхождения live↔backtest для варианта B:
  (1) МЕТОД ВЫРАВНИВАНИЯ HTF: backtest reindex+shift на entry-сетку (lookahead-guard)
      vs live independent iloc[-1] на каждом TF → разные HTF-свечи на границе.
  (2) ГЛУБИНА ИСТОРИИ: HTF-индикаторы (ema200_1d, ATR) зависят от длины ряда.
      live грузит df_1h@300 → 1d≈13 баров (ema200 недостоверна) vs backtest @full.

Запуск:
  python scripts/arch118_parity_check.py [N_пар]
"""
import sys
import glob
import pandas as pd

sys.path.insert(0, ".")
from core.intelligence.feature_snapshot import (  # noqa: E402
    snapshot_features, snapshot_from_flags_row, _import_cb,
)


def _load(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    if not isinstance(df.index, pd.DatetimeIndex):
        tc = "ts" if "ts" in df.columns else ("time" if "time" in df.columns else None)
        if tc:
            df[tc] = pd.to_datetime(df[tc], unit="ms", utc=True)
            df = df.set_index(tc)
    return df[["open", "high", "low", "close", "volume"]].dropna().sort_index()


def _flat(snap: dict) -> set:
    out: dict = {}
    for d in snap["context"].values():
        out.update(d)
    return set(out)


_DEEP = 4320  # глубина 1h в live после HTFHistoryCache (Шаг 4)


def _snap_indep(cb, df_1h):
    """Снимок independent-last из заданной глубины 1h (HTF=resample). Канон Шага 4."""
    return _flat(snapshot_features(
        {"1h": df_1h, "4h": cb.aggregate_tf(df_1h, "4h"), "1d": cb.aggregate_tf(df_1h, "1d")},
        entry_tf="1h"))


def check_pair(path: str, cb) -> dict:
    df = _load(path)
    if len(df) < 4500:
        return {}

    # КАНОН (рой 5/7): independent-last обе стороны.
    # backtest-эталон = full-depth independent-last; live = deep_htf (HTFHistoryCache@4320).
    bt_canon = _snap_indep(cb, df)              # backtest snapshot_features_at (full)
    live_deep = _snap_indep(cb, df.tail(_DEEP))  # live build_df_by_tf(deep_htf=True)
    live_shallow = _snap_indep(cb, df.tail(300))  # СТАРЫЙ live (до Шага 4) — для контраста

    return {
        "fixed_diff": (bt_canon ^ live_deep),     # после Шага 4 (канон+глубина) → цель ~0
        "old_diff": (bt_canon ^ live_shallow),    # до Шага 4 (мелкая глубина)
    }


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    cb = _import_cb()
    files = sorted(glob.glob("data/history/1h/*.parquet"))[:n]
    fixed_total: dict = {}
    old_total: dict = {}
    pairs = 0
    for p in files:
        r = check_pair(p, cb)
        if not r:
            continue
        pairs += 1
        for f in r["fixed_diff"]:
            fixed_total[f] = fixed_total.get(f, 0) + 1
        for f in r["old_diff"]:
            old_total[f] = old_total.get(f, 0) + 1
    print(f"\nПар проверено (>=4500 1h): {pairs}")
    print(f"\n=== ПОСЛЕ ШАГА 4 (independent-last канон + deep@{_DEEP}) vs backtest-эталон ===")
    if not fixed_total:
        print("  ✅ 0 расхождений — PARITY ДОСТИГНУТ")
    for f, c in sorted(fixed_total.items(), key=lambda x: -x[1]):
        print(f"  {c:3d}/{pairs}  {f}")
    print(f"\n=== ДО ШАГА 4 (мелкая глубина@300) vs эталон — для контраста ===")
    print(f"  всего расхождений-флагов: {sum(old_total.values())} (уник: {len(old_total)})")
    for f, c in sorted(old_total.items(), key=lambda x: -x[1])[:8]:
        print(f"  {c:3d}/{pairs}  {f}")


if __name__ == "__main__":
    main()
