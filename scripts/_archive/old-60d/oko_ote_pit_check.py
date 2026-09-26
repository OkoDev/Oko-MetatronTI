# -*- coding: utf-8 -*-
"""PIT-CHECK: масштаб lookahead в выборе HTF-зоны OKO-OTE (приоритет 1, 25.06).

Сравнивает зону старшего ТФ, выбранную ДВУМЯ способами для КАЖДОГО LTF-слома:
  (A) ХИНДСАЙТ (как сейчас в detect_oko_ote бэктесте): select_significant_impulse на
      ПОЛНОМ df_zone → current_price=последний бар ВСЕЙ истории → одна зона на все сделки.
  (B) POINT-IN-TIME (честно): select_significant_impulse на срезе df_zone[:choch_ts] →
      current_price=цена на момент слома → зона как видел бы живой бот.

Метрика: для скольких сломов containment-вердикт (entry в OTE-зоне старшего?) РАСХОДИТСЯ
между A и B. Расхождение = сделка-артефакт хиндсайта (или пропущенная). 0 своих формул —
переиспользует select_significant_impulse/zigzag_atr/find_setups_zz/_zz_params/adaptive_dev.

Запуск: python scripts/oko_ote_pit_check.py [--zone-tf 4h] [--break-tf 5m] [--pairs N]
"""
import argparse, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa

CACHE = ROOT / "ohlcv_cache.db"
ENTRY_FIB = 0.62


def _load(conn, sym, tf):
    df = pd.read_sql_query(
        "SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
        conn, params=(sym, tf))
    if df.empty:
        return None
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df


def check_pair(conn, sym, zone_tf, break_tf):
    from core.smc.smc_engine import (zigzag_atr, find_setups_zz,
                                     select_significant_impulse, adaptive_dev)
    try:
        from core.smc.smc_snapshot import _zz_params
        _dp, _ = _zz_params(zone_tf)
    except Exception:
        _dp = 11
    d_zone = _load(conn, sym, zone_tf); d_break = _load(conn, sym, break_tf)
    if d_zone is None or d_break is None or len(d_zone) < 100 or len(d_break) < 300:
        return None

    # (A) ХИНДСАЙТ-зона: на полном df_zone (как сейчас в detect_oko_ote)
    zz_full = zigzag_atr(d_zone, depth=_dp, dev_mult=adaptive_dev(d_zone, _dp))
    h_hind = select_significant_impulse(d_zone, zz_full)
    if h_hind is None:
        return None
    hind_lo, hind_hi = h_hind["ote"]

    # LTF-сломы (как в detect_oko_ote)
    ltf = find_setups_zz(zigzag_atr(d_break), d_break)
    if not ltf:
        return None

    n_setups = 0
    n_hind_in = 0       # прошли containment по ХИНДСАЙТ-зоне (= "сделки" текущего бэктеста)
    n_pit_in = 0        # прошли бы по PIT-зоне
    n_agree = 0         # вердикт совпал
    n_only_hind = 0     # хиндсайт впустил, PIT — нет (АРТЕФАКТ lookahead)
    n_only_pit = 0      # PIT впустил, хиндсайт — нет (пропущено хиндсайтом)
    n_zone_diff = 0     # сама зона (ote_lo/hi) отличается >1%
    zone_idx = d_zone.index

    for s in ltf:
        cts = pd.Timestamp(s["choch_ts"])
        entry = s["levels"].get(ENTRY_FIB)
        if entry is None:
            continue
        n_setups += 1
        in_hind = hind_lo <= entry <= hind_hi

        # (B) PIT-зона: срез df_zone до времени слома
        d_cut = d_zone.loc[:cts]
        if len(d_cut) < 50:
            in_pit = False; h_pit = None
        else:
            try:
                zz_cut = zigzag_atr(d_cut, depth=_dp, dev_mult=adaptive_dev(d_cut, _dp))
                h_pit = select_significant_impulse(d_cut, zz_cut)
            except Exception:
                h_pit = None
            if h_pit is None:
                in_pit = False
            else:
                plo, phi = h_pit["ote"]
                in_pit = plo <= entry <= phi
                if abs(plo - hind_lo) / hind_lo > 0.01 or abs(phi - hind_hi) / hind_hi > 0.01:
                    n_zone_diff += 1

        n_hind_in += int(in_hind)
        n_pit_in += int(in_pit)
        n_agree += int(in_hind == in_pit)
        if in_hind and not in_pit:
            n_only_hind += 1
        if in_pit and not in_hind:
            n_only_pit += 1

    return dict(sym=sym, setups=n_setups, hind_in=n_hind_in, pit_in=n_pit_in,
                agree=n_agree, only_hind=n_only_hind, only_pit=n_only_pit, zone_diff=n_zone_diff)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--zone-tf", default="4h"); ap.add_argument("--break-tf", default="5m")
    ap.add_argument("--pairs", type=int, default=20)
    a = ap.parse_args()
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe=? ORDER BY symbol", (a.break_tf,))]
    if a.pairs:
        syms = syms[:a.pairs]
    import time
    t0 = time.time()
    agg = dict(setups=0, hind_in=0, pit_in=0, agree=0, only_hind=0, only_pit=0, zone_diff=0)
    done = 0
    for s in syms:
        try:
            r = check_pair(conn, s, a.zone_tf, a.break_tf)
        except Exception:
            r = None
        done += 1
        if r:
            for k in agg:
                agg[k] += r[k]
        if done % 5 == 0:
            print(f"[pit] {done}/{len(syms)} | {time.time()-t0:.0f}s", flush=True)
    conn.close()

    print(f"\n# PIT-CHECK lookahead зоны — {a.zone_tf}->{a.break_tf}, {len(syms)} пар\n")
    s = agg["setups"] or 1
    print(f"LTF-сломов всего: {agg['setups']}")
    print(f"containment IN по ХИНДСАЙТ-зоне (= сделки тек. бэктеста): {agg['hind_in']} ({100*agg['hind_in']/s:.1f}%)")
    print(f"containment IN по PIT-зоне (честно):                      {agg['pit_in']} ({100*agg['pit_in']/s:.1f}%)")
    print(f"вердикт совпал (hind==pit):  {agg['agree']} ({100*agg['agree']/s:.1f}%)")
    print(f"🔴 ТОЛЬКО хиндсайт впустил (АРТЕФАКТ lookahead): {agg['only_hind']}")
    print(f"🟡 ТОЛЬКО PIT впустил (пропущено хиндсайтом):     {agg['only_pit']}")
    hi = agg["hind_in"] or 1
    print(f"\nДоля сделок тек.бэктеста-АРТЕФАКТОВ: {100*agg['only_hind']/hi:.1f}% (only_hind/hind_in)")
    print(f"Зона отличалась >1% на {agg['zone_diff']} сломах ({100*agg['zone_diff']/s:.1f}%)")


if __name__ == "__main__":
    main()
