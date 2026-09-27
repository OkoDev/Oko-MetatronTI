# -*- coding: utf-8 -*-
"""КОРРЕКЦИЯ ПОСЛЕ ПЯТИ ВОЛН — гипотеза Егора в ЕЁ СОБСТВЕННОЙ геометрии (12.09.2026).

Егор: «если 5 волн импульса прошло — всегда есть коррекция, на любом ТФ. Эти отскоки можно
забирать всегда». Канон (LuxAlgo · elliottwave-forecast · EliteCurrenSea): коррекция после
волны 5 идёт В ТЕРРИТОРИЮ ВОЛНЫ 4, типичные уровни 0.382 и 0.618 всего импульса.

🔴 ПОЧЕМУ ЭТО НЕ БЫЛО ПРОВЕРЕНО РАНЬШЕ: наш прошлый замер фейда импульса (impulse_decay_causal)
выходил по 3×ATR-стопу и по времени 60 баров — то есть мерил ДРУГУЮ геометрию. Цель «зона
волны 4» не тестировалась ни разу.

ПРИЧИННОСТЬ (обязательна, docstring detect_elliott_impulse):
  · zigzag ПЕРЕРИСОВЫВАЕТ: из импульсов, видимых в реальном времени, доживает 27-60%;
  · лаг подтверждения ровно 6 баров;
  · без обеих поправок PF был 15.65 → 5.47 → 0.97.
  ⇒ префиксный проход: на каждом шаге детектор видит ТОЛЬКО df[:t], сделка открывается в момент
    ПЕРВОГО появления импульса, включая те, что позже исчезнут.

ГЕОМЕТРИЯ СДЕЛКИ (канон, не выдумка):
  вход  = open бара обнаружения, ПРОТИВ направления импульса;
  стоп  = за экстремум волны 5 (p5) + буфер;
  цели  = конец волны 4 (p4) · 0.382 · 0.5 · 0.618 отката импульса (p0→p5);
  время = соразмерно импульсу: 2× его длительность, не более MAXHOLD.

СЧЁТ (уроки сегодняшнего дня): единица независимости — ЭПИЗОД, не сделка. Бутстрап по эпизодам,
контроль случайным входом той же геометрии в %, хрупкость (безтоп10), охват монет.

Запуск: python wave5_correction.py [--tf 1h] [--pairs 40] [--cost 0.10]
Сохраняет rows в wave5_rows_<tf>.pkl — из них строятся картинки.
"""
from __future__ import annotations
import argparse, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

from research_harness import load, universe            # noqa: E402
from core.smc.smc_engine import zigzag_atr, detect_elliott_impulse   # noqa: E402

WARMUP = 600
STEP = 6              # = лаг подтверждения детектора
BUF = 0.0015          # буфер стопа за экстремум волны 5
MAXHOLD = 240
TGTS = ["w4", "f382", "f500", "f618"]
# Фильтры геометрии (увидены на картинках 12.09, см. комментарий в trade_one):
MIN_IMP_PCT = 3.0     # импульс мельче — цель внутри шума/костов
MAX_IMP_PCT = 40.0    # импульс крупнее — «зона волны 4» уходит в +100% и более, это не цель
MAX_GONE = 0.25       # вход не позже, чем коррекция прошла 25% импульса (иначе стоп ≫ цели)


def trade_one(df, o, h, l, c, imp, t_detect, cost):
    """Одна сделка ПРОТИВ импульса с каноническими целями. → dict | None."""
    w = imp["waves"]
    a, b = int(w[0][0]), int(w[-1][0])
    p0, p4, p5 = float(w[0][1]), float(w[4][1]), float(w[5][1])
    n = len(c)
    if t_detect >= n - 5 or b <= a:
        return None
    up = imp["direction"] == "up"          # импульс вверх → входим В ШОРТ
    e = float(o[t_detect])
    rng = abs(p5 - p0)
    if rng <= 0 or e <= 0:
        return None
    # 🔴 ДВА ФИЛЬТРА ГЕОМЕТРИИ (12.09, увидено НА КАРТИНКАХ, в таблицах было не видно):
    #  1) размер импульса. Детектор на dev=3 ловит импульсы в 50-60% хода и 1000+ баров;
    #     «конец волны 4» тогда оказывается в +127% от входа — не цель, а фантазия (RR 10-12).
    #  2) ОПОЗДАНИЕ ВХОДА. Лаг подтверждения (медиана 8 баров) съедает путь до цели: вход по
    #     0.00909 при вершине 0.0105 → стоп 15.4%, а цель всего в 6% → риск втрое больше цели.
    #     `gone` = какую долю импульса коррекция уже прошла к моменту входа.
    imp_pct = rng / p0 * 100
    if not (MIN_IMP_PCT <= imp_pct <= MAX_IMP_PCT):
        return None
    gone = abs(e - p5) / rng
    if gone > MAX_GONE:
        return None
    # стоп за экстремум волны 5
    sl = p5 * (1 + BUF) if up else p5 * (1 - BUF)
    if (up and sl <= e) or (not up and sl >= e):
        return None                         # цена уже за стопом — сделки нет
    # цели: конец волны 4 и фибо-откаты всего импульса
    tgt = {"w4": p4,
           "f382": p5 - 0.382 * rng if up else p5 + 0.382 * rng,
           "f500": p5 - 0.500 * rng if up else p5 + 0.500 * rng,
           "f618": p5 - 0.618 * rng if up else p5 + 0.618 * rng}
    # цель должна быть по ходу сделки (ниже входа для шорта)
    tgt = {k: v for k, v in tgt.items() if ((v < e) if up else (v > e))}
    if not tgt:
        return None
    hold = min(MAXHOLD, max(20, 2 * (b - a)))
    end = min(t_detect + hold, n - 1)
    sgn = -1 if up else 1                   # шорт: прибыль при падении
    res, hit = {}, {}
    pending = set(tgt)
    stop_i = None
    for j in range(t_detect, end + 1):
        if (h[j] >= sl) if up else (l[j] <= sl):
            stop_i = j
            break
        for k in list(pending):
            px = tgt[k]
            if (l[j] <= px) if up else (h[j] >= px):
                res[k] = (px - e) / e * 100 * sgn
                hit[k] = j
                pending.discard(k)
        if not pending:
            break
    sl_pnl = (sl - e) / e * 100 * sgn
    tail = (float(c[stop_i if stop_i is not None else end]) - e) / e * 100 * sgn
    row = {"dir": imp["direction"], "textbook": bool(imp.get("textbook")),
           "scale": imp.get("scale", np.nan), "w3_ext": imp.get("w3_ext"),
           "t": t_detect, "b": b, "a": a, "lag": t_detect - b,
           "entry": e, "sl": sl, "p0": p0, "p4": p4, "p5": p5,
           # все шесть точек разметки — нужны для картинки с волнами 1-2-3-4-5
           "wave_idx": [int(w[k][0]) for k in range(6)],
           "wave_px": [float(w[k][1]) for k in range(6)],
           "w2_retr": imp.get("w2_retr"), "w4_retr": imp.get("w4_retr"),
           "sl_pct": abs(e - sl) / e * 100, "stopped": stop_i is not None,
           "gone": gone,                      # доля импульса, пройденная коррекцией ДО входа
           "hold": hold, "imp_bars": b - a, "imp_pct": rng / p0 * 100}
    for k in TGTS:
        if k in tgt:
            row[f"hit_{k}"] = k in hit
            row[f"pnl_{k}"] = (res[k] if k in hit else (sl_pnl if stop_i is not None else tail)) - cost
            row[f"rr_{k}"] = abs(tgt[k] - e) / abs(e - sl)
            row[f"tgt_{k}"] = tgt[k]
        else:
            row[f"hit_{k}"] = np.nan; row[f"pnl_{k}"] = np.nan
            row[f"rr_{k}"] = np.nan; row[f"tgt_{k}"] = np.nan
    return row


def run_symbol(sym, tf, cost, rs):
    df = load(sym, tf)
    if len(df) < 1500:
        return []
    idx = df.index
    df = df.reset_index(drop=True)
    o, h, l, c = df.open.values, df.high.values, df.low.values, df.close.values
    n = len(df)
    seen, rows = set(), []
    for t in range(WARMUP, n, STEP):
        try:
            imps = detect_elliott_impulse(zigzag_atr(df.iloc[:t]))
        except Exception:
            continue
        for imp in imps:
            b = int(imp["waves"][-1][0])
            if b in seen or b >= t:
                continue
            seen.add(b)
            r = trade_one(df, o, h, l, c, imp, t, cost)
            if r is None:
                continue
            r["sym"] = sym
            r["ts"] = idx[t]
            r["year"] = int(pd.Timestamp(idx[t]).year)
            # КОНТРОЛЬ: случайный вход той же геометрии в % (±30 дней по барам)
            span = 30 * (1440 // {"15m": 15, "1h": 60, "4h": 240}[tf])
            lo_i, hi_i = max(WARMUP, t - span), min(n - 250, t + span)
            if hi_i > lo_i + 10:
                j0 = rs.randint(lo_i, hi_i)
                ce = float(o[j0])
                up = imp["direction"] == "up"
                csl = ce * (1 + r["sl_pct"] / 100) if up else ce * (1 - r["sl_pct"] / 100)
                sgn = -1 if up else 1
                for k in TGTS:
                    if not np.isfinite(r.get(f"rr_{k}", np.nan)):
                        r[f"ctl_{k}"] = np.nan; r[f"ctlhit_{k}"] = np.nan; continue
                    dist = r[f"rr_{k}"] * r["sl_pct"] / 100
                    cpx = ce * (1 - dist) if up else ce * (1 + dist)
                    end2 = min(j0 + r["hold"], n - 1)
                    hitk, stop2 = False, False
                    for j2 in range(j0, end2 + 1):
                        if (h[j2] >= csl) if up else (l[j2] <= csl):
                            stop2 = True; break
                        if (l[j2] <= cpx) if up else (h[j2] >= cpx):
                            hitk = True; break
                    if hitk:
                        r[f"ctl_{k}"] = (cpx - ce) / ce * 100 * sgn - cost
                    elif stop2:
                        r[f"ctl_{k}"] = (csl - ce) / ce * 100 * sgn - cost
                    else:
                        r[f"ctl_{k}"] = (float(c[end2]) - ce) / ce * 100 * sgn - cost
                    r[f"ctlhit_{k}"] = hitk
            rows.append(r)
    return rows


def episodes(d, gap_bars=50):
    d = d.sort_values("ts").copy()
    g = (d.groupby("sym").ts.diff().dt.total_seconds().fillna(1e9) > gap_bars * 3600).cumsum()
    d["ep"] = d.sym.astype(str) + "_" + g.astype(str)
    return d


def report(d, tf, cost):
    print(f"\n{'='*96}\nТФ {tf} · сделок {len(d)} · монет {d.sym.nunique()} · "
          f"{d.ts.min():%Y-%m-%d} → {d.ts.max():%Y-%m-%d} · кост {cost}%")
    print(f"стоп медиана {d.sl_pct.median():.2f}% · стоп-аут {d.stopped.mean()*100:.0f}% · "
          f"лаг медиана {d.lag.median():.0f} баров · импульс медиана {d.imp_pct.median():.1f}%")
    d = episodes(d)
    rows = []
    for k in TGTS:
        g = d[d[f"pnl_{k}"].notna()]
        if len(g) < 30:
            continue
        pnl = g[f"pnl_{k}"]
        ctl = g[f"ctl_{k}"] if f"ctl_{k}" in g else pd.Series(dtype=float)
        keep = pnl.sort_values(ascending=False).iloc[int(len(g) * 0.1):]
        ep = g.groupby("ep")[f"pnl_{k}"].mean()
        rs2 = np.random.RandomState(7)
        bs = [ep.sample(len(ep), replace=True, random_state=rs2.randint(1e6)).mean() for _ in range(2000)]
        lo, hi = np.percentile(bs, 2.5), np.percentile(bs, 97.5)
        rows.append({"цель": k, "RR": g[f"rr_{k}"].median(), "n": len(g),
                     "эпизодов": ep.size, "дошли%": g[f"hit_{k}"].mean() * 100,
                     "на сделку%": pnl.mean(), "медиана%": pnl.median(),
                     "WR%": (pnl > 0).mean() * 100,
                     "контроль%": ctl.mean() if len(ctl) else np.nan,
                     "к.дошли%": g[f"ctlhit_{k}"].mean() * 100 if f"ctlhit_{k}" in g else np.nan,
                     "безтоп10/сд": keep.mean(),
                     "ДИ_низ": lo, "ДИ_верх": hi, "✅": "ДА" if lo > 0 else "нет"})
    if rows:
        print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:8.3f}"))
    for col, name in (("textbook", "textbook"), ("dir", "направление импульса"), ("year", "год")):
        print(f"\n--- по {name} (цель w4):")
        t = d[d.pnl_w4.notna()].groupby(col).agg(
            n=("pnl_w4", "size"), дошли=("hit_w4", lambda x: x.mean() * 100),
            на_сделку=("pnl_w4", "mean"), медиана=("pnl_w4", "median"),
            контроль=("ctl_w4", "mean") if "ctl_w4" in d else ("pnl_w4", "size"))
        print(t.to_string(float_format=lambda x: f"{x:8.3f}"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--pairs", type=int, default=40)
    ap.add_argument("--cost", type=float, default=0.10)
    a = ap.parse_args()
    syms = universe(a.tf, n=a.pairs)
    print(f"ТФ {a.tf} · монет {len(syms)} · STEP {STEP} · WARMUP {WARMUP}", flush=True)
    rs = np.random.RandomState(20260912)
    rows = []
    for i, s in enumerate(syms, 1):
        try:
            rows += run_symbol(s, a.tf, a.cost, rs)
        except Exception as e:
            print(f"  [skip] {s}: {e}", flush=True)
        if i % 5 == 0:
            print(f"  {i}/{len(syms)} · строк {len(rows)}", flush=True)
    if not rows:
        print("НЕТ СДЕЛОК"); return
    d = pd.DataFrame(rows)
    d.to_pickle(Path(__file__).parent / f"wave5_rows_{a.tf}.pkl")
    report(d, a.tf, a.cost)


if __name__ == "__main__":
    main()
