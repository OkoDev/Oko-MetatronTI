import logging
from core.indicators import calculate_wt, calculate_trend, get_zone, detect_fvg

logger = logging.getLogger(__name__)

class AnomalyDetector:
    def __init__(self, volume_multiplier=5.0, price_threshold=7.0):
        self.volume_multiplier = volume_multiplier
        self.price_threshold = price_threshold

    def check_spike(self, symbol, data_collector):
        """Проверка всплесков объёма и резких изменений цены"""
        try:
            volumes = list(data_collector.volume_history.get(symbol, []))
            prices = list(data_collector.price_history.get(symbol, []))
            info = {}
            if len(volumes) >= 5:
                avg = sum(volumes[:-1]) / max(1, len(volumes[:-1]))
                cur = volumes[-1]
                if avg > 0 and cur > avg * self.volume_multiplier:
                    info["volume"] = {"current": cur, "average": avg, "ratio": cur / avg}
            if prices:
                cur_chg = prices[-1]
                if abs(cur_chg) >= self.price_threshold:
                    info["price_change"] = {"current": cur_chg, "threshold": self.price_threshold}
            return (len(info) > 0, info if info else None)
        except Exception:
            logger.exception(f"check_spike error for {symbol}")
            return False, None

    async def check_wt_signal(self, symbol, data_collector, n1=10, n2=21, timeframe="15m"):
        """WT сигнал на указанном timeframe"""
        try:
            df = await data_collector.get_ohlcv(symbol, timeframe=timeframe, limit=150)
            if df is None or df.empty:
                return False, None
            df = calculate_wt(df, n1=n1, n2=n2)
            df["oversold"] = df["wt1"] < -60
            df["overbought"] = df["wt1"] > 60
            df["cross_over"] = (df["wt1"].shift(1) < df["wt2"].shift(1)) & (df["wt1"] > df["wt2"])
            df["cross_under"] = (df["wt1"].shift(1) > df["wt2"].shift(1)) & (df["wt1"] < df["wt2"])
            last = df.iloc[-1]
            if last["cross_over"] and last["oversold"]:
                info = {"type": "WT_LONG", "symbol": symbol, "wt1": round(last["wt1"],2), "wt2": round(last["wt2"],2), "timeframe": timeframe}
                logger.info(f"[{symbol}] WT CrossOver in OS -> LONG")
                return True, info
            if last["cross_under"] and last["overbought"]:
                info = {"type": "WT_SHORT", "symbol": symbol, "wt1": round(last["wt1"],2), "wt2": round(last["wt2"],2), "timeframe": timeframe}
                logger.info(f"[{symbol}] WT CrossUnder in OB -> SHORT")
                return True, info
            return False, None
        except Exception:
            logger.exception(f"check_wt_signal error for {symbol}")
            return False, None

    async def check_mtf_signal(self, symbol, data_collector):
        """Простой составной MTF сигнал (1h trend + 15m WT + 3m zone/FVG)"""
        try:
            df_1h = await data_collector.get_ohlcv(symbol, "1h", limit=150)
            if df_1h is None or df_1h.empty:
                return False, None
            df_1h = calculate_trend(df_1h)
            trend_dir = df_1h["trend"].iloc[-1]

            df_15m = await data_collector.get_ohlcv(symbol, "15m", limit=150)
            if df_15m is None or df_15m.empty:
                return False, None
            df_15m = calculate_wt(df_15m)
            wt1_last, wt2_last = df_15m["wt1"].iloc[-1], df_15m["wt2"].iloc[-1]
            wt1_prev, wt2_prev = df_15m["wt1"].iloc[-2], df_15m["wt2"].iloc[-2]
            cross_up = wt1_prev < wt2_prev and wt1_last > wt2_last
            cross_down = wt1_prev > wt2_prev and wt1_last < wt2_last

            df_3m = await data_collector.get_ohlcv(symbol, "3m", limit=100)
            if df_3m is None or df_3m.empty:
                return False, None
            df_3m = calculate_wt(df_3m)
            zone = get_zone(df_3m["wt1"].iloc[-1])
            fvg, entry = detect_fvg(df_3m)

            if trend_dir == 1 and cross_up and zone == "OS" and fvg == "BULL":
                return True, {
                    "symbol": symbol,
                    "type": "LONG",
                    "trend": "UP",
                    "wt": f"WT1={wt1_last:.2f}, WT2={wt2_last:.2f}",
                    "zone": zone,
                    "fvg": fvg,
                    "entry_price": entry,
                    "timeframes": {"trend": "1h", "wt": "15m", "zone/fvg": "3m"}
                }
            if trend_dir == -1 and cross_down and zone == "OB" and fvg == "BEAR":
                return True, {
                    "symbol": symbol,
                    "type": "SHORT",
                    "trend": "DOWN",
                    "wt": f"WT1={wt1_last:.2f}, WT2={wt2_last:.2f}",
                    "zone": zone,
                    "fvg": fvg,
                    "entry_price": entry,
                    "timeframes": {"trend": "1h", "wt": "15m", "zone/fvg": "3m"}
                }
            return False, None
        except Exception:
            logger.exception(f"check_mtf_signal error for {symbol}")
            return False, None
