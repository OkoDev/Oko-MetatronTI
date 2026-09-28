# -*- coding: utf-8 -*-
"""Медиана WT (Егор 28.09: «режим ↔ WT — напоминаю про медиану WT; сделать акцент и поиграть с длиной?»).

Эталон OkoTrend_v210.pine: WT(n1=10, n2=21, hlc3); медиана = EMA(wt1, 200); «реакция» = наклон медианы за 1 бар.
Что уже было: SMA(50) по wt1 выжила OOS (27.08), EMA(200) на 15m вырождена (делит 2/98), длина 34 в схеме
«зона на старшем → медиана на младшем» не варьировалась; НАКЛОН медианы не мерился никогда.

Прибор — тот же, что потолок позиционирования (scripts/oi_info_ceiling.py): I(состояние; знак форварда),
сверх контроля-сдвига всей оси времени на тех же строках, подсадка и шум в каждом прогоне.
Состояние медианы = (wt1 выше медианы) × (медиана растёт) → 4 ячейки. Сравнение:
  · зона ±60 (то, на что сейчас смотрит теневой потребитель «WT → режим»);
  · цена (терцили прошлой доходности);
  · цена × медиана → что медиана добавляет СВЕРХ цены.
Длина — вслепую: лучшая на 2022–2024 (IS), проверка на 2025–2026 (OOS). Ось — окно в ЧАСАХ (закон: окно
детектора в минутах, а не в барах). Этап C — суррогаты IAAFT (закон проекта для WT).

python scripts/wt_median_info.py [--coins N]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oi_info_ceiling as oic  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LENS = [14, 34, 50, 89, 200, 400]
WARM = 1200                                            # прогрев EMA(400): ~3 длины
TF = {  # шаг выборки (баров) — чтобы строки не были почти копиями; горизонты — в барах ТФ
    "1h": {"ms": 3_600_000, "step": 4, "hor": {"4ч": 4, "12ч": 12, "24ч": 24, "72ч": 72},
           "r_short": 4, "r_long": 24},
    "4h": {"ms": 14_400_000, "step": 1, "hor": {"12ч": 3, "24ч": 6, "72ч": 18, "7д": 42},
           "r_short": 1, "r_long": 6},
}
oic.N_SHIFT = 12
RNG = np.random.default_rng(20260928)


def wt1_of(high, low, close) -> pd.Series:
    """WaveTrend как в OkoTrend_v210.pine (ta.ema = ewm(span, adjust=False))."""
    ap = (high + low + close) / 3
    esa = ap.ewm(span=10, adjust=False).mean()
    d = (ap - esa).abs().ewm(span=10, adjust=False).mean()
    ci = (ap - esa) / (0.015 * d)
    return ci.ewm(span=21, adjust=False).mean()


def med_state(w1: pd.Series, n: int, kind: str = "EMA") -> np.ndarray:
    med = w1.ewm(span=n, adjust=False).mean() if kind == "EMA" else w1.rolling(n).mean()
    pos = (w1 > med).astype(int)
    up = (med > med.shift(1)).astype(int)
    out = (pos * 2 + up).to_numpy()
    out[med.isna().to_numpy()] = -1
    return out


def panel(tf: str, coins: int | None) -> pd.DataFrame:
    cfg = TF[tf]
    c = sqlite3.connect(ROOT / "ohlcv_cache.db", timeout=60)
    syms = [r[0] for r in c.execute(
        "SELECT symbol FROM ohlcv_cache WHERE timeframe=? GROUP BY symbol HAVING COUNT(*) > ?", (tf, WARM + 500))]
    if coins:
        syms = syms[:coins]
    out = []
    for s in syms:
        k = pd.read_sql("SELECT time, high, low, close, volume FROM ohlcv_cache WHERE symbol=? AND timeframe=? "
                        "ORDER BY time", c, params=(s, tf))
        w1 = wt1_of(k.high, k.low, k.close)
        g = pd.DataFrame({"t": k.time, "px": k.close, "wt1": w1, "qv": k.close * k.volume})
        for n in LENS:
            g[f"EMA{n}"] = med_state(w1, n, "EMA")
        for n in (34, 50):
            g[f"SMA{n}"] = med_state(w1, n, "SMA")
        for nm, h in cfg["hor"].items():
            g[f"fwd_{nm}"] = (k.close.shift(-h) / k.close - 1) * 100          # от закрытия бара t
        g["r_s"] = (k.close / k.close.shift(cfg["r_short"]) - 1) * 100
        g["r_l"] = (k.close / k.close.shift(cfg["r_long"]) - 1) * 100
        g["qv30"] = g.qv.rolling(int(30 * 86_400_000 / cfg["ms"]), min_periods=50).median()
        flat = (k.high.rolling(24).max() == k.low.rolling(24).min()).to_numpy()   # цена стоит сутки+ → WT вырожден
        g = g[~flat]
        g = g.iloc[WARM:]
        g = g[(g.t // cfg["ms"]) % cfg["step"] == 0]
        g["symbol"] = s.split("/")[0]
        out.append(g)
    c.close()
    p = pd.concat(out, ignore_index=True)
    p["hr"] = (p.t // cfg["ms"] // cfg["step"]).astype(int)
    p["year"] = pd.to_datetime(p.t, unit="ms").dt.year
    return p


def states(p: pd.DataFrame, lens_keys: list[str], mid_h: str) -> dict:
    def combo(*parts):
        code, bad, width = np.zeros(len(p), int), np.zeros(len(p), bool), 1
        for x, k in parts:
            bad |= x < 0
            code = code * k + np.maximum(x, 0)
            width *= k
        code[bad] = -1
        return code, width

    price = (oic.terciles(p.r_s), 3), (oic.terciles(p.r_l), 3)
    zone = (np.select([p.wt1 < -60, p.wt1 > 60], [0, 2], 1), 3)
    f = p[f"fwd_{mid_h}"].to_numpy()
    plant = np.where(np.isnan(f), -1, (f > 0).astype(int) ^ (RNG.random(len(p)) < 0.4))
    st = {"шум 4 ячейки (контроль)": combo((RNG.integers(0, 4, len(p)), 4)),
          f"подсадка {mid_h} (контроль)": (plant.astype(int), 2),
          "цена": combo(*price),
          "зона ±60 (сейчас в тени)": combo(zone)}
    for k in lens_keys:
        st[f"медиана {k}"] = combo((p[k].to_numpy(), 4))
        st[f"цена × медиана {k}"] = combo(*price, (p[k].to_numpy(), 4))
    return st


def short(R: pd.DataFrame) -> pd.DataFrame:
    return R[["срез", "гор", "состояние", "сверх_сдвига", "p_сдвиг", "экв_точн", "нужно"]]


def run_tf(tf: str, coins: int | None) -> None:
    cfg = TF[tf]
    oic.HORIZONS = cfg["hor"]
    mid_h = list(cfg["hor"])[1]
    P = panel(tf, coins)
    print(f"\n{'=' * 30} ТФ {tf} {'=' * 30}")
    print(f"строк {len(P):,} (шаг {cfg['step']} бар) · монет {P.symbol.nunique()} · "
          f"{pd.to_datetime(P.t.min(), unit='ms'):%Y-%m-%d} → {pd.to_datetime(P.t.max(), unit='ms'):%Y-%m-%d}")
    reg = []
    for y, g in P.groupby("year"):
        gg = g.sort_values("t")
        ch = gg.groupby("symbol").px.last() / gg.groupby("symbol").px.first() - 1
        reg.append({"год": y, "монет": g.symbol.nunique(), "медиана монеты %": ch.median() * 100,
                    "растущих %": (ch > 0).mean() * 100})
    print(pd.DataFrame(reg).round(1).to_string(index=False))
    split = [w for w in P.columns if w.startswith(("EMA", "SMA"))]
    for k in split:                                                    # сколько времени wt1 над медианой
        pos = P[k][P[k] >= 0] // 2
        print(f"  {k}: wt1 над медианой {pos.mean() * 100:.0f}% · медиана растёт {(P[k][P[k] >= 0] % 2).mean() * 100:.0f}%")

    lens_keys = [f"EMA{n}" for n in LENS] + ["SMA34", "SMA50"]
    IS = P[P.year <= 2024].reset_index(drop=True)
    OOS = P[P.year >= 2025].reset_index(drop=True)
    R = pd.concat([oic.measure(IS, states(IS, lens_keys, mid_h), "IS 2022-24", False),
                   oic.measure(OOS, states(OOS, lens_keys, mid_h), "OOS 2025-26", False)], ignore_index=True)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print("\n=== IS 2022-24 и OOS 2025-26: сверх контроля-сдвига, бит ===")
    print(short(R).round(5).to_string(index=False))

    isr = R[(R.срез == "IS 2022-24") & R.состояние.str.startswith("медиана ")]
    best = isr.groupby("состояние").сверх_сдвига.mean().idxmax().replace("медиана ", "")
    print(f"\n🔑 лучшая длина по IS (средняя по горизонтам): {best} · эталон EMA200")

    keep = sorted({best, "EMA200"})
    res = []
    for y in sorted(P.year.unique()):
        sub = P[P.year == y].reset_index(drop=True)
        res.append(oic.measure(sub, states(sub, keep, mid_h), f"{y}", False))
    liq = P.qv30 >= P.groupby("hr").qv30.transform("median")
    for nm, m in {"ликвидные": liq, "неликвидные": ~liq}.items():
        sub = P[m.to_numpy()].reset_index(drop=True)
        res.append(oic.measure(sub, states(sub, keep, mid_h), nm, False))
    R2 = pd.concat(res, ignore_index=True)
    R2 = R2[~R2.состояние.str.contains("контроль") | R2.состояние.str.startswith("шум")]
    print(f"\n=== СРЕЗЫ (годы · ликвидность) для {keep}: сверх контроля-сдвига, бит ===")
    print(short(R2).round(5).to_string(index=False))

    print(f"\n=== НАПРАВЛЕНИЕ ({best}, горизонт {mid_h}): форвард % по 4 состояниям — обе стороны, по годам ===")
    names = {0: "под медианой · медиана падает", 1: "под медианой · растёт",
             2: "над медианой · падает", 3: "над медианой · растёт"}
    fw = f"fwd_{mid_h}"
    rel = P[fw] - P.groupby("hr")[fw].transform("median")
    D = P.assign(st=P[best].map(names), rel=rel).dropna(subset=[fw, "st"])
    D = D[D[fw] != 0]                                                   # ничьи — как в measure()
    print(D.groupby(["year", "st"]).agg(n=(fw, "size"), ср=(fw, "mean"), мед=(fw, "median"),
                                        вверх=(fw, lambda v: (v > 0).mean() * 100),
                                        отн_мед=("rel", "median")).round(3).to_string())
    R.to_csv(f"G:/oko_lab/out/wt_median_info_{tf}.csv", index=False, encoding="utf-8")
    return best


def iaaft(x, iters=12):
    """Как scripts/_archive/.../surrogate_iaaft.py: сохраняет спектр и распределение, рвёт фазы."""
    n = len(x)
    xs, amp = np.sort(x), np.abs(np.fft.rfft(x))
    y = RNG.permutation(x)
    for _ in range(iters):
        y = np.fft.irfft(amp * np.exp(1j * np.angle(np.fft.rfft(y))), n)
        y = xs[np.argsort(np.argsort(y))]
    return y


def surrogate_test(tf: str, keys: list[str], n_coins: int = 30, n_sur: int = 5) -> None:
    """I(медиана; знак форварда) на реальных рядах против IAAFT-рядов. Обе ветки строятся из CLOSE
    (у суррогата нет high/low) — иначе реальная ветка несла бы внутрибаровые экстремумы."""
    cfg = TF[tf]
    h = list(cfg["hor"].values())[1]
    c = sqlite3.connect(ROOT / "ohlcv_cache.db", timeout=60)
    syms = [r[0] for r in c.execute(
        "SELECT symbol FROM ohlcv_cache WHERE timeframe=? GROUP BY symbol ORDER BY COUNT(*) DESC LIMIT ?",
        (tf, n_coins))]
    real, sur = {k: [] for k in keys}, {k: [[] for _ in range(n_sur)] for k in keys}

    def collect(close: pd.Series, bucket):
        w1 = wt1_of(close, close, close)
        y = np.sign(close.shift(-h) - close).to_numpy()
        for k in keys:
            n = int(k[3:])
            s = med_state(w1, n, k[:3])
            ok = ((np.arange(len(close)) >= WARM) & (np.arange(len(close)) % cfg["step"] == 0) & (s >= 0)
                  & ~np.isnan(y) & (y != 0))                                  # ничьи исключены в обеих ветках
            bucket(k).append(np.c_[s[ok], (y[ok] > 0).astype(int)])

    for s in syms:
        close = pd.read_sql("SELECT close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
                            c, params=(s, tf)).close
        collect(close, lambda k: real[k])
        lr = np.diff(np.log(close.to_numpy()))
        for j in range(n_sur):
            sc = pd.Series(close.iloc[0] * np.exp(np.r_[0, np.cumsum(iaaft(lr))]))
            collect(sc, lambda k, j=j: sur[k][j])
    c.close()
    print(f"\n=== СУРРОГАТЫ IAAFT ({tf}, {len(syms)} ликвидных монет, {n_sur} суррогатов, горизонт {h} бар) ===")
    for k in keys:
        a = np.vstack(real[k])
        ir = oic.mi(a[:, 0], a[:, 1], 4)
        isur = [oic.mi(np.vstack(b)[:, 0], np.vstack(b)[:, 1], 4) for b in sur[k]]
        print(f"  {k}: реальные {ir:.5f} · суррогаты {np.round(isur, 5).tolist()} · "
              f"реальные выше {sum(ir > x for x in isur)}/{n_sur}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int)
    a = ap.parse_args()
    for tf in ("1h", "4h"):
        best = run_tf(tf, a.coins)
        surrogate_test(tf, sorted({best, "EMA200"}))
