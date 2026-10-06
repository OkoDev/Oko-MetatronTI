#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ЛОЖАТСЯ ЛИ ВЕСА/КОНФЛЮЭНЦИЯ SMC НА МЕХАНИКУ ВОЛН (вопрос Егора 06.10).

Повод: «интересно, а веса как лягут на механику волн?» Прямо на боевых сделках
ответить нельзя — волновых в БД всего **133** (`impulse_fib_15m` 92, `choch_wavec` 16,
`waves_long` 14, `impulse_fib` 11), и нарезать их по стороне и месяцу уже не на чем.
Поэтому проверяем на РЕПЛЕЕ через харнесс, где ядро волн мерено на 97 монетах.

Что именно спрашиваем: механика волны C даёт сделки; добавляет ли SMC-конфлюэнция
к ним что-то СВЕРХ того, что уже даёт сам волновой контекст — или они объясняют
одно и то же. Это и есть «лягут ли веса на волны».

🔴 Почему через `research_harness`, а не своим скриптом: харнесс подтягивает ВСЮ
матрицу признаков сам (пивоты · SMC · дивергенции · WT · ATR, со старших ТФ через
`shift(1)` — то есть с ЗАКРЫТОГО бара), печатает обязательные срезы и делает слепой
отбор IS→OOS. Написать замер с нуля = гарантированно забыть половину семей
([[research_harness_single_entry]]).

Механика взята из `scripts/choch_pullback_atrflip_waveC.py` (15.08), не переизобретена:
    A = импульс слома (от экстремума 20 баров до бара CHoCH)
    B = коррекция на PB от A — лимитный вход
    C = цель entry ± |A| × k
    стоп — за экстремум B (инвалидация отката)

Запуск:
    python scripts/wave_c_smc_weights.py --tf 1h --coins 60
    python scripts/wave_c_smc_weights.py --tf 4h --coins 97 --core
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                    # noqa: BLE001
    pass

from research_harness import collect, report, blind_select, blind_select_num  # noqa: E402

PB = 0.5          # глубина коррекции от A (как в эталонном скрипте)
WAVE_K = 1.0      # цель = |A| × k
TTL = 48          # держим баров
WAIT_PB = 12      # ждём коррекцию баров


def _atr_dir(df, period=43, factor=1.25):
    """ATRTrend-направление (как в choch_pullback_atrflip_waveC): +1 вверх, −1 вниз."""
    h, l, c = df.high.values, df.low.values, df.close.values
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr = pd.Series(np.concatenate([[np.nan], tr])).ewm(alpha=1 / period, adjust=False).mean().values
    up, dn = c - factor * atr, c + factor * atr
    d = np.ones(len(c), dtype=int)
    for i in range(1, len(c)):
        d[i] = 1 if c[i] > dn[i - 1] else (-1 if c[i] < up[i - 1] else d[i - 1])
    return d


def _resolve(H, L, C, j, side, entry, sl, tp, ttl):
    """Исход сделки от бара j. Возвращает % БЕЗ костов — их вычтет харнесс."""
    end = min(j + ttl, len(C) - 1)
    for k in range(j, end + 1):
        if side == "long":
            if L[k] <= sl:
                return (sl - entry) / entry * 100
            if H[k] >= tp:
                return (tp - entry) / entry * 100
        else:
            if H[k] >= sl:
                return (entry - sl) / entry * 100
            if L[k] <= tp:
                return (entry - tp) / entry * 100
    return ((C[end] - entry) if side == "long" else (entry - C[end])) / entry * 100


def wave_c(df: pd.DataFrame, tf: str) -> list[dict]:
    """Механика CHoCH → коррекция → волна C в контракте харнесса.

    Возвращает сделки с `entry_bar` (бар ВХОДА — на нём харнесс снимет признаки),
    `pnl_pct` без костов и `side`. Дополнительные поля уезжают в срезы как есть.
    """
    from core.calculators.combinator_core import compute_flags

    try:
        F = compute_flags(df, tf, include_pivots=False)
    except Exception:                                # noqa: BLE001
        return []

    def arr(k):
        """Колонка по ИМЕНИ БЕЗ суффикса ТФ.

        🔴 `compute_flags` возвращает `bull_choch_1h`, а не `bull_choch` — поиск по
        точному имени даёт нули молча, и механика выдаёт 0 сделок без единой ошибки.
        Берём точное совпадение `{k}_{tf}`, иначе первую колонку, начинающуюся с `k_`,
        но НЕ internal-вариант (`bull_choch_i_1h` — микрослом, его в 7 раз больше).
        """
        exact = f"{k}_{tf}"
        if exact in F.columns:
            col = exact
        else:
            cands = [c for c in F.columns
                     if c.startswith(k + "_") and not c.startswith(k + "_i_")]
            if not cands:
                return np.zeros(len(df), dtype=bool)
            col = cands[0]
        try:
            return np.asarray(F[col].fillna(False), dtype=bool)
        except Exception:                            # noqa: BLE001
            return np.zeros(len(df), dtype=bool)

    bull_ch, bear_ch = arr("bull_choch"), arr("bear_choch")
    if not (bull_ch.any() or bear_ch.any()):
        return []                                    # нет событий — молча, но честно
    td = _atr_dir(df)
    H, L, C = df.high.values, df.low.values, df.close.values
    n = len(df)
    out = []

    for side, ch in (("long", bull_ch), ("short", bear_ch)):
        want = 1 if side == "long" else -1
        for i0 in np.flatnonzero(ch):
            i = int(i0)
            if i < 25 or i >= n - TTL - WAIT_PB - 2:
                continue
            # ── волна A: импульс слома ──
            if side == "long":
                a_lo, a_hi = float(L[max(0, i - 20):i + 1].min()), float(C[i])
            else:
                a_hi, a_lo = float(H[max(0, i - 20):i + 1].max()), float(C[i])
            if a_hi <= a_lo:
                continue
            A_len = a_hi - a_lo

            # ── волна B: коррекция, лимитный вход ──
            entry = a_hi - A_len * PB if side == "long" else a_lo + A_len * PB
            jf = None
            for j in range(i + 1, min(i + 1 + WAIT_PB, n)):
                if (side == "long" and L[j] <= entry) or (side == "short" and H[j] >= entry):
                    jf = j
                    break
            if jf is None:
                continue

            # стоп за экстремум B
            if side == "long":
                sl = min(float(L[i:jf + 1].min()), a_lo) * 0.999
            else:
                sl = max(float(H[i:jf + 1].max()), a_hi) * 1.001
            sp = abs(entry - sl) / entry * 100
            if sp <= 0 or sp > 25:
                continue

            tp = entry + A_len * WAVE_K if side == "long" else entry - A_len * WAVE_K
            pnl = _resolve(H, L, C, jf, side, entry, sl, tp, TTL)
            out.append({
                "entry_bar": jf,
                "pnl_pct": pnl,
                "side": side,
                # срезы, специфичные для механики — харнесс положит их как есть
                "stop_pct": round(sp, 3),
                "a_len_atr": round(A_len / entry * 100, 3),
                "wait_bars": jf - i,
                "atr_dir_ok": int(td[jf] == want),
            })
    return out


def gates_vs_full_base(R, gates: list[str]) -> None:
    """Проверка кандидатов КАК ГЕЙТА против ПОЛНОЙ базы.

    🔴 Закон: фильтр меряется против полной базы, а не подменяет её
    ([[golden_keys_matrix_verdict]]). Слепой отбор харнесса отвечает на вопрос
    «лучше ли подвыборка», а торговое решение требует другого: сколько ПОТОКА
    режем и сколько денег теряем вместе с ним. Гейт, поднимающий PF вдвое ценой
    90% сделок, в бою бесполезен.

    Печатаем на каждой строке: долю потока, PF, сумму и хрупкость — чтобы
    «отсеивает много» нельзя было спутать с «зарабатывает больше»
    ([[gate_threshold_frequency_vs_money]]).
    """
    import numpy as np

    def _st(v):
        if len(v) < 30:
            return None
        p = v["pnl"].values
        pos, neg = p[p > 0].sum(), -p[p < 0].sum()
        frail = np.sort(p)[:max(1, int(len(p) * 0.9))].sum()
        return dict(n=len(p), wr=(p > 0).mean() * 100,
                    pf=(pos / neg if neg > 0 else float("inf")),
                    mean=p.mean(), total=p.sum(), frail=frail,
                    cov=(v.groupby("sym")["pnl"].sum() > 0).mean() * 100)

    for side in ("short", "long"):
        S = R[R.side == side]
        base = _st(S)
        if base is None:
            continue
        print(f"\n  ── {side.upper()} · ПОЛНАЯ БАЗА n={base['n']} · PF {base['pf']:.2f} · "
              f"сумма {base['total']:+.0f}% · хрупкость {base['frail']:+.0f} ──")
        print(f"    {'гейт':<34}{'поток':>7}{'n':>6}{'PF':>7}{'сумма':>9}"
              f"{'безтоп10%':>11}{'монет+':>8}")
        for g in gates:
            if g not in S.columns:
                continue
            v = S[S[g].fillna(0) > 0] if _is_bool_like(S[g]) else None
            if v is None:
                continue
            s = _st(v)
            if s is None:
                print(f"    {g:<34}{len(v) / len(S) * 100:>6.0f}%  — мало сделок")
                continue
            print(f"    {g:<34}{s['n'] / base['n'] * 100:>6.0f}%{s['n']:>6}"
                  f"{s['pf']:>7.2f}{s['total']:>+9.0f}{s['frail']:>+11.0f}{s['cov']:>7.0f}%")


def _is_bool_like(col) -> bool:
    u = set(col.dropna().unique().tolist())
    return u <= {0, 1, 0.0, 1.0, True, False}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--coins", type=int, default=60)
    ap.add_argument("--core", action="store_true", help="фиксированное ядро (годы сравнимы)")
    ap.add_argument("--save", default="", help="куда сохранить собранную выборку (.parquet)")
    ap.add_argument("--gates", default="",
                    help="через запятую: проверить признаки КАК ГЕЙТ против полной базы")
    a = ap.parse_args()

    print(f"МЕХАНИКА ВОЛНЫ C на {a.tf}: CHoCH → коррекция {PB} от A → цель |A|×{WAVE_K}, "
          f"стоп за экстремум B, TTL {TTL}, ждём откат {WAIT_PB} баров")
    print("Вопрос: добавляет ли SMC-конфлюэнция СВЕРХ самого волнового контекста.\n")

    R = collect(wave_c, tf=a.tf, n_symbols=a.coins, core=a.core)

    if a.save:
        try:
            R.to_parquet(a.save)
            print(f"выборка сохранена: {a.save} ({len(R)} сделок) — "
                  f"повторный анализ без пересчёта")
        except Exception as e:                       # noqa: BLE001
            print(f"сохранить не вышло: {type(e).__name__}: {e}")

    print("\n" + "=" * 78)
    print("ОБЯЗАТЕЛЬНЫЕ СРЕЗЫ (база механики — без всяких фильтров)")
    print("=" * 78)
    report(R)

    # режим года — харнесс его не печатает, а без него «год» читается неверно
    print("\nРЕЖИМ ГОДА (медиана % net по сделкам года — бык/медведь по нашей выборке):")
    for y, g in R.groupby("year"):
        if len(g) < 30:
            continue
        print(f"    {int(y)}  n={len(g):>4}  медиана {g['pnl'].median():+.2f}%  "
              f"доля плюсовых {(g['pnl'] > 0).mean() * 100:.0f}%  "
              f"монет+ {(g.groupby('sym')['pnl'].sum() > 0).mean() * 100:.0f}%")

    if a.gates:
        print("\n" + "=" * 78)
        print("ГЕЙТЫ ПРОТИВ ПОЛНОЙ БАЗЫ (сколько потока режем и что получаем)")
        print("=" * 78)
        gates_vs_full_base(R, [g.strip() for g in a.gates.split(",") if g.strip()])

    print("\n" + "=" * 78)
    print("СЛЕПОЙ ОТБОР IS→OOS: какие признаки добавляют к механике")
    print("=" * 78)
    blind_select(R)

    print("\n" + "=" * 78)
    print("ТО ЖЕ ПО НЕПРЕРЫВНЫМ ПРИЗНАКАМ (пороги по децилям, не f>0)")
    print("=" * 78)
    try:
        blind_select_num(R)
    except Exception as e:                           # noqa: BLE001
        print(f"  blind_select_num недоступен: {type(e).__name__}: {e}")

    # сколько SMC-признаков вообще доехало — иначе вывод «SMC не помог» будет ложным
    from research_harness import feature_cols
    cols = feature_cols(R)
    smc = [c for c in cols if any(k in c.lower() for k in
                                  ("ob_", "fvg", "choch", "bos", "eqh", "eql", "ote",
                                   "liq", "sweep", "breaker", "premium", "discount"))]
    print(f"\nSMC-признаков в наборе: {len(smc)} из {len(cols)} "
          f"(если 0 — вывод про SMC делать НЕЛЬЗЯ: признака нет, а не эффекта)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
