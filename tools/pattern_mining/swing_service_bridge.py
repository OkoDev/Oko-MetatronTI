"""ARCH-118.3 (05.06): мост перенесён в core/calculators/swing_bridge.py.

Этот файл — re-export для обратной совместимости research-скриптов
(combinator_v3_nested, composite_scoring, d051_t8_retest и др.), что импортируют
tools.pattern_mining.swing_service_bridge. Новый код → core.calculators.swing_bridge.
"""
from core.calculators.swing_bridge import *  # noqa: F401,F403
from core.calculators.swing_bridge import (  # noqa: F401
    etl_fvg, etl_order_blocks, etl_bos_choch, etl_ote_premium, etl_eql_eql,
    etl_swing_structure, etl_fvg_overlap, etl_elliott,
)
