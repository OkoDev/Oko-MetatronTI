"""КОНТРОЛЬ для финалистов из entry_lab_1h: та же ГЕОМЕТРИЯ, случайный момент.

Без контроля вердикт запрещён (law_control_group_random_entry): вариант входа может выигрывать
просто потому, что берёт больше сделок в растущем рынке. Для каждой сделки финалиста берём
5 случайных моментов ±30 дней той же монеты и проходим тем же риском/целью/горизонтом.

python entry_lab_ctl.py [процессов]
"""
import sys, glob, pickle, random
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd

ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf                       # noqa: E402
from triangle_lab import geo                      # noqa: E402

SRC = Path("G:/oko_lab/out/entry_lab_1h")
OUT = Path("G:/oko_lab/out/entry_lab_1h_ctl"); OUT.mkdir(parents=True, exist_ok=True)
FINALISTS = ("лимит 0.382 (бой)", "лимит 0.382 · ждём 48", "лимит 0.382 · ждём 24", "рынок", "лимит 0.5")
N_CTL, HOLD = 5, 96


def one(sym):
    out_p = OUT / f"{sym}.pkl"
    if out_p.exists():
        return sym, 0
    src = SRC / f"{sym}.pkl"
    if not src.exists():
        return sym, 0
    rows = [r for r in pickle.load(open(src, "rb"))["rows"] if r["вариант"] in FINALISTS]
    if not rows:
        pickle.dump([], open(out_p, "wb")); return sym, 0
    try:
        m = load_tf(sym, "1h")
    except Exception:
        return sym, 0
    if m is None or len(m) < 400:
        return sym, 0
    rs = random.Random(sum(map(ord, sym)) + 11)
    t_min, t_max = m.index[0], m.index[-1]
    out = []
    for r in rows:
        long_ = r["side"] == "LONG"
        rsk, tg = r["stop_pct"] / 100, r["tgt_pct"] / 100
        vals = []
        for _ in range(N_CTL):
            sh = rs.uniform(-30, 30)
            t = pd.Timestamp(r["signal_t"]) + pd.Timedelta(days=sh)
            if t <= t_min or t >= t_max:
                continue
            v = geo(m, t, long_, rsk, tg, HOLD)
            if v == v:
                vals.append(v)
        out.append({"sym": sym, "вариант": r["вариант"], "side": r["side"], "год": r["год"],
                    "pnl": r["pnl"], "ctl": float(np.mean(vals)) if vals else np.nan})
    pickle.dump(out, open(out_p, "wb"))
    return sym, len(out)


def report():
    R = []
    for f in glob.glob(str(OUT / "*.pkl")):
        R += pickle.load(open(f, "rb"))
    d = pd.DataFrame(R).dropna(subset=["ctl"])
    pd.set_option("display.width", 260)
    print(f"сделок с контролем: {len(d)}\n")
    g = d.groupby("вариант").agg(n=("pnl", "size"), сделка=("pnl", "mean"), контроль=("ctl", "mean"))
    g["Δr"] = (g["сделка"] - g["контроль"])
    g["сумма Δr"] = [(d[d["вариант"] == v].pnl - d[d["вариант"] == v].ctl).sum() for v in g.index]
    print("=== ВАРИАНТ против КОНТРОЛЯ (случайный вход той же геометрии ±30 дн)")
    print(g.round(2).sort_values("сумма Δr", ascending=False).to_string())
    print("\n=== Δr по сторонам")
    p = d.assign(delta=d.pnl - d.ctl).pivot_table(index="вариант", columns="side", values="delta", aggfunc="mean")
    print(p.round(2).to_string())
    print("\n=== Δr по годам")
    p2 = d.assign(delta=d.pnl - d.ctl).pivot_table(index="год", columns="вариант", values="delta", aggfunc="mean")
    print(p2.round(2).to_string())


if __name__ == "__main__":
    syms = sorted({Path(p).stem for p in glob.glob(str(SRC / "*.pkl"))})
    nproc = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    print(f"монет: {len(syms)}", flush=True)
    done = 0
    with Pool(nproc) as pool:
        for sym, k in pool.imap_unordered(one, syms):
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(syms)}", flush=True)
    report()
