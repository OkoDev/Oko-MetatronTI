"""Замер: кластер наших сигналов (много монет одновременно у одного источника и стороны) против исхода сделки.

Данные: subscriptions.db::simulated_trades (только чтение). Исход = чистый % (ЗАКОН №1):
profit_pct − издержки; издержки пересчитаны ЕДИНО для всей истории формулой бота
(trade_writer: 2×taker + hold_h/8×funding, config simulation.*) — до июля costs_pct в БД = 0.

Кластер K = число РАЗНЫХ монет с тем же источником и стороной:
  def A «бар»  — время регистрации, округлённое вниз до 15m (wt_sideways — 30m);
  def B «окно» — ±15 мин от времени регистрации (устойчивость к тому, что скан идёт минутами).
"""
import sqlite3, sys, json, random
from collections import defaultdict
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
DB = "file:E:/MTF BOT/CURSOR/crypto_volume_bot/subscriptions.db?mode=ro"
TAKER, FUND = 0.045, 0.01           # config.yaml simulation.taker_fee_pct / funding_est_pct
ALIAS = {"watch_list_breach": "wl_breach"}

db = sqlite3.connect(DB, uri=True, timeout=20)
rows = db.execute("""
  select id, symbol, direction, created_at, profit_pct, duration_minutes, entry_price, stop_loss,
         coalesce(nullif(source_router,''), signal_type), regime, execution_mode, features_json
  from simulated_trades
  where status in ('SL','TP','TSL') and coalesce(fakeR_quarantine,0)=0 and profit_pct is not null
""").fetchall()


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "")[:19].replace("T", " "))


T = []
seen = set()
for (tid, sym, side, ca, pp, dur, ent, sl, key, reg, mode, fj) in rows:
    key = ALIAS.get(key, key)
    t = ts(ca)
    tfm = 30 if key == "wt_sideways" else 15
    bar = t.replace(minute=(t.minute // tfm) * tfm, second=0, microsecond=0)
    d = (key, sym, side, bar)
    if d in seen:                    # один сигнал на двух счетах/режимах — одна строка
        continue
    seen.add(d)
    cost = 2 * TAKER + ((dur or 0) / 60.0 / 8.0) * FUND
    stop = abs(ent - sl) / ent * 100 if ent and sl else None
    T.append(dict(id=tid, sym=sym, side=side, t=t, bar=bar, key=key, net=pp - cost,
                  month=ca[:7], stop=stop, reg=reg or "∅", mode=mode))

# ── кластер A (бар) ──
cnt = defaultdict(set)
for r in T:
    cnt[(r["key"], r["side"], r["bar"])].add(r["sym"])
for r in T:
    r["KA"] = len(cnt[(r["key"], r["side"], r["bar"])])
# ── кластер B (окно ±15 мин) ──
by = defaultdict(list)
for r in T:
    by[(r["key"], r["side"])].append(r)
for g in by.values():
    g.sort(key=lambda r: r["t"])
    j0 = 0
    for i, r in enumerate(g):
        lo, hi = r["t"] - timedelta(minutes=15), r["t"] + timedelta(minutes=15)
        while g[j0]["t"] < lo:
            j0 += 1
        syms = set()
        j = j0
        while j < len(g) and g[j]["t"] <= hi:
            syms.add(g[j]["sym"]); j += 1
        r["KB"] = len(syms)


def stats(xs):
    n = len(xs)
    if n == 0:
        return None
    s = sorted(xs)
    wins = sum(x for x in xs if x > 0); loss = -sum(x for x in xs if x < 0)
    k = max(1, n // 10)
    top_cut = sorted(xs, reverse=True)[k:] if n >= 10 else xs
    return dict(n=n, wr=sum(x > 0 for x in xs) / n * 100, mean=sum(xs) / n, med=s[n // 2],
                pf=(wins / loss if loss else float("inf")), sum=sum(xs), sum_ex10=sum(top_cut))


def fmt(st):
    if not st:
        return "—"
    return (f"n={st['n']:5d} WR={st['wr']:4.0f}% ср={st['mean']:+6.2f} мед={st['med']:+6.2f} "
            f"PF={st['pf']:4.2f} Σ={st['sum']:+8.0f} Σбез10%={st['sum_ex10']:+8.0f}")


def perm_p(rs, kf, thr, n_perm=2000, seed=7):
    """p для (ср.кластер − ср.одиночка) при перестановке меток K внутри месяца."""
    obs_c = [r["net"] for r in rs if r[kf] >= thr]; obs_s = [r["net"] for r in rs if r[kf] == 1]
    if len(obs_c) < 30 or len(obs_s) < 30:
        return None, None
    obs = sum(obs_c) / len(obs_c) - sum(obs_s) / len(obs_s)
    bym = defaultdict(list)
    for r in rs:
        bym[r["month"]].append(r)
    rnd = random.Random(seed); ge = 0
    for _ in range(n_perm):
        c = []; s = []
        for g in bym.values():
            ks = [r[kf] for r in g]; rnd.shuffle(ks)
            for r, k in zip(g, ks):
                if k >= thr: c.append(r["net"])
                elif k == 1: s.append(r["net"])
        if c and s and abs(sum(c) / len(c) - sum(s) / len(s)) >= abs(obs):
            ge += 1
    return obs, (ge + 1) / (n_perm + 1)


keys = defaultdict(list)
for r in T:
    keys[r["key"]].append(r)

print(f"строк после чистки: {len(T)} (из {len(rows)}), месяцы {min(r['month'] for r in T)}…{max(r['month'] for r in T)}")
print("\n=== ПО ИСТОЧНИКАМ: база / одиночка K=1 / кластер K≥2 / K≥5 (def A бар) + перестановка ===")
report = []
for key, rs in sorted(keys.items(), key=lambda kv: -len(kv[1])):
    if len(rs) < 200:
        continue
    share2 = sum(r["KA"] >= 2 for r in rs) / len(rs) * 100
    print(f"\n■ {key}  (доля сделок в кластере K≥2: {share2:.0f}%, монет {len({r['sym'] for r in rs})})")
    print("   база      ", fmt(stats([r["net"] for r in rs])))
    for lab, f in [("K=1       ", lambda r: r["KA"] == 1), ("K≥2       ", lambda r: r["KA"] >= 2),
                   ("K≥5       ", lambda r: r["KA"] >= 5)]:
        print("  ", lab, fmt(stats([r["net"] for r in rs if f(r)])))
    for kf, nm in (("KA", "бар"), ("KB", "окно")):
        d, p = perm_p(rs, kf, 2)
        if d is not None:
            print(f"   Δср(K≥2 − K=1) [{nm}] = {d:+.2f} п.п., p={p:.3f}")
            report.append((key, nm, d, p, len(rs)))

print("\n=== СВОДКА Δ (K≥2 − K=1), чем меньше p, тем меньше шанс случайности ===")
for key, nm, d, p, n in sorted(report, key=lambda x: x[3]):
    print(f"  {key:18} {nm:5} Δ={d:+6.2f}  p={p:.3f}  n={n}")
print(f"\nЧисло проверок (множественность): {len(report)}")

json.dump([dict(r, t=str(r["t"]), bar=str(r["bar"])) for r in T],
          open(sys.argv[1] if len(sys.argv) > 1 else "cluster_rows.json", "w", encoding="utf-8"))
