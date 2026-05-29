"""
DEV-235.2 ЭТАП 2: ретробэктест 5m/15m паттернов ARCH-104 на исправленном combinator.

Универсальный LTF-оценщик (в отличие от combinator_v3_nested который хардкодит golden
HTF + только LONG): берёт ПРОИЗВОЛЬНЫЙ паттерн, делит anchor_factors на HTF (1h/4h/1d/1W)
и LTF (_5m/_15m), строит комбинированную маску, симулирует LONG И SHORT, пересчитывает
avgR/WR/n на исправленном combinator (DEV-233 div + DEV-234 cross).

Сравнивает с записанными test_avgR/WR/n из config/arch104_patterns.yaml.

Запуск:
  python tools/pattern_mining/retrobacktest_dev235_ltf.py 5m
  python tools/pattern_mining/retrobacktest_dev235_ltf.py 15m
Вывод: tmp_charts/dev235_ltf_<tf>.csv + сводка.
"""
import sys
from pathlib import Path
import yaml
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "pattern_mining"))
import combinator_v2 as cb   # ставит utf-8 stdout

LTF = sys.argv[1] if len(sys.argv) > 1 else "5m"
HISTORY_1H = ROOT / "data" / "history" / "1h"
HISTORY_LTF = ROOT / "data" / "history" / LTF
PATTERNS_YAML = ROOT / "config" / "arch104_patterns.yaml"
OUT_CSV = ROOT / "tmp_charts" / f"dev235_ltf_{LTF}.csv"

FUTURE_BARS = {"5m": 144, "15m": 48}[LTF]   # ~12h
TP_R = 2.0
MIN_N = 10


def simulate_ltf(df, tp_r, future):
    """LONG+SHORT симуляция на LTF-сетке (swing SL 10 баров, TP=tp_r×SL)."""
    n = len(df)
    high = df["high"].values; low = df["low"].values; close = df["close"].values
    r_long = np.full(n, np.nan); r_short = np.full(n, np.nan)
    for i in range(20, n - future - 1):
        price = close[i]
        # LONG
        sl_l = low[i-10:i+1].min() * 0.999
        sld = price - sl_l
        if 0 < sld and sld/price < 0.06:
            tp = price + sld*tp_r
            fh = high[i+1:i+1+future]; fl = low[i+1:i+1+future]
            ht = (fh >= tp); hs = (fl <= sl_l)
            if ht.any() and hs.any(): r_long[i] = tp_r if np.argmax(ht) <= np.argmax(hs) else -1.0
            elif ht.any(): r_long[i] = tp_r
            elif hs.any(): r_long[i] = -1.0
            else: r_long[i] = (close[i+future]-price)/sld
        # SHORT
        sl_s = high[i-10:i+1].max() * 1.001
        sld_s = sl_s - price
        if 0 < sld_s and sld_s/price < 0.06:
            tp = price - sld_s*tp_r
            fh = high[i+1:i+1+future]; fl = low[i+1:i+1+future]
            ht = (fl <= tp); hs = (fh >= sl_s)
            if ht.any() and hs.any(): r_short[i] = tp_r if np.argmax(ht) <= np.argmax(hs) else -1.0
            elif ht.any(): r_short[i] = tp_r
            elif hs.any(): r_short[i] = -1.0
            else: r_short[i] = (price-close[i+future])/sld_s
    return r_long, r_short


def process_pair(symbol):
    """Возвращает (combined_flags_df, r_long, r_short) на LTF-сетке.
    combined = LTF-флаги + HTF-флаги (1h/4h/1d) reindexed на LTF (lookahead-safe)."""
    path_1h = HISTORY_1H / f"{symbol}.parquet"
    path_ltf = HISTORY_LTF / f"{symbol}.parquet"
    if not path_1h.exists() or not path_ltf.exists():
        return None
    try:
        # HTF флаги (1h/4h/1d) через process_symbol
        res = cb.process_symbol(path_1h)
        if res is None:
            return None
        htf_flags, _, _ = res   # уже содержит 1h+4h+1d колонки

        # LTF данные
        df_ltf = pd.read_parquet(path_ltf)
        df_ltf.columns = [c.lower() for c in df_ltf.columns]
        if "ts" in df_ltf.columns:
            df_ltf["ts"] = pd.to_datetime(df_ltf["ts"], unit="ms", utc=True, errors="coerce")
            df_ltf = df_ltf.set_index("ts")
        df_ltf = df_ltf[["open","high","low","close","volume"]].dropna().sort_index()
        if len(df_ltf) < 500:
            return None

        ltf_flags = cb.compute_flags(df_ltf, LTF, include_pivots=True)

        # HTF reindex на LTF (lookahead-safe: 1h close активен +1h)
        htf_shift = htf_flags.copy()
        htf_shift.index = htf_shift.index + pd.Timedelta(hours=1)
        htf_on_ltf = htf_shift.reindex(df_ltf.index, method="ffill").fillna(False).astype(bool)

        # объединяем (LTF + HTF). Дубли колонок (если есть) — берём LTF.
        combined = ltf_flags.copy()
        for c in htf_on_ltf.columns:
            if c not in combined.columns:
                combined[c] = htf_on_ltf[c].values

        r_long, r_short = simulate_ltf(df_ltf, TP_R, FUTURE_BARS)
        return combined, r_long, r_short
    except Exception as e:
        print(f"  ERR {symbol}: {e}")
        return None


def evaluate(data, factors, direction):
    all_rs = []
    for sym, (flags, r_long, r_short) in data.items():
        mask = np.ones(len(flags), dtype=bool)
        ok = True
        for f in factors:
            if f not in flags.columns:
                ok = False; break
            mask &= flags[f].values
        if not ok:
            return None
        if not mask.any():
            continue
        rs = r_long if direction == "LONG" else r_short
        rs_valid = rs[mask & ~np.isnan(rs)]
        if len(rs_valid):
            all_rs.extend(rs_valid)
    if len(all_rs) < MIN_N:
        return None
    arr = np.array(all_rs)
    return {"n": len(arr), "avgR": float(arr.mean()),
            "WR": float((arr > 0).mean()*100), "stdR": float(arr.std())}


def main():
    print("=" * 70)
    print(f"DEV-235.2 ЭТАП 2 — {LTF} паттерны на исправленном combinator")
    print("=" * 70)
    pats = yaml.safe_load(open(PATTERNS_YAML, encoding="utf-8")).get("patterns", {})
    target = {k: v for k, v in pats.items()
              if isinstance(v, dict) and v.get("detection_tf") == LTF}
    print(f"Паттернов detection_tf={LTF}: {len(target)}")

    files = sorted(HISTORY_LTF.glob("*.parquet"))
    print(f"\n[1] Загрузка {len(files)} пар (LTF {LTF} + HTF reindex, исправленный код)...")
    data = {}
    for i, p in enumerate(files):
        res = process_pair(p.stem)
        if res is not None:
            data[p.stem] = res
        if (i + 1) % 10 == 0:
            print(f"    {i+1}/{len(files)} ({len(data)} валидных)")
    print(f"    Загружено: {len(data)}")
    if not data:
        print("НЕТ данных"); return

    print(f"\n[2] Пересчёт {len(target)} паттернов...")
    rows = []
    for name, cfg in target.items():
        anchors = cfg.get("anchor_factors", [])
        direction = cfg.get("direction", "LONG")
        old_n, old_avgR, old_WR = cfg.get("test_n", 0), cfg.get("test_avgR", 0.0), cfg.get("test_WR", 0.0)
        stats = evaluate(data, tuple(anchors), direction)
        if stats is None:
            rows.append({"pattern": name, "dir": direction, "status": "NO_MATCH",
                         "old_n": old_n, "old_avgR": round(old_avgR,3), "old_WR": round(old_WR,1),
                         "new_n": 0, "new_avgR": None, "new_WR": None, "delta_avgR": None,
                         "anchors": ";".join(anchors)})
        else:
            rows.append({"pattern": name, "dir": direction, "status": "OK",
                         "old_n": old_n, "old_avgR": round(old_avgR,3), "old_WR": round(old_WR,1),
                         "new_n": stats["n"], "new_avgR": round(stats["avgR"],3), "new_WR": round(stats["WR"],1),
                         "delta_avgR": round(stats["avgR"]-old_avgR,3), "anchors": ";".join(anchors)})

    df = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(exist_ok=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8")

    ok = df[df["status"] == "OK"].copy()
    print(f"\n{'='*70}")
    print(f"РЕЗУЛЬТАТ {LTF}: всего {len(df)} | пересчитано {len(ok)} | NO_MATCH {(df['status']=='NO_MATCH').sum()}")
    print(f"{'='*70}")
    if len(ok):
        s = ok.sort_values("delta_avgR")
        print(f"\n🔻 ТОП-15 ДЕГРАДАЦИЙ:")
        print(f"{'pattern':<22}{'dir':<6}{'old_avgR':>9}{'new_avgR':>9}{'Δ':>8}{'oldWR':>7}{'newWR':>7}{'new_n':>7}")
        for _, r in s.head(15).iterrows():
            print(f"{r['pattern']:<22}{r['dir']:<6}{r['old_avgR']:>9}{r['new_avgR']:>9}{r['delta_avgR']:>8}{r['old_WR']:>7}{r['new_WR']:>7}{r['new_n']:>7}")
        print(f"\n🔺 ТОП-8 УЛУЧШИЛИСЬ/СТАБИЛЬНЫ:")
        for _, r in s.tail(8)[::-1].iterrows():
            print(f"{r['pattern']:<22}{r['dir']:<6}{r['old_avgR']:>9}{r['new_avgR']:>9}{r['delta_avgR']:>8}{r['old_WR']:>7}{r['new_WR']:>7}{r['new_n']:>7}")
        flipped = ok[(ok["old_avgR"] > 0) & (ok["new_avgR"] <= 0)]
        still = ok[(ok["new_avgR"] > 0.5) & (ok["new_n"] >= 20)]
        print(f"\n⚠️ Перевернулось из avgR>0 в ≤0: {len(flipped)}/{len(ok)}")
        if len(flipped): print("   ", ", ".join(flipped['pattern'].tolist()[:20]))
        print(f"✅ Остались сильными (new avgR>0.5, n≥20): {len(still)}")
        if len(still): print("   ", ", ".join(still['pattern'].tolist()[:20]))
        # WR-сравнение (для топов которые обещали 97%)
        wr_drop = ok[ok["old_WR"] >= 85].sort_values("new_WR")
        if len(wr_drop):
            print(f"\n📉 Паттерны с заявленным WR≥85% — что стало:")
            for _, r in wr_drop.head(10).iterrows():
                print(f"   {r['pattern']:<22} oldWR={r['old_WR']}% → newWR={r['new_WR']}% (n {r['old_n']}→{r['new_n']})")
    print(f"\nCSV: {OUT_CSV}")


if __name__ == "__main__":
    main()
