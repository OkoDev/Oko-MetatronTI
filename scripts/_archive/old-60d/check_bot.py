#!/usr/bin/env python
"""Проверка целостности бота"""
import sys

print('🔍 Проверка целостности бота...')
print('-' * 60)

try:
    # 1. Импорты
    print('1️⃣ Импорты...')
    from core.trading_intelligence import TradingIntelligence
    from core.infra.data_collector import RealTimeData
    from core.infra.config_loader import config
    from strategies import list_strategies, get_strategy
    print('   ✅ Все импорты OK')

    # 2. Конфиг
    print('\n2️⃣ Конфигурация...')
    strat_name = config.get('strategy.name', 'confluence')
    print(f'   ✅ Config loaded')
    print(f'   ✅ Active strategy: {strat_name}')

    # 3. RealTimeData
    print('\n3️⃣ RealTimeData...')
    dc = RealTimeData(exchange_id=config.get('exchanges.default', 'bingx'))
    print(f'   ✅ Created')

    # 4. TradingIntelligence
    print('\n4️⃣ TradingIntelligence...')
    ti = TradingIntelligence(
        data_collector=dc,
        config=config.get_all(),
        db_path='subscriptions.db'
    )
    strat_cls = ti.strategy.__class__.__name__ if ti.strategy else 'None (legacy mode)'
    print(f'   ✅ Created')
    print(f'   ✅ Strategy: {strat_cls}')

    # 5. Стратегии
    print('\n5️⃣ Стратегии...')
    strats = list_strategies()
    print(f'   ✅ Registered: {strats}')

    print('\n' + '='*60)
    print('🟢 БОТ ИНТАКТЕН - ВСЕ СИСТЕМЫ РАБОТАЮТ!')
    print('='*60)
    
except Exception as e:
    print(f'\n❌ ОШИБКА: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
