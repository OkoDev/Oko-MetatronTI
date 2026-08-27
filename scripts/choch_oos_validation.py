# -*- coding: utf-8 -*-
"""OOS-ВАЛИДАЦИЯ МЕХАНИКИ CHoCH → КОРРЕКЦИЯ → ВОЛНА C (17.08.2026, Даат).

Механика (найдена 15.08, `choch_pullback_real_leg.py`), на 100 монетах с 2024, 1h:
    swing-CHoCH (len50) → откат 0.236 от СТРУКТУРНОЙ ноги OKO-SM → лимитный вход
    → цель волна C ×1.0 → WR 53.8%, PF 1.15, +0.49%/сд, стоп 9.08%

🔴 ЗАЧЕМ OOS. При отборе перебирались ПЯТЬ параметров: глубина коррекции (0.236 из 4),
цель (×1.0 из 7), ТФ (1h из 4), масштаб слома (swing/internal), горизонт удержания.
Пять степеней свободы на одной выборке — классическая машина ложных находок
([[arch104_remeasured_causal_fvg]]: 14 789 паттернов, причинно живых 5 из 153).
Параметры здесь ЗАФИКСИРОВАНЫ и НЕ подбираются заново — только применяются.

Три независимых разреза:
  1. ПО МОНЕТАМ  — вселенная делится пополам детерминированно (хэш символа).
                   IS = половина, на которой механику нашли; OOS = вторая половина.
  2. ПО ВРЕМЕНИ  — 2024 (IS) против 2025–2026 (OOS).
  3. ПЕРЕКРЁСТНО — OOS-монеты × OOS-время (самый строгий: ни монет, ни периода).

Плюс контрольная проверка устойчивости: тот же прогон при СМЕЩЁННЫХ параметрах
(коррекция 0.382, цель ×1.618) — если механика реальна, соседние настройки не должны
разваливаться в ноль.

Косты: LIMIT 0.35% (вход лимитом в коррекцию налога на исполнение не платит).

Запуск:  python scripts/choch_oos_validation.py [--coins 250]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.smc.oko_sm_engine import run_structure  # noqa: E402

DB = "ohlcv_cache.db"
COST_LIMIT = 0.35
TF = "1h"
TTL = 96          # ~4 суток на 1h
WAIT = 12         # ждать коррекцию, баров
# ── ЗАФИКСИРОВАННЫЕ параметры находки (НЕ подбираются в этом скрипте) ──
PB_MAIN, K_MAIN = 0.236, 1.0
# ── соседние настройки для проверки устойчивости ──
NEIGHBORS = [(0.382, 1.0), (0.236, 1.618), (0.382, 1.618), (0.5, 1.272)]


def split_of(sym: str) -> str:
    """Детерминированное деление вселенной пополам по хэшу символа."""
    h = hashlib.md5(sym.encode()).hexdigest()
    return "IS" if int(h[:8], 16) % 2 == 0 else "OOS"


def resolve(H, L, C, j, side, entry, sl, tp, ttl):
    end = min(j + ttl, len(C) - 1)
    fl, fh = L[j + 1:end + 1], H[j + 1:end + 1]
    if len(fl) == 0:
        return None
    if side == "long":
        hs, ht = fl <= sl, fh >= tp
        lo, hi_ = (sl - entry) / entry * 100, (tp - entry) / entry * 100
        tail = (C[end] - entry) / entry * 100
    else:
        hs, ht = fh >= sl, fl <= tp
        lo, hi_ = (entry - sl) / entry * 100, (entry - tp) / entry * 100
        tail = (entry - C[end]) / entry * 100
    js = int(np.argmax(hs)) if hs.any() else 10 ** 9
    jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
    return lo if (js <= jt and js < 10 ** 9) else (hi_ if jt < 10 ** 9 else tail)


def stat(rows, days=None):
    if not rows or len(rows) < 40:
        return None
    pr = np.array([r[0] for r in rows], float)
    sp = np.array([r[1] for r in rows], float)
    net = pr - COST_LIMIT
    neg = abs(net[net < 0].sum())
    s = np.sort(net); cut = max(1, int(len(s) * 0.10))
    out = dict(n=len(rows), wr=100 * (net > 0).mean(),
               pf=(net[net > 0].sum() / neg if neg > 0 else 99.0),
               pct=float(net.mean()), stop=float(np.median(sp)),
               frag=float(s[:-cut].sum()))
    if days:
        out["freq"] = len(rows) / max(days, 1)
    return out


def show(nm, s, ind="  "):
    if not s:
        print(f"{ind}  {nm:<32} — мало данных")
        return
    mark = "🟢" if (s["wr"] > 50 and s["pct"] > 0) else ("✅" if s["wr"] > 50 else
                                                        ("💰" if s["pct"] > 0 else "🔴"))
    fr = f" безтоп10% {s['frag']:>+8.1f}" if "frag" in s else ""
    print(f"{ind}{mark}{nm:<32} n={s['n']:>5} WR {s['wr']:>5.1f}% PF {s['pf']:>5.2f} "
          f"{s['pct']:>+7.2f}%/сд стоп {s['stop']:>5.2f}%{fr}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=250)
    ap.add_argument("--since", type=int, default=2024)
    ap.add_argument("--split-year", type=int, default=2025,
                    help="год, с которого начинается временной OOS")
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    ns_is = sum(1 for s in syms if split_of(s) == "IS")
    print("═" * 118)
    print(f"OOS-ВАЛИДАЦИЯ · CHoCH → откат {PB_MAIN} → волна C ×{K_MAIN} · {TF} · "
          f"{len(syms)} монет с {a.since}")
    print(f"нога: структурная (OKO-SM swing_len=50) · держим {TTL}б · косты {COST_LIMIT}%")
    print(f"деление вселенной по хэшу символа: IS {ns_is} монет · OOS {len(syms) - ns_is}")
    print(f"временной раздел: IS < {a.split_year} · OOS ≥ {a.split_year}")
    print("═" * 118)

    # ключ: (набор_монет, период, side, вариант) → [(profit%, stop%)]
    A = defaultdict(list)
    per_sym = defaultdict(list)
    days_seen = {"IS": 0, "OOS": 0}

    for si, sym in enumerate(syms, 1):
        grp = split_of(sym)
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        raw = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                          "WHERE symbol=? AND timeframe='1h' AND time>=? ORDER BY time",
                          c, params=(sym, t0))
        c.close()
        if len(raw) < 3000:
            continue
        raw["ts"] = pd.to_datetime(raw.time, unit="ms", utc=True)
        d = raw.set_index("ts")[["open", "high", "low", "close", "volume"]]
        dd = d.reset_index(drop=True)
        try:
            st = run_structure(dd, swing_len=50, internal_len=5, record_legs=True)
        except Exception:
            continue
        legs = st.leg_history
        if not legs or len(legs) != len(dd):
            continue
        H, L, C = dd.high.values, dd.low.values, dd.close.values
        yrs = d.index.year.values
        n = len(dd)
        days_seen[grp] = max(days_seen[grp], (d.index.max() - d.index.min()).days)

        for ev in st.events:
            if ev.kind != "CHoCH" or ev.internal:      # swing-CHoCH (len50)
                continue
            i = int(ev.i)
            if i < 60 or i >= n - TTL - WAIT - 2:
                continue
            side = "long" if ev.bull else "short"
            leg = legs[i]
            if not leg or (leg["trend"] == "long") != ev.bull:
                continue
            origin, extreme = float(leg["origin"]), float(leg["extreme"])
            A_len = abs(extreme - origin)
            if A_len <= 0:
                continue
            period = "OOS" if int(yrs[i]) >= a.split_year else "IS"

            for pb, k in [(PB_MAIN, K_MAIN)] + NEIGHBORS:
                entry = extreme - A_len * pb if side == "long" else extreme + A_len * pb
                jf = None
                for j in range(i + 1, min(i + 1 + WAIT, n)):
                    if (side == "long" and L[j] <= entry) or (side == "short" and H[j] >= entry):
                        jf = j; break
                if jf is None:
                    continue
                sl = origin * 0.999 if side == "long" else origin * 1.001
                sp = abs(entry - sl) / entry * 100
                if sp <= 0 or sp > 25:
                    continue
                tp = entry + A_len * k if side == "long" else entry - A_len * k
                pr = resolve(H, L, C, jf, side, entry, sl, tp, TTL)
                if pr is None:
                    continue
                A[(grp, period, side, (pb, k))].append((pr, sp))
                # соседние настройки тоже копим в сводный ключ — иначе секция 4 пуста
                A[("ALL", "ALL", side, (pb, k))].append((pr, sp))
                if (pb, k) == (PB_MAIN, K_MAIN):
                    A[(grp, "ALL", side, (pb, k))].append((pr, sp))
                    A[("ALL", period, side, (pb, k))].append((pr, sp))
                    if side == "short":
                        per_sym[(grp, sym)].append(pr - COST_LIMIT)
        if si % 40 == 0:
            print(f"  … монет: {si}/{len(syms)}")

    main_k = (PB_MAIN, K_MAIN)
    print(f"\n{'=' * 118}")
    print(f"▌ 1. ПО МОНЕТАМ — параметры зафиксированы, вселенная поделена пополам")
    print(f"{'=' * 118}")
    for side in ("short", "long"):
        print(f"\n  --- {side.upper()} ---")
        show("IS  (монеты отбора)", stat(A[("IS", "ALL", side, main_k)]))
        show("OOS (незнакомые монеты)", stat(A[("OOS", "ALL", side, main_k)]))

    print(f"\n{'=' * 118}")
    print(f"▌ 2. ПО ВРЕМЕНИ — {a.since}–{a.split_year - 1} против {a.split_year}+")
    print(f"{'=' * 118}")
    for side in ("short", "long"):
        print(f"\n  --- {side.upper()} ---")
        show(f"IS  (< {a.split_year})", stat(A[("ALL", "IS", side, main_k)]))
        show(f"OOS (≥ {a.split_year})", stat(A[("ALL", "OOS", side, main_k)]))

    print(f"\n{'=' * 118}")
    print(f"▌ 3. ПЕРЕКРЁСТНО — незнакомые монеты И незнакомый период (самый строгий)")
    print(f"{'=' * 118}")
    for side in ("short", "long"):
        print(f"\n  --- {side.upper()} ---")
        show("IS-монеты × IS-время", stat(A[("IS", "IS", side, main_k)]))
        show("OOS-монеты × IS-время", stat(A[("OOS", "IS", side, main_k)]))
        show("IS-монеты × OOS-время", stat(A[("IS", "OOS", side, main_k)]))
        show("🎯 OOS-монеты × OOS-время", stat(A[("OOS", "OOS", side, main_k)]))

    print(f"\n{'=' * 118}")
    print(f"▌ 4. УСТОЙЧИВОСТЬ К ПАРАМЕТРАМ (SHORT, вся выборка)")
    print(f"   если механика реальна — соседние настройки не разваливаются")
    print(f"{'=' * 118}")
    for pb, k in [main_k] + NEIGHBORS:
        tag = "★ найденная" if (pb, k) == main_k else "  соседняя "
        show(f"{tag} откат {pb} цель ×{k}", stat(A[("ALL", "ALL", "short", (pb, k))]))

    print(f"\n{'=' * 118}")
    print(f"▌ 5. ОХВАТ МОНЕТ (SHORT, найденные параметры)")
    print(f"{'=' * 118}")
    for grp in ("IS", "OOS"):
        vals = {s: np.mean(v) for (g, s), v in per_sym.items() if g == grp and len(v) >= 5}
        if vals:
            pos = sum(1 for v in vals.values() if v > 0)
            print(f"  {grp:<4} плюс на {pos} из {len(vals)} монет ({100 * pos / len(vals):.0f}%) "
                  f"· медиана по монете {np.median(list(vals.values())):+.3f}%")

    print("\n" + "═" * 118)
    print("🟢 WR>50% и плюс · ✅ WR>50% но минус · 💰 плюс при WR<50% · 🔴 минус")
    print("ГЛАВНАЯ СТРОКА — «OOS-монеты × OOS-время». Если она держит PF>1, находка реальна.")
    print("═" * 118)
    return 0


if __name__ == "__main__":
    sys.exit(main())
