# -*- coding: utf-8 -*-
"""Бэктест ВЫХОДА OKO-OTE: раннер до CHoCH 1h vs фикс-цель −1. СЧЁТ В $ (НЕ R, R=фикция).

Композиция эталонов (0 своих формул): detect_oko_ote (вход) + find_setups_zz (CHoCH-выход).
Риск $5/сделку (депо $500, 1%). $ = qty×(exit−entry), qty=риск/|entry−sl|, минус комиссия.
Сравнение выходов: target_-1 (фикс) · runner_choch (до противоположного слома 1h) · ladder (лестница).
Запуск: python scripts/oko_ote_runner_test.py [--pairs N] [--zone-tf 4h] [--break-tf 1h]
"""
import argparse, os, sqlite3, sys
from multiprocessing import Pool
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa
import numpy as np   # noqa

CACHE = ROOT / "ohlcv_cache.db"
RISK_USD = 5.0          # риск $/сделку (депо $500, 1%)
FEE = 0.0005            # taker 0.05% за сторону
MAXHOLD = 2000          # макс баров удержания


def _load(conn, sym, tf):
    df = pd.read_sql_query("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
                           conn, params=(sym, tf))
    if df.empty:
        return None
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df


def _pnl(entry, exit_px, sl, direction):
    """$-P&L при риске RISK_USD (qty так, чтобы при SL потеря = RISK_USD). Минус комиссия."""
    risk_px = abs(entry - sl)
    if risk_px <= 0:
        return 0.0
    qty = RISK_USD / risk_px
    raw = qty * (exit_px - entry) if direction == "long" else qty * (entry - exit_px)
    fee = qty * entry * FEE * 2
    return raw - fee


def test_pair(conn, sym, zone_tf, break_tf, min_confs=3, mid_tf=None, entry_fib=0.62, pit_zone=False, recency=False, confs_tf=None):
    from core.smc.oko_ote import detect_oko_ote
    from core.smc.smc_engine import zigzag_atr, find_setups_zz
    d_zone = _load(conn, sym, zone_tf); d_break = _load(conn, sym, break_tf)
    if d_zone is None or d_break is None or len(d_zone) < 100 or len(d_break) < 300:
        return []
    d_mid = _load(conn, sym, mid_tf) if mid_tf else None
    if mid_tf and (d_mid is None or len(d_mid) < 100):
        return []
    # ПОЛНЫЙ dfs для подтверждений (atr на 3m/15m + div/wt/vol/liq) — как ote_nested
    dfs_all = {zone_tf: d_zone, break_tf: d_break}
    if mid_tf:
        dfs_all[mid_tf] = d_mid
    for _tf in ("15m", "5m"):
        if _tf not in dfs_all:
            _d = _load(conn, sym, _tf)
            if _d is not None:
                dfs_all[_tf] = _d
    try:
        sigs = detect_oko_ote(sym, d_zone, d_break, zone_tf, break_tf,
                              only_latest=False, min_confs=min_confs, dfs_all=dfs_all,
                              mid_tf=mid_tf, df_mid=d_mid, entry_fib=entry_fib, pit_zone=pit_zone, recency=recency, confs_tf=confs_tf)
    except Exception:
        return []
    if not sigs:
        return []
    # CHoCH-выход: сломы break_tf (эталон) с временами для раннера
    bsetups = find_setups_zz(zigzag_atr(d_break), d_break)
    opp_choch = [(s["choch_ts"], s["direction"]) for s in bsetups]
    posL = {ts: i for i, ts in enumerate(d_break.index)}
    lo = d_break["low"].values; hi = d_break["high"].values; cl = d_break["close"].values; n = len(d_break)
    out = []
    for sig in sigs:
        try:
            ei = posL.get(pd.Timestamp(sig.entry_ts))
        except Exception:
            ei = None
        if ei is None:
            continue
        entry, sl, D = sig.entry, sig.sl, sig.direction
        is_long = D == "long"
        x_end = min(ei + MAXHOLD, n - 1)

        def slhit(j):
            return (lo[j] <= sl) if is_long else (hi[j] >= sl)

        # MFE % (правда хода после входа)
        mfe_pct = 0.0
        for j in range(ei, x_end + 1):
            fav = (hi[j] - entry) / entry if is_long else (entry - lo[j]) / entry
            mfe_pct = max(mfe_pct, fav * 100)
            if slhit(j):
                break

        # выход 1: фикс-цель −1 (targets[0])
        tgt = sig.targets[0][0] if sig.targets else sig.tp
        r1 = None
        for j in range(ei, x_end + 1):
            if slhit(j): r1 = _pnl(entry, sl, sl, D); break
            if (hi[j] >= tgt) if is_long else (lo[j] <= tgt):
                r1 = _pnl(entry, tgt, sl, D); break
        if r1 is None: r1 = _pnl(entry, cl[x_end], sl, D)

        # выход 1b: фикс-цель −1.618 (targets[1], если есть — эталон fib_ext лестницы)
        r1b = None
        if sig.targets and len(sig.targets) > 1:
            tgt2 = sig.targets[1][0]
            for j in range(ei, x_end + 1):
                if slhit(j): r1b = _pnl(entry, sl, sl, D); break
                if (hi[j] >= tgt2) if is_long else (lo[j] <= tgt2):
                    r1b = _pnl(entry, tgt2, sl, D); break
            if r1b is None: r1b = _pnl(entry, cl[x_end], sl, D)

        # REACH-RATE доп. фибо-уровней (-2.0/-2.618/-3.618/-4.236) — НЕ $-exit, просто
        # "доходила ли цена до SL/maxhold" (как target_-1, но без P&L). Уровни выводятся
        # из канонической build_ote-формулы price=swing_a+f*rng через 2 известные точки
        # -1.0/-1.618 (targets), а не считаются новой формулой.
        reach = {}
        tlabels = {lbl: px for px, lbl in (sig.targets or [])}
        t_m1, t_m1618 = tlabels.get("fib_ext_-1.0"), tlabels.get("fib_ext_-1.618")
        if t_m1 is not None and t_m1618 is not None:
            rng_ = (t_m1 - t_m1618) / 0.618
            for f in (-1.618, -2.0, -2.618, -3.618, -4.236):
                lvl = t_m1 + (1 + f) * rng_
                hit = False
                for j in range(ei, x_end + 1):
                    if slhit(j): break
                    if (hi[j] >= lvl) if is_long else (lo[j] <= lvl):
                        hit = True; break
                reach[f"reach_{f}"] = hit

        # выход 2: РАННЕР до противоположного CHoCH break_tf (твоё «до слома структуры»)
        opp = "short" if is_long else "long"
        xc_ts = None
        for ts, dr in opp_choch:
            if ts > pd.Timestamp(sig.choch_ts) and dr == opp:
                xc_ts = ts; break
        xc = posL.get(xc_ts) if xc_ts is not None else x_end
        xc = min(xc, x_end)
        r2 = None
        for j in range(ei, xc + 1):
            if slhit(j): r2 = _pnl(entry, sl, sl, D); break
        if r2 is None: r2 = _pnl(entry, cl[xc], sl, D)   # выход по close в момент слома

        # выход 3: лестница (частичные 50% на −1, остаток раннером до CHoCH)
        r3 = 0.5 * r1 + 0.5 * r2

        # выходы 4-5: БЛИЖНИЕ фикс-R цели (ловят MFE если ход ближе чем −1)
        risk_px = abs(entry - sl)
        rmap = {}
        for rmult, key in ((2.0, "tp_2R"), (3.0, "tp_3R")):
            tgt_r = entry + rmult * risk_px if is_long else entry - rmult * risk_px
            rr = None
            for j in range(ei, x_end + 1):
                if slhit(j): rr = _pnl(entry, sl, sl, D); break
                if (hi[j] >= tgt_r) if is_long else (lo[j] <= tgt_r):
                    rr = _pnl(entry, tgt_r, sl, D); break
            if rr is None: rr = _pnl(entry, cl[x_end], sl, D)
            rmap[key] = rr
        # выход 6: ЛЕСТНИЦА-RUNNER (50% на +2R фикс, 50% раннером до CHoCH — ловит и edge, и ракету)
        ladder_run = 0.5 * rmap["tp_2R"] + 0.5 * r2

        # htf_dir из zone_ts ("htf=long ..." → "long") + aligned-флаг (слом LTF в сторону
        # импульса HTF = trend-continuation). Вариант A(все)/B(aligned)/counter — без 2-го прогона.
        _htf_dir = ""
        try:
            _htf_dir = sig.zone_ts.split()[0].split("=")[1]
        except Exception:
            pass
        row = {"sym": sym, "dir": D, "htf_dir": _htf_dir, "aligned": (_htf_dir == D),
               "target_-1": r1, "runner_choch": r2,
               "ladder": r3, "tp_2R": rmap["tp_2R"], "tp_3R": rmap["tp_3R"],
               "ladder_run": ladder_run, "mfe_pct": mfe_pct, "depth": sig.depth,
               "entry_ts": sig.entry_ts, "choch_ts": sig.choch_ts, "entry_px": sig.entry}
        if r1b is not None:
            row["target_-1.618"] = r1b
        row.update(reach)
        out.append(row)
    return out


def _worker(args):
    """Изолированный процесс: своё sqlite-подключение (conn не пиклится между процессами)."""
    import time
    sym, zone_tf, break_tf, min_confs, mid_tf, entry_fib, pit_zone, recency, confs_tf = args
    conn = sqlite3.connect(CACHE, timeout=60)
    t0 = time.time()
    try:
        trades = test_pair(conn, sym, zone_tf, break_tf, min_confs, mid_tf, entry_fib, pit_zone, recency, confs_tf)
    except Exception:
        trades = []
    finally:
        conn.close()
    return sym, time.time() - t0, trades


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(); ap.add_argument("--pairs", type=int, default=120)
    ap.add_argument("--zone-tf", default="4h"); ap.add_argument("--break-tf", default="1h")
    ap.add_argument("--mid-tf", default=None)  # опц. средний ТФ — тройная вложенность (4h⊃mid⊃break)
    ap.add_argument("--entry-fib", type=float, default=0.62)  # sweep 0.5/0.62/0.705
    ap.add_argument("--pit-zone", action="store_true")  # PIT-зона (честно, без хиндсайта); 2-уровневый
    ap.add_argument("--recency", action="store_true")  # свежий слом > крупный span (фикс мерцания зоны)
    ap.add_argument("--confs-tf", default=None)  # ТФ подтверждений (5m=LTF); None=break_tf. Слом на break, confs на 5m
    ap.add_argument("--min-confs", type=int, default=3)   # ПОЛНЫЙ тест: подтверждения ≥3 (live-фильтр)
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))  # пары независимы → параллельно по CPU
    ap.add_argument("--csv", default=None)  # дамп per-trade (sym/dir/entry_ts/entry_px) для overlap-анализа между комбо
    a = ap.parse_args()
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe=? ORDER BY symbol", (a.break_tf,))]
    conn.close()
    if a.pairs: syms = syms[:a.pairs]
    allr = []
    import time
    t0 = time.time()
    tasks = [(s, a.zone_tf, a.break_tf, a.min_confs, a.mid_tf, a.entry_fib, a.pit_zone, a.recency, a.confs_tf) for s in syms]
    done = 0
    with Pool(processes=a.workers) as pool:
        for sym, dt, trades in pool.imap_unordered(_worker, tasks):
            allr.extend(trades)
            done += 1
            if dt > 5:
                print(f"[slow] {sym} {dt:.1f}s", flush=True)
            if done % 5 == 0:
                print(f"[runner] {done}/{len(syms)} | сделок {len(allr)} | {time.time()-t0:.0f}s", flush=True)
    if not allr:
        print("нет сделок"); return
    if a.csv:
        import csv as _csv
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=["sym", "dir", "entry_ts", "choch_ts", "entry_px",
                "target_-1", "target_-1.618", "runner_choch", "ladder", "tp_2R", "tp_3R", "ladder_run", "mfe_pct"])
            w.writeheader()
            for t in allr:
                w.writerow({k: t.get(k) for k in w.fieldnames})
        print(f"[csv] {len(allr)} сделок -> {a.csv}")
    _chain = f"{a.zone_tf}->{a.mid_tf}->{a.break_tf}" if a.mid_tf else f"{a.zone_tf}->{a.break_tf}"
    _pit_tag = (" PIT-ЗОНА(честно)" if a.pit_zone else " хиндсайт-зона") + (" +recency" if a.recency else "") + (f" confs_tf={a.confs_tf}" if a.confs_tf else "")
    print(f"\n# OKO-OTE ВЫХОД-ТЕСТ ($) — {_chain}, confs>={a.min_confs}, entry_fib={a.entry_fib},{_pit_tag}, {len(allr)} сделок, риск ${RISK_USD}/сделку\n")
    print("| выход | сумма $ | средн $/сделку | WR% | макс $ | мин $ |")
    print("|---|---|---|---|---|---|")
    for k in ("target_-1", "target_-1.618", "tp_2R", "tp_3R", "runner_choch", "ladder", "ladder_run"):
        v = np.array([t[k] for t in allr if k in t])
        if not len(v): continue
        wr = round(100 * (v > 0).mean())
        print(f"| {k} | **{v.sum():+.0f}** | {v.mean():+.2f} | {wr}% | {v.max():+.0f} | {v.min():+.0f} |")
    mfe = np.array([t["mfe_pct"] for t in allr])
    print(f"\nMFE медиана {np.median(mfe):.2f}% · ≥5% {round(100*(mfe>=5).mean())}% · ≥20% {round(100*(mfe>=20).mean())}% · max {mfe.max():.0f}%")
    print("\nДоходила ли цена до фибо-уровня до SL/maxhold (reach-rate, БЕЗ P&L):")
    for f in (-1.618, -2.0, -2.618, -3.618, -4.236):
        k = f"reach_{f}"
        v = [t[k] for t in allr if k in t]
        if v:
            print(f"  {f}: {round(100*np.mean(v))}% (n={len(v)})")
    longs = [t for t in allr if t["dir"] == "long"]; shorts = [t for t in allr if t["dir"] == "short"]
    print(f"\nlong={len(longs)} short={len(shorts)}")
    for nm, sub in (("LONG", longs), ("SHORT", shorts)):
        if len(sub) < 5: continue
        rc = np.array([t["runner_choch"] for t in sub])
        print(f"  {nm}: runner_choch сумма {rc.sum():+.0f}$ средн {rc.mean():+.2f}$ WR{round(100*(rc>0).mean())}%")

    # ── РЕШАЮЩЕЕ СРАВНЕНИЕ: A=текущий(все) vs B=HTF-bias(aligned) vs counter(против HTF) ──
    # aligned = слом LTF в сторону импульса HTF (trend-continuation, как видит OKO-SM на чарте).
    # counter = слом против HTF (текущий детектор их пропускает — против шерсти, RPL-кейс).
    def _st(sub, key):
        v = np.array([t[key] for t in sub if key in t])
        if not len(v):
            return 0.0, 0.0, 0
        return float(v.sum()), float(v.mean()), round(100 * (v > 0).mean())
    aligned = [t for t in allr if t.get("aligned")]
    counter = [t for t in allr if not t.get("aligned")]
    print("\n# A=текущий(все) · B=HTF-bias(aligned) · counter(против HTF) — выходы runner_choch / target_-1 / ladder_run")
    print("| вариант | n | runner $ | ср.$ | WR | target_-1 $ | ср.$ | WR | ladder_run $ | ср.$ | WR |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for nm, sub in (("A: все(текущий)", allr), ("B: aligned(HTF-bias)", aligned), ("counter(против HTF)", counter)):
        rs, rm, rw = _st(sub, "runner_choch")
        t1s, t1m, t1w = _st(sub, "target_-1")
        ls, lm, lw = _st(sub, "ladder_run")
        print(f"| {nm} | {len(sub)} | **{rs:+.0f}** | {rm:+.2f} | {rw}% | **{t1s:+.0f}** | {t1m:+.2f} | {t1w}% | **{ls:+.0f}** | {lm:+.2f} | {lw}% |")
    # aligned по сторонам (видеть, LONG-cont или SHORT-cont несёт)
    print("\naligned по сторонам (trend-continuation):")
    for nm in ("long", "short"):
        sub = [t for t in aligned if t["dir"] == nm]
        if len(sub) < 5:
            continue
        rs, rm, rw = _st(sub, "runner_choch")
        print(f"  {nm}-cont: n={len(sub)} runner {rs:+.0f}$ ср {rm:+.2f}$ WR{rw}%")

    # ── ЧАСТОТА (вопрос Егора «почему мало сигналов / прибыль каждый день») ──
    # aligned confs≥N сетапов/день по всему юниверсу пар (live сканит все пары одновременно).
    al_ts = []
    for t in aligned:
        try:
            al_ts.append(pd.Timestamp(t["entry_ts"]))
        except Exception:
            pass
    if al_ts:
        al_ts.sort()
        span_days = max(1, (al_ts[-1] - al_ts[0]).days)
        per_day = len(aligned) / span_days
        print(f"\nЧАСТОТА aligned confs>={a.min_confs}: {len(aligned)} сетапов / {span_days}д / {len(syms)} пар "
              f"= {per_day:.2f}/день. На 467 пар ≈ {per_day * 467 / len(syms):.2f}/день. "
              f"long-cont (чистый edge) ≈ {sum(1 for t in aligned if t['dir']=='long') / span_days * 467 / len(syms):.2f}/день")


if __name__ == "__main__":
    main()
