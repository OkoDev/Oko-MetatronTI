"""ОТБОР ПО ПРИЗНАКАМ: на чём пробой уровня отрабатывает чаще (Егор 18.09: «нужен отбор монет по признакам, на которых
чаще отрабатывает — если у монеты набор признаков для большей вероятности отработки»).

НЕ с чистого листа: харнесс `scripts/research_harness.py` (вся матрица compute_flags + старшие ТФ с закрытого бара)
+ `scripts/matrix_full.extra_flags` (фандинг, ширина/дрейф вселенной, режим BTC, дистанции, состояние, RS монеты)
+ признаки МОНЕТЫ (волатильность 30д, оборот 30д, возраст, число пампов за 90д, доходность 30/90д, расстояние до
максимума 180д) — всё на баре ВХОДА, каузально. Слепой отбор IS→OOS (чётные монеты × ≤2024 → нечётные × ≥2025),
числовые — по децилям с перестановочным контролем.

Механика: пробой хая пампа (хай 7 дн, ход ≥30%, откат ≥15%, возврат) с закрепом на 1h, вход по open следующего бара,
стоп = уровень − 2·ATR(24), цель 3R, удержание 72 ч. Шорт зеркально. Косты 0.10 (как в сегодняшних прогонах).
Запуск: python level_break_features.py [монет]   (по умолчанию ядро полного покрытия, до 120 монет)
"""
import sys, pickle, time
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from scripts import research_harness as H
from scripts.matrix_full import extra_flags

OUT = Path("G:/oko_lab/out/level_break_features"); OUT.mkdir(parents=True, exist_ok=True)
W_H, MIN_PUMP, MIN_PULL, HOLD, K_ATR, RR = 24 * 7, 0.30, 0.15, 72, 2.0, 3.0


def mechanic(df: pd.DataFrame, tf: str) -> list:
    hi, lo, cl, op = df.high.values, df.low.values, df.close.values, df.open.values
    tr = np.maximum(df.high - df.low, np.maximum((df.high - df.close.shift()).abs(), (df.low - df.close.shift()).abs()))
    atr = tr.rolling(24).mean().values
    n = len(df); out = []
    for long_ in (True, False):
        last_level = None; i = W_H
        while i < n - 4:
            wh, wl = hi[i - W_H:i], lo[i - W_H:i]
            if long_:
                k = int(wh.argmax()); L = float(wh[k]); base = float(wl[:k + 1].min())
                pump = L / base - 1 if base > 0 else 0; pull = 1 - float(wl[k:].min()) / L; below = cl[i - 1] < L
            else:
                k = int(wl.argmin()); L = float(wl[k]); base = float(wh[:k + 1].max())
                pump = base / L - 1 if L > 0 else 0; pull = float(wh[k:].max()) / L - 1; below = cl[i - 1] > L
            if pump >= MIN_PUMP and pull >= MIN_PULL and below and L != last_level:
                last_level = L
                seg = df.iloc[i - W_H:i]
                near = seg[(seg.high >= L * 0.995) & (seg.high <= L * 1.005)] if long_ else seg[(seg.low <= L * 1.005) & (seg.low >= L * 0.995)]
                touches, last = 1, None
                for t in near.index:
                    if last is not None and (t - last) >= pd.Timedelta(hours=4):
                        touches += 1
                    if last is None or (t - last) >= pd.Timedelta(hours=4):
                        last = t
                # пробой в течение 7 дней + закреп
                j1 = None
                for t in range(i, min(i + W_H, n - 3)):
                    if (cl[t] > L) if long_ else (cl[t] < L):
                        j1 = t; break
                if j1 is not None and ((cl[j1 + 1] > L) if long_ else (cl[j1 + 1] < L)) and np.isfinite(atr[j1 + 1]):
                    e_i = j1 + 2; e = float(op[e_i]); a_ = float(atr[j1 + 1])
                    sl = L - K_ATR * a_ if long_ else L + K_ATR * a_
                    if (long_ and sl < e) or (not long_ and sl > e):
                        r = abs(e - sl); tp = e + RR * r if long_ else e - RR * r
                        pnl, outc, k_out = None, "time", min(e_i + HOLD, n) - 1
                        for k2 in range(e_i, min(e_i + HOLD, n)):
                            if (lo[k2] <= sl) if long_ else (hi[k2] >= sl):
                                pnl, outc, k_out = ((sl - e) / e * 100) * (1 if long_ else -1), "stop", k2; break
                            if (hi[k2] >= tp) if long_ else (lo[k2] <= tp):
                                pnl, outc, k_out = ((tp - e) / e * 100) * (1 if long_ else -1), "target", k2; break
                        if pnl is None:
                            pnl = ((float(cl[k_out]) - e) / e * 100) * (1 if long_ else -1)
                        seg_h = hi[e_i:e_i + HOLD]; seg_l = lo[e_i:e_i + HOLD]
                        mfe = (seg_h.max() / e - 1) * 100 if long_ else (1 - seg_l.min() / e) * 100
                        out.append({"entry_bar": e_i, "pnl_pct": pnl, "side": "long" if long_ else "short", "stop_pct": r / e * 100,
                                    "hit": int(outc == "target"), "outcome": outc, "mfe": mfe, "pump": pump * 100, "pull": pull * 100,
                                    "touches": touches, "wait_h": j1 - i, "level": L})
                    i = j1 + 2
                    continue
            i += 1
    return out


def coin_features(df: pd.DataFrame, tf: str, sym: str) -> pd.DataFrame:
    """Признаки МОНЕТЫ на закрытом баре (shift(1)): волатильность, оборот, возраст, памповость, доходность, расстояние до максимума."""
    d1 = df.close.resample("1D").last().dropna()
    r = np.log(d1).diff()
    f = pd.DataFrame(index=d1.index)
    f["coin_vol30"] = r.rolling(30).std() * 100
    f["coin_vol7"] = r.rolling(7).std() * 100
    f["coin_ret30"] = (d1 / d1.shift(30) - 1) * 100
    f["coin_ret90"] = (d1 / d1.shift(90) - 1) * 100
    f["coin_dist_max180"] = (d1 / d1.rolling(180, min_periods=30).max() - 1) * 100
    f["coin_dist_min180"] = (d1 / d1.rolling(180, min_periods=30).min() - 1) * 100
    dol = (df.close * df.volume).resample("1D").sum()
    f["coin_dol30_musd"] = dol.rolling(30).mean() / 1e6
    f["coin_age_days"] = (d1.index - df.index[0]).days
    hi7 = df.high.resample("1D").max().rolling(7).max(); lo7 = df.low.resample("1D").min().rolling(7).min()
    pump_day = (hi7 / lo7 - 1 >= MIN_PUMP).astype(float)
    f["coin_pumps90"] = pump_day.rolling(90, min_periods=30).sum()
    # «своя игра, не зависит от биткоина» (автор канала, 18.09): корреляция и бета к BTC за 30 дней, доходность минус BTC
    b = _btc_daily()
    if b is not None:
        rb = np.log(b).diff().reindex(r.index)
        f["coin_corr30_btc"] = r.rolling(30).corr(rb)
        f["coin_beta30_btc"] = r.rolling(30).cov(rb) / rb.rolling(30).var()
        f["coin_ret30_vs_btc"] = f["coin_ret30"] - ((b / b.shift(30) - 1) * 100).reindex(r.index)
    f = f.shift(1).reindex(df.index, method="ffill")
    return f.astype("float32")


_BTC = {}


def _btc_daily():
    if "d" not in _BTC:
        try:
            _BTC["d"] = H.load("BTC/USDT", "1h").close.resample("1D").last().dropna()
        except Exception:                               # noqa: BLE001
            _BTC["d"] = None
    return _BTC["d"]


def extra(df, tf, sym):
    parts = [coin_features(df, tf, sym)]
    try:
        parts.append(extra_flags(df, tf, sym))
    except Exception as e:                              # noqa: BLE001
        print(f"  [{sym}] extra_flags: {type(e).__name__}: {str(e)[:60]}")
    return pd.concat(parts, axis=1)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    t0 = time.time()
    R = H.collect(mechanic, tf="1h", n_symbols=n, core=True, cost=0.10, extra=extra)
    R.to_pickle(OUT / "R.pkl")
    print(f"\nсобрано за {time.time() - t0:.0f}с → {OUT / 'R.pkl'}")
    H.report(R)
    print("\nОТРАБОТКА (цель 3R взята):", f"{R.hit.mean() * 100:.1f}% всего · long {R[R.side == 'long'].hit.mean() * 100:.1f}% · short {R[R.side == 'short'].hit.mean() * 100:.1f}%")
    H.blind_select(R)
    H.blind_select_num(R)
