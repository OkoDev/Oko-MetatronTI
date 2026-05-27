"""
position_parser.py — единый парсер ответа BingX getPositions().

Hedge mode (BingX): для одной пары может быть две независимые позиции
с разным positionSide ("LONG"/"SHORT"). positionAmt в hedge всегда положительный.
Direction надо брать из positionSide, НЕ из знака positionAmt — это hedge bug
который мы уже трижды фиксили в разных файлах (order_manager, position_sync,
_detect_orphans).

Использование:
    from core.exchange.position_parser import parse_position, parse_positions, by_symbol_side

    parsed = parse_position(raw_pos_dict)   # → ParsedPosition | None
    items = parse_positions(positions_list) # → list[ParsedPosition]
    idx = by_symbol_side(items)             # → {(symbol_our, "LONG"|"SHORT"): ParsedPosition}
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class ParsedPosition:
    symbol_bx: str          # "BTC-USDT" — формат BingX
    symbol_our: str         # "BTC/USDT:USDT" — наш формат (ccxt-like)
    side: str               # "LONG" | "SHORT"
    qty: float              # абс. величина (positionAmt as abs)
    entry: float            # avgPrice / entryPrice
    mark: float             # markPrice (для PnL вычислений)
    leverage: int           # текущее плечо
    margin: float           # initial margin / isolated
    unrealized_pnl: float   # unrealizedProfit
    notional: float         # |qty| * mark
    raw: dict[str, Any]     # исходник, на случай если нужны редкие поля


def parse_position(p: dict[str, Any]) -> Optional[ParsedPosition]:
    """Парсит одну позицию из BingX getPositions response.

    Возвращает None если позиция пустая (qty=0) или невалидная (нет symbol).
    Direction берётся из positionSide; для one-way mode fallback на знак qty.
    """
    if not isinstance(p, dict):
        return None
    sym_bx = str(p.get("symbol") or "").strip()
    if not sym_bx:
        return None
    try:
        qty_raw = float(p.get("positionAmt") or p.get("availableAmt") or 0)
    except (TypeError, ValueError):
        return None
    if qty_raw == 0:
        return None

    side = str(p.get("positionSide") or "").upper().strip()
    if side not in ("LONG", "SHORT"):
        # one-way mode fallback (positionSide может быть пустой)
        side = "LONG" if qty_raw > 0 else "SHORT"

    from core.exchange.bingx_client import from_bingx_symbol
    sym_our = from_bingx_symbol(sym_bx)
    qty = abs(qty_raw)

    def _f(key: str, *fallbacks: str) -> float:
        for k in (key,) + fallbacks:
            v = p.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return 0.0

    entry = _f("avgPrice", "entryPrice", "markPrice")
    mark  = _f("markPrice", "avgPrice", "entryPrice")
    try:
        leverage = int(float(p.get("leverage") or 1))
    except (TypeError, ValueError):
        leverage = 1
    margin = _f("margin", "initialMargin", "isolatedMargin")
    if margin == 0 and qty > 0 and entry > 0 and leverage > 0:
        margin = qty * entry / leverage
    pnl = _f("unrealizedProfit", "unrealisedProfit", "pnl")
    notional = qty * mark if mark > 0 else qty * entry

    return ParsedPosition(
        symbol_bx=sym_bx, symbol_our=sym_our, side=side, qty=qty,
        entry=entry, mark=mark, leverage=leverage, margin=margin,
        unrealized_pnl=pnl, notional=notional, raw=p,
    )


def parse_positions(positions: Iterable[dict[str, Any]]) -> list[ParsedPosition]:
    """Парсит список позиций, отбрасывая пустые/невалидные."""
    out: list[ParsedPosition] = []
    for p in positions or []:
        pp = parse_position(p)
        if pp is not None:
            out.append(pp)
    return out


def by_symbol_side(items: Iterable[ParsedPosition]) -> dict[tuple[str, str], ParsedPosition]:
    """Индекс (symbol_our, side) → ParsedPosition для hedge-aware lookup.

    В hedge mode одна пара может быть и LONG и SHORT одновременно — ключ
    обязан включать side, иначе одна перезаписывает другую.
    """
    return {(pp.symbol_our, pp.side): pp for pp in items}


def by_symbol(items: Iterable[ParsedPosition]) -> dict[str, ParsedPosition]:
    """Индекс symbol_our → ParsedPosition. ОПАСНО для hedge: если LONG+SHORT
    по одной паре — последняя перезаписывает. Используй только когда явно знаешь
    что hedge не релевантен (например, has_open_position для legacy путей)."""
    return {pp.symbol_our: pp for pp in items}
