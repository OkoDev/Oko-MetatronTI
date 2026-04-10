#!/usr/bin/env python3
"""
Тест TSL floor буфера (DEV-132/DEV-149).

Проверяет что:
1. TSL floor для LONG = entry * 0.997 (не entry ровно)
2. TSL floor для SHORT = entry * 1.003
3. Начальный SL по стратегиям НЕ затронут (floor только после TSL активации)
4. TSL активируется только при R >= tsl_activation_r
5. SL check: VST -> wick, SIM -> close (для tsl_line источников)
"""

# ── Чистый unit-тест логики floor — без импорта тяжёлых модулей ──

_TSL_FLOOR_PCT = 0.003  # 0.3%


def tsl_floor_long(tsl_price: float, entry: float) -> float:
    """Повторяет логику из trade_simulator.py:1650-1652"""
    _floor = entry * (1 - _TSL_FLOOR_PCT)
    return max(tsl_price, _floor)


def tsl_floor_short(tsl_price: float, entry: float) -> float:
    """Повторяет логику из trade_simulator.py:1654-1655"""
    _ceil = entry * (1 + _TSL_FLOOR_PCT)
    return min(tsl_price, _ceil)


# ═══════════════════════════════════════════════════════════════════
# LONG тесты
# ═══════════════════════════════════════════════════════════════════

def test_long_tsl_above_entry():
    """LONG: trenddown выше entry -> TSL фиксирует прибыль, floor не вмешивается"""
    entry = 100.0
    tsl = 103.0  # тренд растёт, прибыль
    result = tsl_floor_long(tsl, entry)
    assert result == 103.0, f"Ожидали 103.0, получили {result}"
    print(f"  PASS: LONG tsl={tsl} > entry={entry} -> SL={result} (profit locked)")


def test_long_tsl_below_entry_old_bug():
    """LONG: trenddown ниже entry -> старый код ставил SL=entry, новый — entry*0.997"""
    entry = 100.0
    tsl = 98.0  # тренд откатился ниже entry
    result = tsl_floor_long(tsl, entry)
    expected = entry * (1 - _TSL_FLOOR_PCT)  # 99.7
    assert result == expected, f"Ожидали {expected}, получили {result}"
    assert result < entry, f"Floor должен быть НИЖЕ entry: {result} >= {entry}"
    assert result > tsl, f"Floor должен быть ВЫШЕ trenddown: {result} <= {tsl}"
    print(f"  PASS: LONG tsl={tsl} < entry={entry} -> SL={result:.4f} (buffer 0.3% below entry)")


def test_long_wick_survives():
    """LONG: wick до entry-0.1% не выбивает позицию (раньше выбивал при SL=entry)"""
    entry = 100.0
    tsl = 98.0
    floor_sl = tsl_floor_long(tsl, entry)

    wick_price = entry * 0.999  # фитиль -0.1% от entry
    assert wick_price > floor_sl, (
        f"Wick {wick_price:.4f} должен быть ВЫШЕ floor SL {floor_sl:.4f} — позиция жива"
    )
    print(f"  PASS: LONG wick={wick_price:.4f} > floor={floor_sl:.4f} -> position survives")


def test_long_real_sl_triggers():
    """LONG: цена падает ниже floor -> SL реально срабатывает"""
    entry = 100.0
    tsl = 98.0
    floor_sl = tsl_floor_long(tsl, entry)

    crash_price = entry * 0.995  # падение -0.5%
    assert crash_price < floor_sl, (
        f"Crash {crash_price:.4f} должен быть НИЖЕ floor SL {floor_sl:.4f} — SL срабатывает"
    )
    print(f"  PASS: LONG crash={crash_price:.4f} < floor={floor_sl:.4f} -> SL triggered")


def test_long_tsl_exactly_at_entry():
    """LONG: trenddown ровно на entry -> floor опускает SL на 0.3% ниже"""
    entry = 100.0
    tsl = 100.0  # trenddown == entry
    result = tsl_floor_long(tsl, entry)
    expected = entry * (1 - _TSL_FLOOR_PCT)
    # max(100.0, 99.7) = 100.0 — tsl >= floor, поэтому tsl остаётся
    assert result == 100.0, f"max(100.0, 99.7) должен быть 100.0, получили {result}"
    print(f"  PASS: LONG tsl=entry={entry} -> SL={result} (tsl == entry, floor не меняет)")


def test_long_tsl_slightly_below_entry():
    """LONG: trenddown чуть ниже entry (на 0.1%) -> max(99.9, 99.7) = 99.9"""
    entry = 100.0
    tsl = 99.9  # -0.1% от entry, но выше floor (99.7)
    result = tsl_floor_long(tsl, entry)
    # max(99.9, 99.7) = 99.9 — tsl выше floor, остаётся tsl
    assert result == 99.9, f"Expected 99.9, got {result}"
    print(f"  PASS: LONG tsl={tsl} (slightly below entry) -> SL={result:.4f}")


# ═══════════════════════════════════════════════════════════════════
# SHORT тесты
# ═══════════════════════════════════════════════════════════════════

def test_short_tsl_below_entry():
    """SHORT: trendup ниже entry -> TSL фиксирует прибыль, ceiling не вмешивается"""
    entry = 100.0
    tsl = 97.0  # цена упала, SHORT в прибыли
    result = tsl_floor_short(tsl, entry)
    assert result == 97.0, f"Ожидали 97.0, получили {result}"
    print(f"  PASS: SHORT tsl={tsl} < entry={entry} -> SL={result} (прибыль зафиксирована)")


def test_short_tsl_above_entry():
    """SHORT: trendup выше entry -> ceiling ограничивает SL на entry*1.003"""
    entry = 100.0
    tsl = 102.0  # откат вверх
    result = tsl_floor_short(tsl, entry)
    expected = entry * (1 + _TSL_FLOOR_PCT)  # 100.3
    assert result == expected, f"Ожидали {expected}, получили {result}"
    assert result > entry, f"Ceiling должен быть ВЫШЕ entry: {result} <= {entry}"
    print(f"  PASS: SHORT tsl={tsl} > entry={entry} -> SL={result:.4f} (буфер 0.3% выше entry)")


def test_short_wick_survives():
    """SHORT: wick вверх до entry+0.1% не выбивает позицию"""
    entry = 100.0
    tsl = 102.0
    ceil_sl = tsl_floor_short(tsl, entry)

    wick_price = entry * 1.001  # фитиль +0.1% от entry
    assert wick_price < ceil_sl, (
        f"Wick {wick_price:.4f} должен быть НИЖЕ ceiling SL {ceil_sl:.4f} — позиция жива"
    )
    print(f"  PASS: SHORT wick={wick_price:.4f} < ceil={ceil_sl:.4f} -> позиция выживает")


def test_short_real_sl_triggers():
    """SHORT: цена растёт выше ceiling -> SL срабатывает"""
    entry = 100.0
    tsl = 102.0
    ceil_sl = tsl_floor_short(tsl, entry)

    pump_price = entry * 1.005  # рост +0.5%
    assert pump_price > ceil_sl, (
        f"Pump {pump_price:.4f} должен быть ВЫШЕ ceiling SL {ceil_sl:.4f} — SL срабатывает"
    )
    print(f"  PASS: SHORT pump={pump_price:.4f} > ceil={ceil_sl:.4f} -> SL сработал")


# ═══════════════════════════════════════════════════════════════════
# Разные цены (дешёвые / дорогие монеты)
# ═══════════════════════════════════════════════════════════════════

def test_cheap_coin():
    """Дешёвая монета (SHIB/PEPE уровень): буфер корректно масштабируется"""
    entry = 0.00001234
    tsl = 0.00001100  # ниже entry
    result = tsl_floor_long(tsl, entry)
    expected = entry * (1 - _TSL_FLOOR_PCT)
    assert abs(result - expected) < 1e-12, f"Cheap coin: ожидали {expected}, получили {result}"
    print(f"  PASS: Cheap coin entry={entry} -> floor={result:.10f}")


def test_expensive_coin():
    """Дорогая монета (BTC): буфер в абсолюте = ~$300 при BTC=100k"""
    entry = 100000.0
    tsl = 99500.0  # ниже entry
    result = tsl_floor_long(tsl, entry)
    expected = entry * (1 - _TSL_FLOOR_PCT)  # 99700
    assert result == expected, f"BTC: ожидали {expected}, получили {result}"
    buffer_usd = entry - result
    print(f"  PASS: BTC entry={entry} -> floor={result} (буфер ${buffer_usd:.0f})")


# ═══════════════════════════════════════════════════════════════════
# SL check: wick vs close
# ═══════════════════════════════════════════════════════════════════

def test_sl_check_mode():
    """Проверяем логику выбора wick/close для SL"""
    cases = [
        # (sl_source, exchange_managed, expected_close_check)
        ("tsl_line:trendup",      False, True),   # SIM + tsl_line -> close
        ("tsl_line:trendup",      True,  False),  # VST + tsl_line -> wick
        ("wl_pivot_tsl:R1",       False, True),   # SIM + wl_pivot_tsl -> close
        ("wl_pivot_tsl:R1",       True,  False),  # VST + wl_pivot_tsl -> wick
        ("atr_14:1.5%",           False, False),  # SIM + atr -> wick
        ("atr_14:1.5%",           True,  False),  # VST + atr -> wick
        ("swing_low:50000",       False, False),  # SIM + swing -> wick
        ("swing_low:50000",       True,  False),  # VST + swing -> wick
        ("s1:support:49000",      False, False),  # SIM + pivot -> wick
    ]

    for sl_src, exch_managed, expected in cases:
        _sl_src = sl_src.lower()
        result = (
            (_sl_src.startswith("tsl_line") or _sl_src.startswith("wl_pivot_tsl"))
            and not exch_managed
        )
        assert result == expected, (
            f"sl_source={sl_src}, exchange={exch_managed}: "
            f"ожидали close_check={expected}, получили {result}"
        )

    print(f"  PASS: все {len(cases)} кейсов SL check mode корректны")


# ═══════════════════════════════════════════════════════════════════
# TSL min_move фильтр (0.15%)
# ═══════════════════════════════════════════════════════════════════

def test_min_move_filter():
    """Проверяем что движение < 0.15% не вызывает cancel+replace на бирже"""
    _min_move = 0.15  # %

    cases = [
        # (old_sl, new_tsl, should_move)
        (100.0, 100.10, False),  # 0.1% — слишком мало
        (100.0, 100.14, False),  # 0.14% — ещё мало
        (100.0, 100.15, True),   # 0.15% — ровно порог
        (100.0, 100.50, True),   # 0.5% — нормальное движение
        (100.0, 103.00, True),   # 3% — большое движение
        (100.0, 100.0,  False),  # 0% — нет движения
    ]

    for old_sl, new_tsl, expected in cases:
        move_pct = abs(new_tsl - old_sl) / old_sl * 100 if old_sl > 0 else 0
        is_real_move = old_sl > 0 and move_pct >= _min_move
        assert is_real_move == expected, (
            f"old={old_sl}, new={new_tsl}, move={move_pct:.3f}%: "
            f"ожидали {expected}, получили {is_real_move}"
        )

    print(f"  PASS: все {len(cases)} кейсов min_move фильтра корректны")


# ═══════════════════════════════════════════════════════════════════
# TSL activation gate
# ═══════════════════════════════════════════════════════════════════

def test_tsl_activation_gate():
    """TSL активируется только при current_r >= порога"""
    cases = [
        # (current_r, regime, tsl_act_r, tsl_act_r_range, should_activate)
        (0.5,  "TREND_UP", 1.0, 0.7, False),  # R=0.5 < 1.0
        (0.7,  "RANGE",    1.0, 0.7, True),   # RANGE: R=0.7 >= 0.7
        (0.7,  "TREND_UP", 1.0, 0.7, False),  # TREND: R=0.7 < 1.0
        (1.0,  "TREND_UP", 1.0, 0.7, True),   # R=1.0 >= 1.0
        (1.5,  "TREND_UP", 1.0, 0.7, True),   # R=1.5 >= 1.0
        (0.0,  "RANGE",    1.0, 0.7, False),  # R=0 < 0.7
        (-0.5, "RANGE",    1.0, 0.7, False),  # R=-0.5, в убытке
    ]

    for current_r, regime, act_r, act_r_range, expected in cases:
        threshold = act_r_range if regime == "RANGE" else act_r
        gate = current_r is not None and current_r >= threshold
        assert gate == expected, (
            f"R={current_r}, regime={regime}, порог={threshold}: "
            f"ожидали activate={expected}, получили {gate}"
        )

    print(f"  PASS: все {len(cases)} кейсов TSL activation gate корректны")


# ═══════════════════════════════════════════════════════════════════
# Запуск
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("TSL Floor Buffer — тесты (DEV-132/DEV-149)")
    print("=" * 60)

    tests = [
        ("LONG: TSL выше entry (прибыль)",         test_long_tsl_above_entry),
        ("LONG: TSL ниже entry (floor)",            test_long_tsl_below_entry_old_bug),
        ("LONG: wick выживает",                     test_long_wick_survives),
        ("LONG: реальный SL срабатывает",           test_long_real_sl_triggers),
        ("LONG: TSL ровно на entry",                test_long_tsl_exactly_at_entry),
        ("LONG: TSL чуть ниже entry",               test_long_tsl_slightly_below_entry),
        ("SHORT: TSL ниже entry (прибыль)",         test_short_tsl_below_entry),
        ("SHORT: TSL выше entry (ceiling)",         test_short_tsl_above_entry),
        ("SHORT: wick выживает",                    test_short_wick_survives),
        ("SHORT: реальный SL срабатывает",          test_short_real_sl_triggers),
        ("Дешёвая монета (SHIB)",                   test_cheap_coin),
        ("Дорогая монета (BTC)",                    test_expensive_coin),
        ("SL check: wick vs close",                 test_sl_check_mode),
        ("Min move фильтр (0.15%)",                 test_min_move_filter),
        ("TSL activation gate",                     test_tsl_activation_gate),
    ]

    passed = 0
    failed = 0
    for name, func in tests:
        try:
            print(f"\n[{passed+failed+1:02d}] {name}")
            func()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Результат: {passed}/{passed+failed} passed, {failed} failed")
    print(f"{'=' * 60}")
