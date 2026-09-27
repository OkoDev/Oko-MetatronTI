# -*- coding: utf-8 -*-
"""HYP-7: потолок информации в слое ПОЗИЦИОНИРОВАНИЯ (OI, фандинг) — тем же прибором, что потолок
гиперкуба 09.09 (I(ячейка; знак форварда) = верхняя граница для ЛЮБОГО правила на этих признаках).

Главный вопрос: добавляет ли OI информацию СВЕРХ цены → ΔI = I(цена × OI) − I(цена).
Второй: предсказывает ли OI, какие монеты ОБГОНЯТ рынок (знак хода относительно медианы часа).

Данные: oko_feed/external_data.db::oi_history (Binance fapi, поллер oi-fast, с 04.09.2026). Причинность
(scripts/oi_fast_poller.py): oi_d15 = OI сейчас / 15 опросов назад; oi_d1d = от первого замера суток UTC;
funding — текущая ставка; px — цена в момент снимка. Форвард — px того же ряда через h часов.

Контроли:
  shuffle — перемешанный знак форварда (как 09.09; на коротком окне ЗАВЫШАЕТ находку);
  shift   — сдвиг ВСЕЙ оси времени на одно и то же число часов для всех монет (≥48 ч, по кругу):
            сохраняет автокорреляцию и общий рыночный фактор, рвёт только привязку к моменту.
            Сверх контроля считается против shift; p = доля сдвигов с I ≥ фактической.

python scripts/oi_info_ceiling.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "oko_feed" / "external_data.db"
HORIZONS = {"1ч": 1, "4ч": 4, "12ч": 12, "24ч": 24}
COST = 0.35                     # как 09.09: косты на круг, % цены
N_SHIFT = 30
RNG = np.random.default_rng(20260927)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def mi(x: np.ndarray, y: np.ndarray, nx: int, ny: int = 2) -> float:
    """Взаимная информация I(X;Y), бит (как info_ceiling.py 09.09)."""
    ok = (x >= 0) & (y >= 0)
    x, y = x[ok], y[ok]
    joint = np.bincount(x * ny + y, minlength=nx * ny).reshape(nx, ny) / len(x)
    px, py = joint.sum(1, keepdims=True), joint.sum(0, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        return float(np.nansum(joint * np.log2(joint / (px * py))))


def eq_accuracy(i_bits: float) -> float:
    """Точность, которую даёт ТОЛЬКО информация сверх контроля: 1 − H(m) = I (база 50/50).
    🔴 27.09: версия 09.09 решала H(Y) − H(m) = I и на перекошенном окне включала базовую долю роста
    («всегда лонг» на бычьем сентябре ≈ 55%) — это бета режима, а не информация признака."""
    lo, hi = 0.5, 0.99
    for _ in range(40):
        m = (lo + hi) / 2
        hm = -(m * np.log2(m) + (1 - m) * np.log2(1 - m))
        lo, hi = (lo, m) if 1 - hm > i_bits else (m, hi)
    return (lo + hi) / 2 * 100


def terciles(s: pd.Series) -> np.ndarray:
    out = pd.qcut(s.rank(method="first"), 3, labels=False)
    return out.fillna(-1).astype(int).to_numpy()


def load() -> pd.DataFrame:
    c = sqlite3.connect(DB, timeout=60)
    df = pd.read_sql("SELECT symbol, ts, px, oi_d15, oi_d1d, funding FROM oi_history WHERE px > 0", c)
    c.close()
    return df.sort_values(["symbol", "ts"]).reset_index(drop=True)


def inventory(df: pd.DataFrame) -> None:
    t = pd.to_datetime(df.ts, unit="s")
    gap = df.groupby("symbol").ts.diff().dropna()
    print("=== ИНВЕНТАРИЗАЦИЯ ===")
    print(f"строк {len(df):,} · монет {df.symbol.nunique()} · {t.min():%Y-%m-%d %H:%M} → {t.max():%Y-%m-%d %H:%M} UTC "
          f"({(t.max() - t.min()).days} сут)")
    print(f"шаг опроса на монету: медиана {gap.median():.0f} с · p90 {gap.quantile(.9):.0f} с · "
          f"дыр > 2 ч: {(gap > 7200).sum()}")
    per_day = df.assign(d=t.dt.date).groupby("d").symbol.nunique()
    print(f"монет в сутки: мин {per_day.min()} · медиана {per_day.median():.0f} · макс {per_day.max()}")


def hourly_panel(df: pd.DataFrame) -> pd.DataFrame:
    """Один снимок на монету в час + цена 15 мин / 24 ч назад + цена через h часов (ближайший снимок)."""
    df = df.copy()
    df["hr"] = df.ts // 3600
    snap = df.groupby(["symbol", "hr"], as_index=False).first()
    out = []
    for sym, g in df.groupby("symbol"):
        s = snap[snap.symbol == sym].sort_values("ts")
        if len(s) < 72:
            continue
        ref = g[["ts", "px"]].sort_values("ts")

        def px_at(offset: int, tol: int) -> np.ndarray:
            q = pd.DataFrame({"t": s.ts.to_numpy() + offset}).sort_values("t")
            m = pd.merge_asof(q, ref.rename(columns={"ts": "t"}), on="t", direction="nearest", tolerance=tol)
            return m.px.to_numpy()

        s = s.assign(px_m15=px_at(-900, 300), px_m24=px_at(-86400, 1800))
        for nm, h in HORIZONS.items():
            s[f"fwd_{nm}"] = (px_at(h * 3600, max(600, h * 360)) / s.px - 1) * 100
        out.append(s)
    p = pd.concat(out, ignore_index=True)
    p["ret15"] = (p.px / p.px_m15 - 1) * 100
    p["ret24"] = (p.px / p.px_m24 - 1) * 100
    return p


def states(p: pd.DataFrame) -> dict[str, tuple[np.ndarray, int]]:
    r15, r24 = terciles(p.ret15), terciles(p.ret24)
    o15, o1d, fu = terciles(p.oi_d15), terciles(p.oi_d1d), terciles(p.funding)
    br = p.groupby("hr").oi_d15.transform(lambda v: (v > 0).mean())      # ширина: доля монет с OI↑ в этот час
    b = terciles(br)

    def combo(*parts):
        code = np.zeros(len(p), int)
        bad = np.zeros(len(p), bool)
        for x in parts:
            bad |= x < 0
            code = code * 3 + np.maximum(x, 0)
        code[bad] = -1
        return code, 3 ** len(parts)

    noise = [RNG.integers(0, 3, len(p)) for _ in range(3)]           # отрицательный контроль прибора
    f4 = p["fwd_4ч"].to_numpy()                                       # положительный: знак форварда 4ч, 40% переворотов
    plant = np.where(np.isnan(f4), -1, (f4 > 0).astype(int) ^ (RNG.random(len(p)) < 0.4))
    return {"шум 27 ячеек (контроль)": combo(*noise),
            "подсадка 4ч (контроль)": (plant.astype(int), 2),
            "цена (ret15×ret24)": combo(r15, r24),
            "OI (d15×d1d×фандинг)": combo(o15, o1d, fu),
            "OI + ширина OI": combo(o15, o1d, fu, b),
            "цена × OI": combo(r15, r24, o15, o1d, fu)}


def shifted(y: np.ndarray, hr: np.ndarray, sym: np.ndarray, shift: int) -> np.ndarray:
    """Сдвиг всей оси времени: ответ часа t берётся из часа t+shift (по кругу), монета та же."""
    h0, span = int(hr.min()), int(hr.max() - hr.min() + 1)
    code = pd.factorize(sym)[0].astype(np.int64)
    table = np.full(int(code.max() + 1) * span, -1, dtype=np.int64)       # (монета, час) → ответ
    table[code * span + (hr - h0)] = y
    return table[code * span + (hr - h0 + shift) % span]


def measure(p: pd.DataFrame, st: dict, label: str, relative: bool) -> pd.DataFrame:
    rows = []
    for nm in HORIZONS:
        f = p[f"fwd_{nm}"]
        if relative:
            f = f - p.groupby("hr")[f"fwd_{nm}"].transform("median")
        y = np.where(f.notna(), (f > 0).astype(int), -1)
        shifts = RNG.integers(48, p.hr.max() - p.hr.min() - 48, N_SHIFT)
        ys = [shifted(y, p.hr.to_numpy(), p.symbol.to_numpy(), int(s)) for s in shifts]
        need = 50 + COST / (2 * np.nanmean(np.abs(p[f"fwd_{nm}"]))) * 100
        base = (y[y >= 0] == 1).mean() * 100
        for sn, (x, nx) in st.items():
            i = mi(x, y, nx)
            ok = y >= 0
            ctl_sh = np.mean([mi(x[ok], RNG.permutation(y[ok]), nx) for _ in range(3)])
            # 🔴 сдвиг: факт и контроль на ОДНИХ И ТЕХ ЖЕ строках (иначе контроль на меньшей выборке
            # получает большее смещение оценки и «съедает» находку — дефект первого прогона 27.09)
            act, ctl = [], []
            for yy in ys:
                v = ok & (yy >= 0)
                act.append(mi(x[v], y[v], nx)); ctl.append(mi(x[v], yy[v], nx))
            act, ctl = np.array(act), np.array(ctl)
            ex = float((act - ctl).mean())
            rows.append({"срез": label, "гор": nm, "состояние": sn, "I": i, "ctl_перемеш": ctl_sh,
                         "сверх_перемеш": i - ctl_sh, "сверх_сдвига": ex, "p_сдвиг": (ctl >= act).mean(),
                         "экв_точн": eq_accuracy(max(ex, 0)), "нужно": need, "доля_вверх": base})
    return pd.DataFrame(rows)


def binance_liquidity() -> dict[str, float]:
    try:
        d = json.load(urllib.request.urlopen("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=20))
        return {x["symbol"][:-4]: float(x["quoteVolume"]) for x in d if x["symbol"].endswith("USDT")}
    except Exception as e:  # noqa: BLE001
        print(f"  ликвидность недоступна: {e}")
        return {}


if __name__ == "__main__":
    raw = load()
    inventory(raw)
    P = hourly_panel(raw)
    print(f"панель: {len(P):,} монето-часов · монет {P.symbol.nunique()}")
    btc = P[P.symbol == "BTC"].sort_values("ts")
    if len(btc):
        print(f"режим окна: BTC {btc.px.iloc[0]:.0f} → {btc.px.iloc[-1]:.0f} "
              f"({(btc.px.iloc[-1] / btc.px.iloc[0] - 1) * 100:+.1f}%) · "
              f"медиана монеты за окно {P.groupby('symbol').px.agg(lambda v: v.iloc[-1] / v.iloc[0] - 1).median() * 100:+.1f}%")

    ST = states(P)
    res = [measure(P, ST, "все", False), measure(P, ST, "все/относ.", True)]

    half = P.hr.median()                                              # срезы: время, монеты, ликвидность
    syms = P.symbol.unique(); RNG.shuffle(syms); grp_a = set(syms[: len(syms) // 2])
    liq = binance_liquidity()
    med_liq = np.median([liq.get(s, 0) for s in syms]) if liq else None
    cuts = {"1-я половина окна": P.hr < half, "2-я половина окна": P.hr >= half,
            "монеты A": P.symbol.isin(grp_a), "монеты B": ~P.symbol.isin(grp_a)}
    if med_liq:
        cuts["ликвидные"] = P.symbol.map(lambda s: liq.get(s, 0) >= med_liq)
        cuts["неликвидные"] = ~cuts["ликвидные"]
    for nm, m in cuts.items():
        sub = P[m.to_numpy()].reset_index(drop=True)
        res.append(measure(sub, states(sub), nm, False))
    R = pd.concat(res, ignore_index=True)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    inc = []                                                          # ΔI: что OI добавляет СВЕРХ цены
    for (lab, hor), g in R.groupby(["срез", "гор"], sort=False):
        s = g.set_index("состояние")
        inc.append({"срез": lab, "гор": hor,
                    "цена": s.at["цена (ret15×ret24)", "сверх_сдвига"],
                    "цена×OI": s.at["цена × OI", "сверх_сдвига"],
                    "ΔI_от_OI": s.at["цена × OI", "сверх_сдвига"] - s.at["цена (ret15×ret24)", "сверх_сдвига"],
                    "шум": s.at["шум 27 ячеек (контроль)", "сверх_сдвига"]})
    INC = pd.DataFrame(inc)
    fmt = {"I": "{:.5f}", "ctl_перемеш": "{:.5f}", "сверх_перемеш": "{:+.5f}", "сверх_сдвига": "{:+.5f}",
           "p_сдвиг": "{:.2f}", "экв_точн": "{:.2f}", "нужно": "{:.2f}", "доля_вверх": "{:.1f}"}
    for k, f in fmt.items():
        R[k] = R[k].map(f.format)
    print("\n=== ПОТОЛОК: I(состояние; знак форварда), бит ===")
    print(R[R.срез.isin(["все", "все/относ."])].to_string(index=False))
    print("\n=== СРЕЗЫ (абсолютный знак) ===")
    print(R[~R.срез.isin(["все", "все/относ."])].to_string(index=False))

    print("\n=== ΔI: что OI добавляет СВЕРХ цены (сверх контроля-сдвига, бит) ===")
    print(INC.round(5).to_string(index=False))

    print("\n=== НАПРАВЛЕНИЕ: форвард 24ч (%) по терцилям OI за сутки — абсолютный и относительно медианы часа ===")
    rel = P["fwd_24ч"] - P.groupby("hr")["fwd_24ч"].transform("median")
    D = P.assign(t=terciles(P.oi_d1d), rel=rel).dropna(subset=["fwd_24ч"])
    print(D.groupby("t").agg(n=("fwd_24ч", "size"), ср=("fwd_24ч", "mean"), медиана=("fwd_24ч", "median"),
                             доля_вверх=("fwd_24ч", lambda v: (v > 0).mean() * 100),
                             отн_медиана=("rel", "median"),
                             отн_доля_лучше=("rel", lambda v: (v > 0).mean() * 100)).round(3).to_string())
    out = Path("G:/oko_lab/out/oi_info_ceiling.csv")
    try:
        R.to_csv(out, index=False, encoding="utf-8")
        print(f"\nтаблица → {out}")
    except Exception:
        pass
