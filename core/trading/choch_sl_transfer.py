"""CHoCH-перенос SL — после первого LTF-CHoCH в сторону сделки подтянуть SL за структуру.

Валидировано в honest-backtest (struct_choch_tp1 +0.315R vs голый tp1 +0.296R, 38473 сделки,
4 года, WF 13/15 OOS+). [[ote_production_drift_root]]. Применяется к ote_nested OPEN ОДИН раз
(флаг choch_sl_moved). Логика = research struct_choch: широкий SL (импульс-1.0) на входе → при
первом CHoCH (разворот подтверждён) SL за структурный экстремум отката → урезает убыток <−1R.

Решения (Егор 29.06): только ote_nested · только СУЖЕНИЕ SL (теснее, не шире) · выход остаётся tp1.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

CHOCH_BUF = 0.0005   # микро-буфер за структурный swing


def compute_choch_sl(df_ltf, entry_ts, direction, current_sl):
    """new_sl за LTF-структуру после ПЕРВОГО CHoCH в сторону сделки. ТОЛЬКО если теснее.

    Возвращает round(new_sl, 8) | None (нет CHoCH / не теснее / мало данных).
    LONG: CHoCH bull → SL за swing-low отката (higher-low). SHORT: CHoCH bear → за swing-high.
    """
    if df_ltf is None or len(df_ltf) < 12 or not current_sl or current_sl <= 0:
        return None
    try:
        from core.smc.smc_engine import detect_structure_breaks
        d = df_ltf[df_ltf.index > entry_ts]
        if len(d) < 8:
            return None
        is_long = str(direction).lower() == "long"
        want = "bull" if is_long else "bear"
        breaks = detect_structure_breaks(d, length=5)
        choch = next((b for b in breaks if b.kind == "CHoCH" and b.direction == want), None)
        if choch is None:
            return None
        seg = d[d.index <= choch.ts]          # откат до момента разворота (CHoCH)
        if len(seg) < 2:
            return None
        if is_long:
            sw = float(seg["low"].min())      # структурный low отката = новый higher-low
            new_sl = sw * (1 - CHOCH_BUF)
            if new_sl > float(current_sl):    # теснее = выше для long
                return round(new_sl, 8)
        else:
            sw = float(seg["high"].max())     # структурный high отката = новый lower-high
            new_sl = sw * (1 + CHOCH_BUF)
            if new_sl < float(current_sl):    # теснее = ниже для short
                return round(new_sl, 8)
    except Exception as e:
        logger.debug("[CHoCH-SL] %s entry=%s: %s", direction, entry_ts, e)
    return None


async def apply_choch_transfer(bot) -> list:
    """Для ote_nested OPEN без choch_sl_moved: детект CHoCH на LTF → подтянуть SL за структуру.
    Обновляет БД (stop_loss + choch_sl_moved=1) и возвращает tsl_moved-формат для синка на биржу.
    Один перенос на сделку. Только сужение SL (compute_choch_sl возвращает только теснее)."""
    import sqlite3
    import pandas as pd

    ts = getattr(bot, "trade_simulator", None)
    dc = getattr(bot, "data_collector", None)
    if ts is None or dc is None:
        return []
    db = ts.db_path
    moved: list = []
    try:
        with sqlite3.connect(db, timeout=30) as conn:
            rows = conn.execute(
                """SELECT id, symbol, direction, stop_loss, created_at, features_json, exchange_sl_order_id
                   FROM simulated_trades WHERE status='OPEN' AND source_router='ote_nested'
                   AND COALESCE(choch_sl_moved, 0) = 0 AND stop_loss > 0"""
            ).fetchall()
    except Exception as e:
        logger.debug("[CHoCH-SL] read: %s", e)
        return []

    for tid, symbol, direction, cur_sl, created, fj, sl_oid in rows:
        try:
            import json
            f = json.loads(fj) if fj else {}
            ltf = f.get("ote_ltf") or "15m"
            df = await dc.get_ohlcv(symbol, timeframe=ltf, limit=300)
            if df is None or len(df) < 12:
                continue
            entry_ts = pd.to_datetime(created, utc=True)
            new_sl = compute_choch_sl(df, entry_ts, direction, cur_sl)
            if not new_sl:
                continue
            with sqlite3.connect(db, timeout=30) as conn:
                conn.execute("UPDATE simulated_trades SET stop_loss=?, choch_sl_moved=1 WHERE id=?",
                             (new_sl, tid))
                conn.commit()
            logger.info("[CHoCH-SL] #%s %s %s: SL %.6g→%.6g (перенос за структуру после CHoCH)",
                        tid, symbol, direction, cur_sl, new_sl)
            moved.append({"trade_id": tid, "symbol": symbol, "direction": direction,
                          "new_sl_price": new_sl, "old_sl_price": cur_sl,
                          "exchange_sl_order_id": sl_oid})
        except Exception as e:
            logger.debug("[CHoCH-SL] #%s: %s", tid, e)
    return moved
