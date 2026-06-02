# -*- coding: utf-8 -*-
"""ARCH-122 Phase 2 SHADOW — A/B анализ магнит-TP vs TP канала (pivot/atr).

Магнит пишется в shadow-поля (magnet_tp_*), НЕ закрывает позицию. Живое закрытие =
TP канала. По max_R_possible (peak excursion) восстанавливаем, дошла ли цена до
магнита и до pivot — и развернулась ли У МАГНИТА, не дойдя до pivot.

Главный вопрос (когда магнит БЛИЖЕ pivot):
  • развернулось у магнита (magnet_rr ≤ peak < pivot_rr) → магнит СПАС бы прибыль
  • прошло насквозь (peak ≥ pivot_rr)                   → магнит РЕЗАЛ бы прибыль
Решение о пороге dist_R принимаем по соотношению этих двух исходов.

Запуск: python scripts/magnet_shadow_ab.py [--db subscriptions.db]
"""
import argparse
import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

CLOSED = ("TP", "SL", "TSL", "EXPIRED")


def one_r(entry, original_sl, sl):
    base = original_sl if original_sl else sl
    if entry is None or base is None:
        return None
    d = abs(float(entry) - float(base))
    return d if d > 1e-9 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="subscriptions.db")
    args = ap.parse_args()

    c = sqlite3.connect(args.db)
    rows = c.execute(
        """SELECT id, symbol, signal_type, direction, status, entry_price, stop_loss,
                  original_sl, take_profit, R_multiple, max_R_possible,
                  magnet_tp_price, magnet_tp_rr, magnet_tp_src
           FROM simulated_trades
           WHERE magnet_tp_rr IS NOT NULL"""
    ).fetchall()
    c.close()

    total = len(rows)
    closed = [r for r in rows if r[4] in CLOSED and r[10] is not None]
    print(f"Сделок с магнит-тенью: {total} | закрытых с peak: {len(closed)}")
    if not closed:
        print("Нет закрытых shadow-сделок с max_R_possible — ждём накопления.")
        return

    # категории
    cat = defaultdict(list)        # имя → список (id, magnet_rr, pivot_rr, peak, R_fact)
    by_bucket = defaultdict(lambda: [0, 0])  # bucket магнит-RR → [спас, резал]

    for r in closed:
        (tid, sym, sig, direction, status, entry, sl, osl, tp,
         rmult, peak, m_price, m_rr, m_src) = r
        orr = one_r(entry, osl, sl)
        if not orr or tp is None:
            continue
        pivot_rr = abs(float(tp) - float(entry)) / orr
        m_rr = float(m_rr)
        peak = float(peak)

        if m_rr >= pivot_rr:
            # магнит ДАЛЬШЕ канала — он бы УЛУЧШИЛ RR (если достижим)
            name = "магнит ДАЛЬШЕ pivot (улучшил бы RR)"
            cat[name].append((tid, m_rr, pivot_rr, peak, rmult, sig))
        else:
            # магнит БЛИЖЕ pivot — ключевой вопрос
            if peak < m_rr:
                name = "не дошло даже до магнита"
            elif peak < pivot_rr:
                name = "★ разворот У МАГНИТА (магнит СПАС бы)"
                bk = f"{int(m_rr)}-{int(m_rr)+1}R"
                by_bucket[bk][0] += 1
            else:
                name = "прошло насквозь до pivot (магнит РЕЗАЛ бы)"
                bk = f"{int(m_rr)}-{int(m_rr)+1}R"
                by_bucket[bk][1] += 1
            cat[name].append((tid, m_rr, pivot_rr, peak, rmult, sig))

    print("\n=== ИСХОДЫ ===")
    for name in (
        "★ разворот У МАГНИТА (магнит СПАс бы)".replace("СПАс", "СПАС"),
        "прошло насквозь до pivot (магнит РЕЗАЛ бы)",
        "не дошло даже до магнита",
        "магнит ДАЛЬШЕ pivot (улучшил бы RR)",
    ):
        lst = cat.get(name, [])
        if not lst:
            continue
        avg_peak = sum(x[3] for x in lst) / len(lst)
        avg_fact = sum((x[4] or 0) for x in lst) / len(lst)
        print(f"\n{name}: n={len(lst)} | avg_peak_R={avg_peak:+.2f} | avg_R_факт(канал)={avg_fact:+.2f}")
        for tid, m_rr, p_rr, peak, rmult, sig in lst[:6]:
            print(f"   id={tid} [{sig}] магнит_RR={m_rr:.2f} pivot_RR={p_rr:.2f} peak={peak:+.2f} R_факт={(rmult or 0):+.2f}")

    # вердикт по «магнит ближе»
    spas = len(cat.get("★ разворот У МАГНИТА (магнит СПАС бы)", []))
    rezal = len(cat.get("прошло насквозь до pivot (магнит РЕЗАЛ бы)", []))
    print("\n=== ВЕРДИКТ (магнит ближе pivot) ===")
    MIN_N_VERDICT = 10   # ниже — статистика недостоверна (metrics-hygiene: n<10 = шум)
    if spas + rezal:
        share = spas / (spas + rezal) * 100
        print(f"  магнит СПАС бы: {spas} | РЕЗАЛ бы: {rezal} | доля 'спас' = {share:.0f}%")
        if spas + rezal < MIN_N_VERDICT:
            print(f"  ⏳ n={spas + rezal} < {MIN_N_VERDICT} — РАНО решать. Вердикт «live» НЕ давать, копить «магнит ближе» кейсы.")
        elif share >= 60:
            print("  → магнит-ближе ОПРАВДАН: цена чаще разворачивается у магнита. Включать live.")
        elif share <= 40:
            print("  → магнит-ближе ВРЕДИТ: цена чаще проходит до pivot. Порог dist_R поднять / только магнит-дальше.")
        else:
            print("  → неоднозначно (40-60%): копить ещё или решать по RR-бакетам ниже.")
    else:
        print("  нет кейсов 'магнит ближе' — ждём.")

    if by_bucket:
        print("\n=== по RR-бакетам магнита (спас / резал) ===")
        for bk in sorted(by_bucket):
            s, rz = by_bucket[bk]
            tot = s + rz
            print(f"  {bk}: спас={s} резал={rz} ({s/tot*100:.0f}% спас)" if tot else f"  {bk}: —")


if __name__ == "__main__":
    main()
