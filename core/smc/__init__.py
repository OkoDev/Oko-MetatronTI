"""
SMC Layer — Smart Money Concepts.

Аналитический пакет: структура рынка + зоны интереса.
Выдаёт SMCContext (контекст), НЕ торговые сигналы.

Модули:
  swing_points  — Swing H/L с чередованием + HH/HL/LH/LL
  structure     — BOS / CHoCH + breaker blocks
  fvg           — Fair Value Gaps + mitigation tracking
  order_blocks  — Order Blocks (последняя свеча перед BOS)
  liquidity     — Кластеры ликвидности (swept/unswept)
  fibonacci     — OTE зона (0.618–0.786)
  models        — SMCContext dataclass + analyze_smc()
  confluence    — ARCH-28: FVG + Pivot confluence map

Использование:
  from core.smc import analyze_smc, SMCContext
  ctx = analyze_smc(df_15m)
  print(ctx.summary())

  from core.smc.confluence import find_fvg_pivot_confluences
  zones = find_fvg_pivot_confluences(ctx.fvg, pivot_levels, price)
"""
from core.smc.models import SMCContext, analyze_smc
from core.smc.confluence import find_fvg_pivot_confluences, format_confluence_zones

__all__ = ["SMCContext", "analyze_smc", "find_fvg_pivot_confluences", "format_confluence_zones"]
