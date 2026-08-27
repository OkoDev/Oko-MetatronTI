# -*- coding: utf-8 -*-
"""OOS FORWARD-ТЕСТ СЕТАПОВ A/B (ширина≥61 · funding<20+возвратный) (13.08.2026, DS).

Сетапы найдены ревизией Даата 13.08 на ПОЛНОЙ истории (4h·LONG·стоп 8-12%):
  A: br24 >= 61          → PF 4.21, WR 81% (20 дней)
  B: fund_pct<20 & ac<0  → PF 2.76, WR 68% (51 день)
Риск: подгонка на полной базе. Проверяем OOS двумя способами:
  1. TRAIN/TEST по режимам: train 2022-2024 (бык+нейтраль) → test 2025-2026 (медведь).
     Пороги фиксированы из ревизии (не подбираются на train!).
  2. РОЛЛИНГ: окно 12 мес / шаг 3 мес. На train-окне решаем «взять сетап?» (PF>=1.3 и n>=30),
     результат меряем в следующем test-окне. Решение причинно.
База сравнения: LONG·стоп 8-12% без фильтров. Косты 0.35% уже в net.

Запуск: python scripts/fade_ab_forward_oos.py
"""
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DUMP = "scripts/_fade_signals_4h_enriched.csv"
COST = 0.35

d = pd.read_csv(DUMP)
d["t"] = pd.to_datetime(d["t"])
d = d[(d.side == "LONG") & (d.stop_pct > 8) & (d.stop_pct <= 12)].copy()
print(f"база LONG·стоп 8-12%: n={len(d)}")


def stat(df):
    if len(df) == 0:
        return None
    v = df.net.values
    pf = v[v > 0].sum() / abs(v[v < 0].sum()) if (v < 0).any() else 99.0
    srt = np.sort(v)
    cut = max(1, int(len(srt) * 0.10))
    return dict(n=len(v), med=float(np.median(v)), wr=100.0 * float((v > 0).mean()),
                pf=float(pf), top10=float(srt[:-cut].sum()), s=float(v.sum()))


def line(tag, df):
    st = stat(df)
    if not st:
        print(f"  {tag:<28} n=0")
        return st
    print(f"  {tag:<28} n={st['n']:>4} WR {st['wr']:5.1f}% МЕД {st['med']:+6.2f}% "
          f"PF {st['pf']:5.2f} безтоп10% {st['top10']:+8.1f} сумма {st['s']:+8.1f}")
    return st


A = d[d.br24 >= 61]
B = d[(d.fund_pct < 20) & (d.ac < 0)]

print("\n═══ 1. TRAIN/TEST по режимам ═══")
print("TRAIN 2022-2024 (бык+нейтраль):")
train = d[d.t < "2025-01-01"]
line("база", train)
line("A: ширина>=61", train[train.br24 >= 61])
line("B: fund<20+возврат", train[(train.fund_pct < 20) & (train.ac < 0)])
print("TEST 2025-2026 (медведь) — ВАЖНО:")
test = d[d.t >= "2025-01-01"]
line("база", test)
line("A: ширина>=61", test[test.br24 >= 61])
line("B: fund<20+возврат", test[(test.fund_pct < 20) & (test.ac < 0)])

print("\n═══ 2. РОЛЛИНГ 12м/шаг 3м (решение причинно) ═══")
d = d.sort_values("t")
months = pd.date_range("2023-01-01", "2026-04-01", freq="3MS")
res_base, res_a, res_b = [], [], []
for i in range(len(months) - 1):
    tr_start, tr_end = months[i], months[i] + pd.DateOffset(months=12)
    te_start, te_end = tr_end, tr_end + pd.DateOffset(months=3)
    if te_end > d.t.max():
        break
    tr = d[(d.t >= tr_start) & (d.t < tr_end)]
    te = d[(d.t >= te_start) & (d.t < te_end)]
    if len(te) < 5:
        continue
    res_base.append((te_start.date(), *[stat(te)[k] for k in ("n", "pf", "s")]))
    # A: решаем по train (PF>=1.3, n>=30) → берём A в test
    tr_a = tr[tr.br24 >= 61]
    take_a = stat(tr_a) is not None and stat(tr_a)["pf"] >= 1.3 and stat(tr_a)["n"] >= 30
    te_a = te[te.br24 >= 61] if take_a else te.iloc[0:0]
    res_a.append((te_start.date(), take_a, *(stat(te_a) or dict(n=0, pf=0, s=0)).values()))
    # B
    tr_b = tr[(tr.fund_pct < 20) & (tr.ac < 0)]
    take_b = stat(tr_b) is not None and stat(tr_b)["pf"] >= 1.3 and stat(tr_b)["n"] >= 30
    te_b = te[(te.fund_pct < 20) & (te.ac < 0)] if take_b else te.iloc[0:0]
    res_b.append((te_start.date(), take_b, *(stat(te_b) or dict(n=0, pf=0, s=0)).values()))

print(f"{'test-окно':<14}{'база':>22}{'A (решение по train)':>30}{'B (решение по train)':>30}")
for i in range(len(res_base)):
    bs, an, ap, asum = res_base[i]
    a_take, ann, apf, asum_a = res_a[i][0], res_a[i][2], res_a[i][3], res_a[i][4]
    b_take, bnn, bpf, bsum_b = res_b[i][0], res_b[i][2], res_b[i][3], res_b[i][4]
    print(f"{str(bs):<14}{an:>4}/{ap:5.2f}/{asum:+7.0f}"
          f"{('да ' if a_take else 'нет'):<4}{ann:>4}/{apf:5.2f}/{asum_a:+7.0f}"
          f"{('да ' if b_take else 'нет'):<4}{bnn:>4}/{bpf:5.2f}/{bsum_b:+7.0f}")

# сводка роллинга
def roll_sum(res):
    taken = [r for r in res if r[1]]
    if not taken:
        return None
    ns = sum(r[2] for r in taken)
    ss = sum(r[4] for r in taken)
    return dict(n=ns, s=ss, wins=sum(1 for r in taken if r[4] > 0), tot=len(taken))
ra, rb = roll_sum(res_a), roll_sum(res_b)
print("\nРоллинг-сводка (только окна, где train сказал «да»):")
print(f"  A: {ra}")
print(f"  B: {rb}")
