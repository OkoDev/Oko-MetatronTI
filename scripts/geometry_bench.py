# -*- coding: utf-8 -*-
"""СТЕНД ГЕОМЕТРИИ: ВСЕ структурные стопы × ВСЕ структурные цели (05.09.2026).

Егор: «зачем нам структура рынка, если стоп ставится просто фиксированный? Мы ищем волны,
зоны для входа, а после выставляем стоп неструктурный и цели непонятные. А у нас есть
магниты, фибоначчи, разрывы, неэффективности, конфлюэнции — всё живёт в Кубе, а мы смотрим
вечно в один угол. Не братья вилку и нож, а строить дом.»

Стенд отвечает на вопрос, который мы ни разу не задавали целиком:
    КАКАЯ СТРУКТУРА ДЕРЖИТ СТОП и КАКАЯ СТРУКТУРА ДАЁТ ДОСТИЖИМУЮ ЦЕЛЬ — и какие ПАРЫ работают.

Вход берётся ФАКТИЧЕСКИЙ боевой (символ/время/сторона) — меняется только геометрия выхода.
Уровни считаются ОДИН раз на символ по всей истории (векторно), затем читаются на баре входа.

🔴 ОБЯЗАТЕЛЬНОЕ (законы проекта):
  · причинность — все уровни только из ПРОШЛЫХ баров, свинг подтверждён через `length`;
  · санитайзер цен БД↔кэш ([[law_check_db_cache_price_match]]);
  · косты явной ставкой, счёт в % ЦЕНЫ, не в R ([[principle_measure_pct_not_r_LAW]]);
  · контроль = случайный вход той же геометрии в ТОМ ЖЕ окне;
  · слепая проверка: монеты делятся на IS/OOS, отбор на IS → одна проверка на OOS;
  · множественность названа явно (число ячеек сетки).
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from research_harness import load                      # noqa: E402

COST = 0.35
SW_LEN = 20            # длина свингов (та же, что у OTE-семьи в swing_bridge)
HOLDS = {"6ч": 24, "24ч": 96}


# ─────────────────────────── СТРУКТУРНЫЕ УРОВНИ ───────────────────────────
def build_levels(df: pd.DataFrame) -> dict:
    """Все структурные уровни на КАЖДОМ баре. Только прошлое.

    Возвращает {имя: массив длины n} — цена уровня (nan, если нет).
    """
    n = len(df)
    H, L, C = df.high.values, df.low.values, df.close.values
    out: dict[str, np.ndarray] = {}

    # 1. SWING (эталонные свинги LuxAlgo): ближайший подтверждённый выше / ниже цены
    from core.smc.smc_engine import confirmed_swings
    sw_hi = np.full(n, np.nan)
    sw_lo = np.full(n, np.nan)
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    born: dict[int, list] = {}
    for idx, price, kind in confirmed_swings(df, SW_LEN):
        b = int(idx) + SW_LEN                      # бар ПОДТВЕРЖДЕНИЯ
        if b < n:
            born.setdefault(b, []).append((float(price), kind))
    for i in range(n):
        for price, kind in born.get(i, ()):
            (highs if kind == "H" else lows).append((i, price))
        c = C[i]
        up = [p for _, p in highs if p > c]
        dn = [p for _, p in lows if p < c]
        if up:
            sw_hi[i] = min(up)
        if dn:
            sw_lo[i] = max(dn)
    out["swing"] = np.where(np.isnan(sw_hi), np.nan, sw_hi)      # цель для long
    out["swing_lo"] = sw_lo                                      # стоп для long

    # 2. ДИАПАЗОН: экстремумы окна (строго прошлые бары)
    for w in (48, 96, 288):
        out[f"range{w}_hi"] = pd.Series(H).rolling(w).max().shift(1).values
        out[f"range{w}_lo"] = pd.Series(L).rolling(w).min().shift(1).values

    # 3. ATR-уровни от цены (волатильностный стоп/цель)
    from core.smc.impulse_fib import _atr
    atr = _atr(df).values
    for k in (1.5, 2.5, 4.0):
        out[f"atr{k}_up"] = C + k * atr
        out[f"atr{k}_dn"] = C - k * atr

    # 4. ЛИКВИДНОСТЬ: кластеры свингов (онлайн, как в swing_bridge.etl_liquidity)
    liq_up = np.full(n, np.nan)
    liq_dn = np.full(n, np.nan)
    zones: list[list] = []
    for i in range(n):
        for price, kind in born.get(i, ()):
            for z in zones:
                if z[2] == kind and z[0] > 0 and abs(price - z[0]) / z[0] * 100 <= 0.3:
                    z[0] = (z[0] * z[1] + price) / (z[1] + 1)
                    z[1] += 1
                    break
            else:
                zones.append([price, 1, kind])
        alive = []
        for z in zones:
            tol = z[0] * 0.003
            if z[2] == "H" and H[i] > z[0] + tol:
                continue
            if z[2] == "L" and L[i] < z[0] - tol:
                continue
            alive.append(z)
        zones = alive
        c = C[i]
        up = [z[0] for z in zones if z[2] == "H" and z[0] > c]
        dn = [z[0] for z in zones if z[2] == "L" and z[0] < c]
        if up:
            liq_up[i] = min(up)
        if dn:
            liq_dn[i] = max(dn)
    out["liq_up"] = liq_up
    out["liq_dn"] = liq_dn

    # 5. ПИВОТЫ дневные (PP/R1/S1) — прошлый ЗАКРЫТЫЙ день
    d = df.resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    if len(d) > 2:
        pp = (d.high + d.low + d.close) / 3.0
        piv = pd.DataFrame({"PP": pp, "R1": 2 * pp - d.low, "S1": 2 * pp - d.high,
                            "R2": pp + (d.high - d.low), "S2": pp - (d.high - d.low)}).shift(1)
        piv = piv.reindex(df.index, method="ffill")
        for k in piv.columns:
            out[f"piv_{k}"] = piv[k].values

    # 6. МАГНИТЫ: ближайший круглый (психологический) уровень сверху и снизу
    mag_up = np.full(n, np.nan)
    mag_dn = np.full(n, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        step = np.power(10.0, np.floor(np.log10(np.where(C > 0, C, np.nan))) - 1.0)
    for i in range(n):
        s = step[i]
        if not (s == s) or s <= 0:
            continue
        mag_up[i] = np.ceil(C[i] / s) * s
        mag_dn[i] = np.floor(C[i] / s) * s
        if mag_up[i] <= C[i]:
            mag_up[i] += s
        if mag_dn[i] >= C[i]:
            mag_dn[i] -= s
    out["magnet_up"] = mag_up
    out["magnet_dn"] = mag_dn

    # 7. ФИБО-РАСШИРЕНИЯ последнего импульса (origin→extreme, только прошлое)
    fib_up = np.full(n, np.nan)
    fib_dn = np.full(n, np.nan)
    orig_lo = np.full(n, np.nan)
    orig_hi = np.full(n, np.nan)
    last_h = last_l = np.nan
    for i in range(n):
        for price, kind in born.get(i, ()):
            if kind == "H":
                last_h = price
            else:
                last_l = price
        if last_h == last_h and last_l == last_l and last_h > last_l:
            amp = last_h - last_l
            fib_up[i] = last_h + 0.618 * amp        # расширение вверх
            fib_dn[i] = last_l - 0.618 * amp
            orig_lo[i] = last_l                      # origin импульса вверх
            orig_hi[i] = last_h
    out["fib_ext_up"] = fib_up
    out["fib_ext_dn"] = fib_dn
    out["origin_lo"] = orig_lo
    out["origin_hi"] = orig_hi
    return out


# источники стопа и цели: (имя, ключ_для_long, ключ_для_short)
STOPS = [
    ("swing",     "swing_lo",    "swing"),
    ("origin",    "origin_lo",   "origin_hi"),
    ("liq",       "liq_dn",      "liq_up"),
    ("range48",   "range48_lo",  "range48_hi"),
    ("range96",   "range96_lo",  "range96_hi"),
    ("atr1.5",    "atr1.5_dn",   "atr1.5_up"),
    ("atr2.5",    "atr2.5_dn",   "atr2.5_up"),
    ("atr4.0",    "atr4.0_dn",   "atr4.0_up"),
]
TARGETS = [
    ("swing",     "swing",       "swing_lo"),
    ("liq",       "liq_up",      "liq_dn"),
    ("magnet",    "magnet_up",   "magnet_dn"),
    ("range96",   "range96_hi",  "range96_lo"),
    ("range288",  "range288_hi", "range288_lo"),
    ("piv_R1",    "piv_R1",      "piv_S1"),
    ("piv_R2",    "piv_R2",      "piv_S2"),
    ("fib_ext",   "fib_ext_up",  "fib_ext_dn"),
    ("atr4.0",    "atr4.0_up",   "atr4.0_dn"),
]
RR_TARGETS = [1.0, 2.0, 3.0]          # цели, кратные стопу — как контроль структуре


def simulate(H, L, C, pos, e, d, sl, tp, hold):
    """Что сработало раньше — стоп или цель. Внутри бара приоритет СТОПУ (консервативно)."""
    lo, hi = L[pos:pos + hold], H[pos:pos + hold]
    if len(lo) == 0:
        return None
    hit_sl = (lo <= sl) if d > 0 else (hi >= sl)
    hit_tp = (hi >= tp) if d > 0 else (lo <= tp)
    i_sl = int(np.argmax(hit_sl)) if hit_sl.any() else 10 ** 9
    i_tp = int(np.argmax(hit_tp)) if hit_tp.any() else 10 ** 9
    if i_sl == 10 ** 9 and i_tp == 10 ** 9:
        return (float(C[min(pos + hold, len(C) - 1)]) - e) / e * 100.0 * d
    if i_sl <= i_tp:
        return (sl - e) / e * 100.0 * d
    return (tp - e) / e * 100.0 * d


def main() -> int:
    ap = argparse.ArgumentParser(description="Стенд геометрии: структурные стопы × цели")
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--limit", type=int, default=6000)
    ap.add_argument("--cost", type=float, default=COST)
    ap.add_argument("--side", default="both", choices=["both", "LONG", "SHORT"])
    ap.add_argument("--min-n", type=int, default=80)
    ap.add_argument("--max-stop", type=float, default=15.0, help="отсечь абсурдные стопы, %%")
    a = ap.parse_args()

    c = sqlite3.connect(str(ROOT / "subscriptions.db"))
    c.row_factory = sqlite3.Row
    where_side = "" if a.side == "both" else f" AND direction='{a.side}'"
    tr = [dict(r) for r in c.execute(
        f"""SELECT symbol, direction, entry_price, created_at, signal_type
            FROM simulated_trades
            WHERE execution_mode='VST' AND status NOT IN ('OPEN') AND entry_price>0{where_side}
              AND created_at > datetime('now','-{a.days} day')
            ORDER BY RANDOM() LIMIT {a.limit}""")]
    c.close()

    n_cells = len(STOPS) * (len(TARGETS) + len(RR_TARGETS)) * len(HOLDS)
    print(f"СТЕНД ГЕОМЕТРИИ · входов {len(tr)} · косты {a.cost}% · сторона {a.side}")
    print(f"источников стопа {len(STOPS)} × целей {len(TARGETS) + len(RR_TARGETS)} × "
          f"горизонтов {len(HOLDS)} = 🔴 {n_cells} ЯЧЕЕК (множественность названа)\n")

    by: dict[str, list] = {}
    for t in tr:
        by.setdefault(t["symbol"].split(":")[0], []).append(t)

    rng = np.random.default_rng(29)
    rows = []
    t0 = time.time()
    done = 0
    for sym, items in by.items():
        try:
            df = load(sym, "15m")
        except Exception:                                   # noqa: BLE001
            continue
        if df is None or len(df) < 700:
            continue
        # 🔴 ОКНО: build_levels растёт квадратично (20k баров = 1.7 с, 127k = минуты).
        # Сделки лежат в последних  сутках → держим ровно нужный хвост + запас.
        _need = a.days * 96 + 1500
        if len(df) > _need:
            df = df.tail(_need)
        try:
            LV = build_levels(df)
        except Exception as e:                              # noqa: BLE001
            continue
        idx, H, L, C = df.index, df.high.values, df.low.values, df.close.values
        oos = int(hashlib.md5(sym.encode()).hexdigest(), 16) % 2 == 1
        for t in items:
            try:
                ts = pd.Timestamp(t["created_at"], tz="UTC")
            except Exception:                               # noqa: BLE001
                continue
            p = int(idx.searchsorted(ts))
            if p <= 300 or p >= len(C) - max(HOLDS.values()) - 1:
                continue
            e = float(t["entry_price"])
            if abs(float(C[p]) - e) / e * 100.0 > 5.0:      # санитайзер данных
                continue
            d = 1 if t["direction"] == "LONG" else -1
            base = dict(sym=sym, oos=oos, st=t["signal_type"], dir=t["direction"])
            for s_name, k_long, k_short in STOPS:
                key = k_long if d > 0 else k_short
                sl = LV.get(key, np.full(len(C), np.nan))[p]
                if not (sl == sl):
                    continue
                # стоп обязан быть с ПРАВИЛЬНОЙ стороны и разумного размера
                if (d > 0 and sl >= e) or (d < 0 and sl <= e):
                    continue
                sp = abs(e - sl) / e * 100.0
                if not (0.15 <= sp <= a.max_stop):
                    continue
                for t_name, tk_long, tk_short in TARGETS:
                    tkey = tk_long if d > 0 else tk_short
                    tp = LV.get(tkey, np.full(len(C), np.nan))[p]
                    if not (tp == tp):
                        continue
                    if (d > 0 and tp <= e) or (d < 0 and tp >= e):
                        continue
                    for h_name, hold in HOLDS.items():
                        r = simulate(H, L, C, p, e, d, sl, tp, hold)
                        if r is not None:
                            rows.append({**base, "SL": s_name, "TP": t_name, "H": h_name,
                                         "sp": sp, "r": r - a.cost})
                for rr in RR_TARGETS:                        # цель кратная стопу — контроль
                    tp = e * (1 + d * sp * rr / 100.0)
                    for h_name, hold in HOLDS.items():
                        r = simulate(H, L, C, p, e, d, sl, tp, hold)
                        if r is not None:
                            rows.append({**base, "SL": s_name, "TP": f"RR{rr:.0f}", "H": h_name,
                                         "sp": sp, "r": r - a.cost})
            # контроль: случайный вход в том же окне, геометрия swing×magnet 6ч
            q = int(np.clip(p + rng.integers(-96, 97), 300, len(C) - max(HOLDS.values()) - 1))
            sl_c = LV["swing_lo"][q] if d > 0 else LV["swing"][q]
            tp_c = LV["magnet_up"][q] if d > 0 else LV["magnet_dn"][q]
            if sl_c == sl_c and tp_c == tp_c:
                ec = float(C[q])
                if ((d > 0 and sl_c < ec < tp_c) or (d < 0 and tp_c < ec < sl_c)):
                    r = simulate(H, L, C, q, ec, d, sl_c, tp_c, HOLDS["6ч"])
                    if r is not None:
                        rows.append({**base, "SL": "КОНТРОЛЬ", "TP": "КОНТРОЛЬ", "H": "6ч",
                                     "sp": abs(ec - sl_c) / ec * 100.0, "r": r - a.cost})
        done += 1
        if done % 25 == 0:
            print(f"  ... монет {done} · строк {len(rows)} · {time.time()-t0:.0f}с", flush=True)

    R = pd.DataFrame(rows)
    if R.empty:
        print("🔴 нет данных")
        return 1
    R.to_parquet(ROOT / "cache" / "geometry_bench.parquet")
    ctrl = R[R.SL == "КОНТРОЛЬ"]
    R = R[R.SL != "КОНТРОЛЬ"]
    n_tr = R.groupby(["sym", "st"]).size().shape[0]
    print(f"\nсобрано: {len(R):,} строк · {R.sym.nunique()} монет · ячеек с данными "
          f"{R.groupby(['SL','TP','H']).ngroups}")
    if len(ctrl):
        print(f"КОНТРОЛЬ (случайный вход, swing×magnet, 6ч): n={len(ctrl)} "
              f"медиана={ctrl.r.median():+.3f}% среднее={ctrl.r.mean():+.3f}%\n")

    # ── карта: медиана по ячейкам, горизонт 6ч ─────────────────────────
    for h in HOLDS:
        sub = R[R.H == h]
        piv_m = sub.pivot_table(index="SL", columns="TP", values="r", aggfunc="median")
        piv_n = sub.pivot_table(index="SL", columns="TP", values="r", aggfunc="size")
        cols = [c for c in piv_m.columns if piv_n[c].sum() >= a.min_n]
        print("=" * (18 + 11 * len(cols)))
        print(f"КАРТА · горизонт {h} · МЕДИАНА net % (ячейки с n<{a.min_n} скрыты)")
        print("=" * (18 + 11 * len(cols)))
        print(f"{'стоп \\ цель':16s}" + "".join(f"{c:>11}" for c in cols))
        for i in piv_m.index:
            cells = ""
            for cc in cols:
                v, nn = piv_m.loc[i, cc], piv_n.loc[i, cc]
                cells += f"{v:>+10.3f}%" if (nn == nn and nn >= a.min_n) else f"{'—':>11}"
            print(f"{i:16s}{cells}")
        print()

    # ── слепая проверка: отбор на IS, одна проверка на OOS ─────────────
    print("=" * 104)
    print("СЛЕПАЯ ПРОВЕРКА: лучшие ячейки отобраны на ПОЛОВИНЕ монет (IS) → проверены на другой (OOS)")
    print("=" * 104)
    IS, OOS = R[~R.oos], R[R.oos]
    g_is = IS.groupby(["SL", "TP", "H"]).r.agg(["median", "size"])
    g_is = g_is[g_is["size"] >= a.min_n].sort_values("median", ascending=False)
    if g_is.empty:
        print("   на IS нет ячеек с достаточным n")
        return 0
    print(f"{'стоп':10s} {'цель':10s} {'гор.':5s} {'IS медиана':>12} {'IS n':>7} "
          f"{'OOS медиана':>13} {'OOS n':>7} {'OOS среднее':>12} {'OOS WR':>8}")
    for (sl_, tp_, h_), row in g_is.head(10).iterrows():
        o = OOS[(OOS.SL == sl_) & (OOS.TP == tp_) & (OOS.H == h_)]
        if len(o) < 30:
            print(f"{sl_:10s} {tp_:10s} {h_:5s} {row['median']:>+11.3f}% {int(row['size']):>7} "
                  f"{'мало':>13}")
            continue
        print(f"{sl_:10s} {tp_:10s} {h_:5s} {row['median']:>+11.3f}% {int(row['size']):>7} "
              f"{o.r.median():>+12.3f}% {len(o):>7} {o.r.mean():>+11.3f}% {100*(o.r>0).mean():>7.1f}%")
    print(f"\n🔴 множественность: {n_cells} ячеек в сетке. Ячейка «лучшая на IS» ожидаемо теряет "
          f"на OOS — смотреть надо, ОСТАЁТСЯ ли она положительной и бьёт ли контроль.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
