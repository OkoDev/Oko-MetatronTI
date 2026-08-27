# -*- coding: utf-8 -*-
"""КОНФЛЮЭНЦИИ В OTE НА ЭТАЛОННОМ СБОРЩИКЕ (11.08.2026, поправка Егора).

Егор: «ты опять упускаешь всю карту json признаков SMC. SC сильнее ордер-блока».
Он прав дважды:
1. Греп показал: НИ ОДИН мой тест OTE не включал конфлюэнции (FVG=0, OB=0, пивоты=0).
2. Мой самодельный тест считал перекрытие с ДВУМЯ САМЫМИ СЛАБЫМИ типами и без весов.

В проекте есть КАЛИБРОВАННЫЙ сборщик `OTESignalGenerator._collect_triggers`
(`core/smc/ote_signal_generator.py`), и его иерархия силы прямо записана в коде:
    SC* > EQL > OB > FVG      (веса 5 / 4 / 3 (1 если митигирован) / 2)
плюс `_merge`: перекрывающиеся триггеры схлопываются в зону, +1 за каждый доп. ТФ.
SC = sponsored candle (свип ликвидности + разворот); SC* = свип + CHoCH + FVG.

Здесь сборщик ПЕРЕИСПОЛЬЗУЕТСЯ НАПРЯМУЮ (генератор создаётся без аргументов) —
не копия весов, а тот же калькулятор ([[principle_reuse_not_duplication]]).

База: конфигурация, выжившая развёртки — импульс CHoCH+BOS на 4h, зона 0.55-0.85,
стоп>6%, кластер≥2, переключатель по причинному режиму (180/48/12). Косты 0.35%.
Триггеры собираются на 15m ВНУТРИ ОКНА ИМПУЛЬСА (как в эталоне: там, где они сформированы).

Контрольная клетка обязательна: «БЕЗ триггеров вовсе». Если зона без единой конфлюэнции
не хуже — конфлюэнция не работает, и это надо знать."""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.oko_sm_engine import run_structure
from core.smc.impulse_assembly import assemble_impulse, ote_zone
from core.smc.ote_signal_generator import OTESignalGenerator
from core.context.market_drift import regime_series, BULL, BEAR
DB = "ohlcv_cache.db"
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 30
COST, MIN_STOP, ZLO, ZHI = 0.35, 6.0, 0.55, 0.85
GEN = OTESignalGenerator()


def load(sym, tf, t0):
    c = sqlite3.connect(DB)
    df = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                     "AND timeframe=? AND time>=? ORDER BY time", c, params=(sym, tf, t0))
    c.close()
    return df.reset_index(drop=True)


def sim(i, side, H, L, C, sl, tp, ttl=72):
    e = C[i]; end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if side > 0:
            if L[j] <= sl: return (sl - e) / e * 100
            if H[j] >= tp: return (tp - e) / e * 100
        else:
            if H[j] >= sl: return (e - sl) / e * 100
            if L[j] <= tp: return (e - tp) / e * 100
    return side * (C[end] - e) / e * 100


def rep(name, rows):
    if len(rows) < 20:
        print(f"    {name:34} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - COST
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - COST for x in rows if x[2] == cn]) > 0)
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:34} n={len(r):4} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+7.0f}% монет+{pos:3}/{len(coins):3} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute(
    "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? "
    "GROUP BY symbol HAVING n>60000 ORDER BY n DESC LIMIT ?", (t0, NCOIN)).fetchall()]
c.close()
print(f"монет {len(syms)} (с длинной историей 15m) · триггеры эталонного сборщика\n")

px = {}
SIG = []
for si, sym in enumerate(syms):
    d4 = load(sym, "4h", t0); d1 = load(sym, "1h", t0); d15 = load(sym, "15m", t0)
    if len(d4) < 1200 or len(d1) < 5000 or len(d15) < 20000:
        continue
    px[sym] = pd.Series(d4.close.values, index=d4.time.values)
    d15.index = pd.to_datetime(d15.time, unit="ms")
    t4 = d4.time.values; t1 = d1.time.values
    H1 = d1.high.values; L1 = d1.low.values; C1 = d1.close.values
    yr1 = pd.to_datetime(d1.time, unit="ms").dt.year.values
    seen = {}
    for b in range(1050, len(d4) - 1, 6):
        win = d4.iloc[max(0, b - 1000):b + 1].reset_index(drop=True)
        try:
            st = run_structure(win, swing_len=50, internal_len=5)
        except Exception:
            continue
        imp = assemble_impulse(st, win["high"], win["low"], internal=True)
        if not imp or imp["n_bos"] < 1:
            continue
        is_long = imp["is_long"]; sd = "LONG" if is_long else "SHORT"
        key = (round(imp["origin"], 10), round(imp["extreme"], 10))
        if seen.get(sd) == key:
            continue
        seen[sd] = key
        z_lo, z_hi = ote_zone(imp["origin"], imp["extreme"], is_long, ZLO, ZHI)
        # ── ЭТАЛОННЫЙ СБОРЩИК: окно = сам импульс, где триггеры и сформированы ──
        try:
            w0 = pd.to_datetime(win.time.iloc[imp["i_choch"]], unit="ms")
            w1 = pd.to_datetime(win.time.iloc[-1], unit="ms")
            trg = GEN._collect_triggers(z_lo, z_hi, "long" if is_long else "short",
                                        {"15m": d15}, w0, w1)
        except Exception:
            trg = []
        wmax = max([t[5] for t in trg], default=0)
        types = set()
        for t in trg:
            types.update(t[0].split("+"))
        side = 1 if is_long else -1
        j0 = int(np.searchsorted(t1, t4[b])); j1 = min(j0 + 24, len(d1) - 2)
        for j in range(max(j0, 1), j1):
            p_ = C1[j]
            if not (z_lo <= p_ <= z_hi):
                continue
            sl = imp["origin"] * (0.997 if is_long else 1.003)
            if (is_long and sl >= p_) or ((not is_long) and sl <= p_):
                break
            dist = abs(p_ - sl) / p_ * 100
            if not (MIN_STOP < dist < 25):
                break
            SIG.append({"sym": sym, "t": int(t1[j]), "y": int(yr1[j]), "side": sd,
                        "n_trg": len(trg), "wmax": wmax, "types": types,
                        "pnl": sim(j, side, H1, L1, C1, sl, p_ + side * abs(p_ - sl))})
            break
    print(f"  [{si+1}/{len(syms)}] {sym.split('/')[0]:12} сигналов={len(SIG)}")

panel = pd.DataFrame(px).sort_index()
REG = regime_series(panel, drift_bars=180, ma_bars=48, min_periods=400, min_hold=12)
rt = REG.index.values.astype("int64"); rl = REG["label"].values
BUCKET = 4 * 3600 * 1000
cl = defaultdict(int)
for s in SIG:
    cl[(s["t"] // BUCKET, s["side"])] += 1
# 11.08 ИСПРАВЛЕНИЕ КОНСТРУКЦИИ: первый прогон дал n=8 — я сложил ТРИ ограничительных гейта
# (кластер≥2 + переключатель режима + стоп>6%) на вселенной из 30 монет. Кластер мерился
# на 120 монетах; на 30 одновременные сигналы почти не встречаются. Вердикта не было — был шум.
# Конфлюэнция ОРТОГОНАЛЬНА кластеру и режиму → для её измерения эти гейты не нужны.
# Меряем на широкой базе (импульс + стоп>6%), гейты оставляем отдельной справкой.
R = defaultdict(list)
for s in SIG:
    k = int(np.searchsorted(rt, s["t"], side="right")) - 1
    lab = rl[k] if 0 <= k < len(rl) else None
    in_cluster = cl[(s["t"] // BUCKET, s["side"])] >= 2
    on_regime = (lab is not None and not (isinstance(lab, float) and np.isnan(lab))
                 and ((lab == BULL and s["side"] == "LONG")
                      or (lab == BEAR and s["side"] == "SHORT")))
    row = (s["y"], s["pnl"], s["sym"])
    if in_cluster:
        R["справка: кластер≥2"].append(row)
    if on_regime:
        R["справка: по режиму"].append(row)
    if in_cluster and on_regime:
        R["справка: кластер+режим (было n=8)"].append(row)
    R["БАЗА (все)"].append(row)
    R["БЕЗ триггеров (контроль)" if s["n_trg"] == 0 else "ЕСТЬ триггеры"].append(row)
    for w, nm in ((2, "макс.вес ≥2 (FVG+)"), (3, "макс.вес ≥3 (OB+)"),
                  (4, "макс.вес ≥4 (EQL/SC+)"), (5, "макс.вес ≥5 (SC* / мульти-ТФ)")):
        if s["wmax"] >= w:
            R[nm].append(row)
    for ty in ("SC*", "SC", "EQL", "OB", "FVG"):
        if ty in s["types"]:
            R[f"тип {ty}"].append(row)
    if "SC*" in s["types"] or "SC" in s["types"]:
        R["SC любой"].append(row)
    if s["n_trg"] >= 3:
        R["≥3 триггер-зоны"].append(row)
    # 11.08 ГИПОТЕЗА ЕГОРА: «стоит проверить свип ликвидности с OB».
    # Сырой OB вредит ДВАЖДЫ независимо (1.29 против 1.65 · 1.63 против 2.68). Но OB
    # непотревоженный и OB, с которого СНЯЛИ ЛИКВИДНОСТЬ, — разные объекты: первый просто
    # уровень, который проходят насквозь; второй = забрали стопы и развернулись.
    # Свип оцифрован как SC (sponsored candle: свип+разворот), SC* = свип+CHoCH+FVG.
    _ob = "OB" in s["types"]
    _sc = ("SC" in s["types"]) or ("SC*" in s["types"])
    R[("OB + СВИП" if _sc else "OB БЕЗ свипа") if _ob
      else ("СВИП без OB" if _sc else "ни OB ни свипа")].append(row)
    if _ob and "SC*" in s["types"]:
        R["OB + СВИП подтверждённый (SC*)"].append(row)

print(f"\nбаза (импульс + стоп>{MIN_STOP}%): {len(R.get('БАЗА (все)', []))} сделок · "
      f"без единого триггера: {len(R.get('БЕЗ триггеров (контроль)', []))}")
print("\n═══ КОНФЛЮЭНЦИИ В OTE · косты 0.35% · база БЕЗ кластера/режима ═══")
for k in ("БАЗА (все)", "БЕЗ триггеров (контроль)", "ЕСТЬ триггеры",
          "макс.вес ≥2 (FVG+)", "макс.вес ≥3 (OB+)", "макс.вес ≥4 (EQL/SC+)",
          "макс.вес ≥5 (SC* / мульти-ТФ)", "≥3 триггер-зоны"):
    rep(k, R.get(k, []))
print("\n  ── по ТИПУ (проверка «SC сильнее OB») ──")
for k in ("тип SC*", "тип SC", "SC любой", "тип EQL", "тип OB", "тип FVG"):
    rep(k, R.get(k, []))
print("\n  ── ГИПОТЕЗА ЕГОРА: свип ликвидности + ордер-блок ──")
for k in ("OB БЕЗ свипа", "OB + СВИП", "OB + СВИП подтверждённый (SC*)",
          "СВИП без OB", "ни OB ни свипа"):
    rep(k, R.get(k, []))
print("\n  ── справка: что делают гейты на ЭТОЙ вселенной ──")
for k in ("справка: кластер≥2", "справка: по режиму", "справка: кластер+режим (было n=8)"):
    rep(k, R.get(k, []))
