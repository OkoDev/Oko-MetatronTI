"""
DS-321: TSL backtest — жёсткий (текущий) vs адаптивный (ATR-based).

Тестирует на закрытых сделках arch104 + ote_nested:
  - Текущий TSL: tsl_activation_r=1.0, be_activation_r=0.5, жёсткие уровни
  - Адаптивный: ATR-эскалация/деэскалация, BE только после MFE > 1 ATR

Использует реальные max_price/min_price из БД чтобы симулировать
движение цены и рассчитать когда бы сработал TSL.
"""
import sqlite3
import sys
import statistics
from dataclasses import dataclass, field
from typing import Optional

DB = "subscriptions.db"


# ═══════════════════════════════════════════════════════════════
# Модель сделки
# ═══════════════════════════════════════════════════════════════

@dataclass
class TradeSnapshot:
    symbol: str
    direction: str          # LONG / SHORT
    entry: float
    original_sl: float
    original_tp: float
    max_price: float
    min_price: float
    exit_price: float
    actual_r: float
    max_r_possible: float
    captured_r_pct: float
    tsl_activated: bool
    be_activated: bool
    first_profit_r: float
    first_drawdown_r: float
    signal_type: str
    duration_min: float


def load_trades(signal_types: list = None) -> list[TradeSnapshot]:
    """Загружает закрытые сделки с ценами из БД."""
    conn = sqlite3.connect(DB)
    query = """
        SELECT symbol, direction, entry_price, original_sl, take_profit,
               max_price, min_price, exit_price, R_multiple, max_R_possible,
               captured_R_pct, tsl_activated, be_activated,
               first_profit_r, first_drawdown_r,
               signal_type, duration_minutes
        FROM simulated_trades
        WHERE status IN ('TSL','TP','SL')
          AND max_price IS NOT NULL AND entry_price IS NOT NULL
          AND entry_price > 0
          AND original_sl IS NOT NULL
          AND created_at >= '2026-05-31'
    """
    if signal_types:
        placeholders = ",".join("?" * len(signal_types))
        query += f" AND signal_type IN ({placeholders})"
        rows = conn.execute(query, signal_types).fetchall()
    else:
        rows = conn.execute(query).fetchall()
    conn.close()

    trades = []
    for r in rows:
        trades.append(TradeSnapshot(
            symbol=r[0], direction=r[1], entry=float(r[2]),
            original_sl=float(r[3]) if r[3] else None,
            original_tp=float(r[4]) if r[4] else None,
            max_price=float(r[5]), min_price=float(r[6]),
            exit_price=float(r[7]), actual_r=float(r[8]) if r[8] else 0,
            max_r_possible=float(r[9]) if r[9] else 0,
            captured_r_pct=float(r[10]) if r[10] else 0,
            tsl_activated=bool(r[11]), be_activated=bool(r[12]),
            first_profit_r=float(r[13]) if r[13] else 0,
            first_drawdown_r=float(r[14]) if r[14] else 0,
            signal_type=r[15], duration_min=float(r[16]) if r[16] else 0,
        ))
    return trades


# ═══════════════════════════════════════════════════════════════
# Текущий TSL (жёсткий)
# ═══════════════════════════════════════════════════════════════

def simulate_current_tsl(t: TradeSnapshot,
                          tsl_activation_r: float = 1.0,
                          be_activation_r: float = 0.5) -> dict:
    """
    Симулирует текущий TSL.
    Сценарий: цена идёт от entry → max/min → exit.
    TSL активируется при +1R (версия h1).
    BE при +0.5R.
    """
    if t.direction == "LONG":
        sl_dist = t.entry - t.original_sl
        if sl_dist <= 0:
            return _fail("no_sl_dist")
        tp_dist = t.original_tp - t.entry if t.original_tp else sl_dist * 3

        be_price = t.entry
        tsl_active = False
        be_active = False
        current_sl = t.original_sl
        tsl_hit = False
        be_hit = False
        exit_r = 0.0

        # Симуляция: цена растёт к max, потом падает к exit
        peak_r = (t.max_price - t.entry) / sl_dist

        if peak_r >= be_activation_r:
            be_active = True
            current_sl = max(current_sl, be_price)
        if peak_r >= tsl_activation_r:
            tsl_active = True
            # TSL на уровне entry + (peak_r - 1) * sl_dist * 0.5
            # Упрощённо: TSL = max(entry, max_price - 1.5 * sl_dist)
            tsl_level = max(t.entry, t.max_price - 1.5 * sl_dist)
            current_sl = max(current_sl, tsl_level)

        # Проверка: пробила ли цена TSL на пути вниз?
        if current_sl > t.exit_price:
            tsl_hit = True
            exit_r = (current_sl - t.entry) / sl_dist
        else:
            exit_r = (t.exit_price - t.entry) / sl_dist

    else:  # SHORT
        sl_dist = t.original_sl - t.entry
        if sl_dist <= 0:
            return _fail("no_sl_dist")
        tp_dist = t.entry - t.original_tp if t.original_tp else sl_dist * 3

        be_price = t.entry
        tsl_active = False
        be_active = False
        current_sl = t.original_sl
        tsl_hit = False
        be_hit = False
        exit_r = 0.0

        peak_r = (t.entry - t.min_price) / sl_dist

        if peak_r >= be_activation_r:
            be_active = True
            current_sl = min(current_sl, be_price)
        if peak_r >= tsl_activation_r:
            tsl_active = True
            tsl_level = min(t.entry, t.min_price + 1.5 * sl_dist)
            current_sl = min(current_sl, tsl_level)

        if current_sl < t.exit_price:
            tsl_hit = True
            exit_r = (t.entry - current_sl) / sl_dist
        else:
            exit_r = (t.entry - t.exit_price) / sl_dist

    return {
        "exit_r": exit_r,
        "tsl_active": tsl_active,
        "be_active": be_active,
        "tsl_hit": tsl_hit,
        "be_hit": be_hit,
        "peak_r": peak_r,
        "final_sl": current_sl,
    }


# ═══════════════════════════════════════════════════════════════
# Адаптивный TSL v2 — многослойный
# ═══════════════════════════════════════════════════════════════

def simulate_adaptive_tsl(t: TradeSnapshot) -> dict:
    """
    Слои:
      1. Multi-TF ATR: max(entry_atr, htf_atr * 0.3)
      2. HTF impulse: MFE > 2 ATR -> шире TSL +50%
      3. Time decay: дольше без движения -> TSL сжимается до -50% за 24ч
      4. BE: только при MFE > 1.5 ATR (сделка реально пошла)
      5. TP1 partial: 50% при MFE > 2 ATR
    """
    if t.direction == "LONG":
        sl_dist = t.entry - t.original_sl
        if sl_dist <= 0:
            return _fail("no_sl_dist")

        # Слой 1: Multi-TF ATR
        entry_atr = sl_dist / 1.5
        total_range_pct = abs(t.max_price - t.min_price) / t.entry * 100
        htf_atr_est = max(entry_atr, total_range_pct / 100 * t.entry * 0.4)
        effective_atr = max(entry_atr, htf_atr_est * 0.3)

        mfe_atr = (t.max_price - t.entry) / effective_atr

        # Слой 2: HTF impulse
        is_impulse = mfe_atr > 2.0
        impulse_mult = 1.5 if is_impulse else 1.0

        # Слой 3: Time decay
        if t.duration_min > 0:
            time_factor = max(0.5, 1.0 - (t.duration_min / 1440) * 0.5)
        else:
            time_factor = 1.0

        # BE: только MFE > 1.5 ATR
        be_active = mfe_atr >= 1.5
        be_price = t.entry
        current_sl = t.original_sl

        if be_active:
            current_sl = max(current_sl, be_price)

        # TSL: адаптивная дистанция × модификаторы
        if mfe_atr > 0.5:
            base_tsl_dist = max(0.4, 1.0 - mfe_atr * 0.2)
            tsl_atr_dist = base_tsl_dist * impulse_mult * time_factor
            tsl_atr_dist = min(tsl_atr_dist, 2.0)
            tsl_level = t.max_price - tsl_atr_dist * effective_atr
            current_sl = max(current_sl, tsl_level)

        # Слой 5: TP1 partial
        tp1_partial = mfe_atr >= 2.0
        tp1_price = t.entry + 2 * effective_atr if tp1_partial else None

        tsl_hit = current_sl > t.exit_price
        tsl_active = mfe_atr > 0.5
        exit_r = max((current_sl - t.entry), (t.exit_price - t.entry)) / sl_dist

    else:  # SHORT
        sl_dist = t.original_sl - t.entry
        if sl_dist <= 0:
            return _fail("no_sl_dist")

        entry_atr = sl_dist / 1.5
        total_range_pct = abs(t.max_price - t.min_price) / t.entry * 100
        htf_atr_est = max(entry_atr, total_range_pct / 100 * t.entry * 0.4)
        effective_atr = max(entry_atr, htf_atr_est * 0.3)

        mfe_atr = (t.entry - t.min_price) / effective_atr

        is_impulse = mfe_atr > 2.0
        impulse_mult = 1.5 if is_impulse else 1.0

        if t.duration_min > 0:
            time_factor = max(0.5, 1.0 - (t.duration_min / 1440) * 0.5)
        else:
            time_factor = 1.0

        be_active = mfe_atr >= 1.5
        be_price = t.entry
        current_sl = t.original_sl

        if be_active:
            current_sl = min(current_sl, be_price)

        if mfe_atr > 0.5:
            base_tsl_dist = max(0.4, 1.0 - mfe_atr * 0.2)
            tsl_atr_dist = base_tsl_dist * impulse_mult * time_factor
            tsl_atr_dist = min(tsl_atr_dist, 2.0)
            tsl_level = t.min_price + tsl_atr_dist * effective_atr
            current_sl = min(current_sl, tsl_level)

        tp1_partial = mfe_atr >= 2.0
        tp1_price = t.entry - 2 * effective_atr if tp1_partial else None

        tsl_hit = current_sl < t.exit_price
        tsl_active = mfe_atr > 0.5
        exit_r = max((t.entry - current_sl), (t.entry - t.exit_price)) / sl_dist

    return {
        "exit_r": exit_r,
        "tsl_active": tsl_active,
        "be_active": be_active,
        "tsl_hit": tsl_hit,
        "be_hit": False,
        "peak_r": mfe_atr,
        "final_sl": current_sl,
        "atr_est": effective_atr,
        "mfe_atr": mfe_atr,
        "impulse": is_impulse,
        "time_factor": time_factor,
        "tp1_partial": tp1_partial,
    }


# ═══════════════════════════════════════════════════════════════
# Адаптивный TSL v3 — ГИБРИДНАЯ КОРОБКА ПЕРЕДАЧ
# ═══════════════════════════════════════════════════════════════

def simulate_hybrid_tsl(t: TradeSnapshot) -> dict:
    """
    Переключение между v1 (простой ATR) и v2 (многослойный) по ходу сделки.
    
    Критерии переключения:
      Gear 1 (v1): MFE < 2 ATR — жёсткая защита, быстрый BE при 1 ATR
      Gear 2 (v2): MFE >= 2 ATR — расширение для импульса, HTF-контекст
      Gear 3 (v1 tight): MFE >= 4 ATR или duration > 12ч — фиксация
    
    Симуляция: предполагаем что сделка проходит стадии gear'ов
    последовательно (entry -> peak MFE -> exit).
    """
    if t.direction == "LONG":
        sl_dist = t.entry - t.original_sl
        if sl_dist <= 0:
            return _fail("no_sl_dist")

        entry_atr = sl_dist / 1.5
        mfe_atr = (t.max_price - t.entry) / entry_atr
        current_sl = t.original_sl
        gear = 1

        # Gear 1 (v1): разгон — BE при 1 ATR, TSL 0.8..0.3 ATR
        if mfe_atr >= 1.0:
            current_sl = max(current_sl, t.entry)  # BE
        if mfe_atr > 0.5:
            tsl_dist = max(0.3, 0.8 - mfe_atr * 0.15) * entry_atr
            tsl_level = t.max_price - tsl_dist
            current_sl = max(current_sl, max(t.entry, tsl_level))

        # Gear 2 (v2): MFE >= 2 ATR — переключаемся на широкий режим
        if mfe_atr >= 2.0:
            gear = 2
            total_range_pct = abs(t.max_price - t.min_price) / t.entry * 100
            htf_atr_est = max(entry_atr, total_range_pct / 100 * t.entry * 0.4)
            effective_atr = max(entry_atr, htf_atr_est * 0.3)
            # Пересчитываем TSL с HTF-контекстом и impulse multiplier
            tsl_dist_v2 = max(0.4, 1.0 - mfe_atr * 0.2) * effective_atr * 1.5
            tsl_level_v2 = t.max_price - tsl_dist_v2
            current_sl = max(current_sl, tsl_level_v2)

        # Gear 3 (v1 tight): MFE >= 4 ATR или duration > 12ч — фиксация
        if mfe_atr >= 4.0 or (t.duration_min > 720):
            gear = 3
            # Сжимаем TSL агрессивно: 0.3..0.1 ATR от пика
            tsl_dist_tight = max(0.1, 0.3 - (mfe_atr - 4) * 0.03) * entry_atr
            tsl_level_tight = t.max_price - tsl_dist_tight
            current_sl = max(current_sl, tsl_level_tight)

        be_active = mfe_atr >= 1.0
        tsl_hit = current_sl > t.exit_price
        tsl_active = mfe_atr > 0.5
        exit_r = max((current_sl - t.entry), (t.exit_price - t.entry)) / sl_dist

    else:  # SHORT
        sl_dist = t.original_sl - t.entry
        if sl_dist <= 0:
            return _fail("no_sl_dist")

        entry_atr = sl_dist / 1.5
        mfe_atr = (t.entry - t.min_price) / entry_atr
        current_sl = t.original_sl
        gear = 1

        if mfe_atr >= 1.0:
            current_sl = min(current_sl, t.entry)
        if mfe_atr > 0.5:
            tsl_dist = max(0.3, 0.8 - mfe_atr * 0.15) * entry_atr
            tsl_level = t.min_price + tsl_dist
            current_sl = min(current_sl, min(t.entry, tsl_level))

        if mfe_atr >= 2.0:
            gear = 2
            total_range_pct = abs(t.max_price - t.min_price) / t.entry * 100
            htf_atr_est = max(entry_atr, total_range_pct / 100 * t.entry * 0.4)
            effective_atr = max(entry_atr, htf_atr_est * 0.3)
            tsl_dist_v2 = max(0.4, 1.0 - mfe_atr * 0.2) * effective_atr * 1.5
            tsl_level_v2 = t.min_price + tsl_dist_v2
            current_sl = min(current_sl, tsl_level_v2)

        if mfe_atr >= 4.0 or (t.duration_min > 720):
            gear = 3
            tsl_dist_tight = max(0.1, 0.3 - (mfe_atr - 4) * 0.03) * entry_atr
            tsl_level_tight = t.min_price + tsl_dist_tight
            current_sl = min(current_sl, tsl_level_tight)

        be_active = mfe_atr >= 1.0
        tsl_hit = current_sl < t.exit_price
        tsl_active = mfe_atr > 0.5
        exit_r = max((t.entry - current_sl), (t.entry - t.exit_price)) / sl_dist

    return {
        "exit_r": exit_r,
        "tsl_active": tsl_active,
        "be_active": be_active,
        "tsl_hit": tsl_hit,
        "be_hit": False,
        "peak_r": mfe_atr,
        "final_sl": current_sl,
        "atr_est": entry_atr,
        "mfe_atr": mfe_atr,
        "gear": gear,
    }


def _fail(reason: str) -> dict:
    return {"exit_r": 0, "tsl_active": False, "be_active": False,
            "tsl_hit": False, "be_hit": False, "peak_r": 0,
            "final_sl": 0, "error": reason}


# ═══════════════════════════════════════════════════════════════
# Анализ
# ═══════════════════════════════════════════════════════════════

def analyze(title: str, trades: list[TradeSnapshot], mode: str):
    if not trades:
        print(f"\n{'='*60}")
        print(f"  {title}: нет сделок")
        return

    results = []
    for t in trades:
        if mode == "current":
            r = simulate_current_tsl(t)
        elif mode == "hybrid":
            r = simulate_hybrid_tsl(t)
        else:
            r = simulate_adaptive_tsl(t)

        if "error" in r:
            continue
        results.append((t, r))

    if not results:
        print(f"  {title}: все сделки отфильтрованы")
        return

    actual_rs = [tr.actual_r for tr, _ in results]
    sim_rs = [res["exit_r"] for tr, res in results]
    tsl_act = sum(1 for _, r in results if r["tsl_active"])
    be_act = sum(1 for _, r in results if r["be_active"])
    tsl_hit = sum(1 for _, r in results if r["tsl_hit"])
    improved = sum(1 for i in range(len(results))
                   if sim_rs[i] > actual_rs[i])
    worsened = sum(1 for i in range(len(results))
                   if sim_rs[i] < actual_rs[i])

    print(f"\n{'='*60}")
    print(f"  {title} ({mode}) — n={len(results)}")
    print(f"  R actual:     mean={statistics.mean(actual_rs):+.3f}  med={statistics.median(actual_rs):+.3f}  pos={sum(1 for x in actual_rs if x>0)/len(actual_rs)*100:.0f}%")
    print(f"  R simulated:  mean={statistics.mean(sim_rs):+.3f}  med={statistics.median(sim_rs):+.3f}  pos={sum(1 for x in sim_rs if x>0)/len(sim_rs)*100:.0f}%")
    print(f"  TSL active: {tsl_act}/{len(results)} ({tsl_act/len(results)*100:.0f}%)")
    print(f"  BE active:  {be_act}/{len(results)} ({be_act/len(results)*100:.0f}%)")
    print(f"  TSL hit:    {tsl_hit}/{len(results)} ({tsl_hit/len(results)*100:.0f}%)")
    delta = statistics.mean(sim_rs) - statistics.mean(actual_rs)
    print(f"  dR mean:    {delta:+.3f}R  (improved={improved} worsened={worsened})")

    # Топ улучшений и ухудшений
    diffs = [(sim_rs[i] - actual_rs[i], results[i][0], sim_rs[i], actual_rs[i])
             for i in range(len(results))]
    diffs.sort(key=lambda x: x[0], reverse=True)
    print(f"  Топ-3 улучшения:")
    for d, tr, sr, ar in diffs[:3]:
        print(f"    {tr.symbol:12s} {tr.direction:5s} {tr.signal_type:15s} " +
              f"actual={ar:+.2f}R sim={sr:+.2f}R delta={d:+.2f}R " +
              f"MFE={(tr.max_price-tr.entry)/tr.entry*100:+.1f}%")
    print(f"  Топ-3 ухудшения:")
    for d, tr, sr, ar in diffs[-3:]:
        print(f"    {tr.symbol:12s} {tr.direction:5s} {tr.signal_type:15s} " +
              f"actual={ar:+.2f}R sim={sr:+.2f}R delta={d:+.2f}R " +
              f"MFE={(tr.max_price-tr.entry)/tr.entry*100:+.1f}%")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("DS-321: TSL Backtest — жёсткий vs адаптивный")
    print("=" * 60)

    # Загружаем свежие сделки
    arch104 = load_trades(["arch104"])
    ote = load_trades(["ote_nested"])
    wt = load_trades(["wt_signal"])
    pivot = load_trades(["pivot_reversal"])
    div = load_trades(["divergence"])
    all_trades = arch104 + ote + wt + pivot + div

    print(f"Loaded: arch104={len(arch104)}, ote={len(ote)}, wt={len(wt)}, pivot={len(pivot)}, div={len(div)}, total={len(all_trades)}")

    # Анализ по группам
    for name, trades in [("arch104", arch104), ("ote_nested", ote), ("ALL", all_trades)]:
        analyze(f"[{name}] CURRENT TSL", trades, "current")
        analyze(f"[{name}] ADAPTIVE TSL v2", trades, "adaptive")
        analyze(f"[{name}] HYBRID TSL v3", trades, "hybrid")

    # Сравнительная сводка
    print(f"\n{'='*60}")
    print("  ВЫВОД")
    print("  Если dR > 0 -> адаптивный TSL лучше.")
    print("  Если TSL active % ниже -> адаптивный реже дёргает.")
    print("  Если BE active % выше -> адаптивный чаще защищает.")
    print("=" * 60)


if __name__ == "__main__":
    main()
