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


def check_pair(path: str, cb) -> dict:
    cf = cb.compute_flags
    df = _load(path)
    if len(df) < 300:
        return {}
    df4 = cb.aggregate_tf(df, "4h")
    df1d = cb.aggregate_tf(df, "1d")

    # backtest all_flags: reindex+shift на 1h-сетку (process_symbol style)
    f1 = cf(df, "1h", include_pivots=True)
    f4 = cf(df4, "4h"); f4.index = f4.index + pd.Timedelta(hours=4)
    f4 = f4.reindex(df.index, method="ffill").fillna(False)
    fd = cf(df1d, "1d"); fd.index = fd.index + pd.Timedelta(days=1)
    fd = fd.reindex(df.index, method="ffill").fillna(False)
    allf = pd.concat([f1, f4, fd], axis=1).astype(bool)
    bt = _flat(snapshot_from_flags_row(allf.iloc[-1], entry_tf="1h"))

    # live full-depth (independent last per TF)
    live = _flat(snapshot_features({"1h": df, "4h": df4, "1d": df1d}, entry_tf="1h"))

    # live shallow-depth (1h@300, как build_df_by_tf в проде)
    d300 = df.tail(300)
    sh = _flat(snapshot_features(
        {"1h": d300, "4h": cb.aggregate_tf(d300, "4h"), "1d": cb.aggregate_tf(d300, "1d")},
        entry_tf="1h"))

    return {
        "align_diff": (bt ^ live),          # (1) метод выравнивания
        "depth_diff": (live ^ sh),          # (2) глубина
        "bt_n": len(bt), "live_n": len(live),
    }


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    cb = _import_cb()
    files = sorted(glob.glob("data/history/1h/*.parquet"))[:n]
    align_total: dict = {}
    depth_total: dict = {}
    pairs = 0
    for p in files:
        r = check_pair(p, cb)
        if not r:
            continue
        pairs += 1
        for f in r["align_diff"]:
            align_total[f] = align_total.get(f, 0) + 1
        for f in r["depth_diff"]:
            depth_total[f] = depth_total.get(f, 0) + 1
    print(f"\nПар проверено: {pairs}")
    print(f"\n=== (1) РАСХОЖДЕНИЯ МЕТОДА ВЫРАВНИВАНИЯ (backtest reindex+shift vs live indep) ===")
    for f, c in sorted(align_total.items(), key=lambda x: -x[1]):
        print(f"  {c:3d}/{pairs}  {f}")
    print(f"\n=== (2) РАСХОЖДЕНИЯ ГЛУБИНЫ (live full vs live@300) ===")
    for f, c in sorted(depth_total.items(), key=lambda x: -x[1]):
        print(f"  {c:3d}/{pairs}  {f}")


if __name__ == "__main__":
    main()
