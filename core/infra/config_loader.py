"""
Модуль для загрузки конфигурации из YAML файла
"""
import os
import yaml
import logging
from typing import Dict, Any
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

logger = logging.getLogger(__name__)

class ConfigLoader:
    """Загрузчик конфигурации"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self.load_config()
    
    def load_config(self) -> Dict[str, Any]:
        """Загружает конфигурацию из YAML файла"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as file:
                config = yaml.safe_load(file)
            
            # Заменяем переменные окружения
            config = self._replace_env_vars(config)

            # CONFIG-SLTP-BUG (14.06): merge sl_tp_engine → trading namespace.
            # Историч. блок exit/risk-настроек (use_tsl, tsl_activation_r_per_strategy,
            # breakeven, cascade, min_sl_dist_pct, max_positions...) в секции sl_tp_engine,
            # но часть кода читает их как trading.X → None → defaults. Merge (setdefault,
            # не перезатирая trading) даёт ОБОИМ путям работать (дублей trading∩sl_tp_engine нет).
            # sl_tp_engine.X остаётся для tp_selector/tsl_hybrid (их читают оттуда).
            if (isinstance(config, dict) and isinstance(config.get('trading'), dict)
                    and isinstance(config.get('sl_tp_engine'), dict)):
                _merged = 0
                for _k, _v in config['sl_tp_engine'].items():
                    if _k not in config['trading']:
                        config['trading'][_k] = _v
                        _merged += 1
                logger.info("[CONFIG] sl_tp_engine → trading merge: %d ключей (CONFIG-SLTP-BUG fix)", _merged)

            from core.infra.config_validator import validate_and_log
            validate_and_log(config)
            logger.info("Конфигурация загружена успешно")
            return config
        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации: {e}")
            return self._get_default_config()
    
    def _replace_env_vars(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Заменяет переменные окружения в конфигурации"""
        def replace_recursive(obj):
            if isinstance(obj, dict):
                return {k: replace_recursive(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [replace_recursive(item) for item in obj]
            elif isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
                env_var = obj[2:-1]
                return os.getenv(env_var, obj)
            else:
                return obj
        
        return replace_recursive(config)
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Возвращает конфигурацию по умолчанию"""
        return {
            "telegram": {
                "token": os.getenv("TELEGRAM_TOKEN", ""),
                "admin_id": os.getenv("ADMIN_ID", "")
            },
            "exchanges": {
                "default": "bingx",
                "supported": ["binance", "bybit", "bingx"]
            },
            "analysis": {
                "volume_multiplier": 5.0,
                "price_threshold": 7.0,
                "history_size": 200,
                "check_interval": 60,
                "indicators": {
                    "wavetrend": {
                        "n1": 10,              # ESA period (9-12)
                        "n2": 21,              # WT signal period (20-25)
                        "ob_threshold": 60,    # Overbought zone
                        "os_threshold": -60    # Oversold zone
                    },
                    "trend": {
                        "atr_period": 43,      # ATR period for TSL-based trend (特殊パラメータ)
                        "factor": 1.0          # ATR multiplier (0.8-1.2)
                    },
                    "market_regime": {
                        "adx_period": 14,      # ADX period (standard TradingView)
                        "atr_period": 14,      # ATR period (standard TradingView)
                        "ema_period": 20       # EMA period for regime
                    },
                    "divergence": {
                        "pivot_period": 5,
                        "lookback": 50,
                        "max_bars": 100,
                        "min_bars_between": 5
                    }
                },
                "signals": {
                    "min_signals": 2,
                    "single_signal_min_strength": 70,
                    "premium_pairs": ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "DOT", "MATIC", "AVAX"]
                },
                "divergence": {
                    "pivot_proximity_pct": 4.0  # допустимое расстояние до пивота для фильтра дивергенций
                }
            },
            "subscriptions": {
                "free": {"daily_limit": 5, "signals": ["anomaly"], "price": 0},
                "basic": {"daily_limit": 10, "signals": ["anomaly", "wt_signal"], "price": 9.99},
                "premium": {"daily_limit": 50, "signals": ["anomaly", "wt_signal", "trend_signal"], "price": 29.99},
                "pro": {"daily_limit": 999999, "signals": ["all"], "price": 99.99}
            },
            "logging": {
                "level": "INFO",
                "file": "crypto_bot.log",
                "max_size": "10MB",
                "backup_count": 5
            },
            "detectors": {
                "anomaly": {
                    "min_bars": 20,
                    "volume_ma_period": 20,
                    "volume_ratio_threshold": 3.0,
                    "strength_trend_multiplier": 12,
                    "strength_counter_multiplier": 8,
                }
            },
            "monitoring": {
                "check_intervals": {
                    "divergences_every_n_cycles": 3,
                    "background_every_n_cycles": 5,
                    "cascade_div_every_n_cycles": 60,
                }
            },
            "performance": {
                "scan_semaphore_size": 5,
                "analyze_semaphore_size": 2,
                "prefetch_pivots_semaphore_size": 2,
                "background_check_semaphore_size": 5,
                "cascade_div_semaphore_size": 3,
                "api_semaphore_size": 20,
                "api_rps": 15.0,
                "ohlcv_scan_limit": 160,
                "ohlcv_slow_threshold_sec": 5.0,
                "divergence_slow_threshold_sec": 3.0,
                "pair_slow_threshold_sec": 10.0,
                "scan_cycle_warning_threshold_sec": 55.0,
            },
            "signal_quality": {
                "sl_cooldown_hours": 4,
                "dedup_minutes": 30,
                "min_volume_usd": 1000000,
                "min_strength": 50,
                "min_strength_register": 20,
                "counter_trend_strength_threshold": 70,
            },
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """Получает значение по ключу (поддержка вложенных ключей)"""
        keys = key.split('.')
        value = self.config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def perf(self, key: str, default: Any = None) -> Any:
        """PROXY-NODE профиль: если proxy_pool.enabled → берёт proxy_pool.overrides.<key>
        (прокси-оптимизированные rps/semaphore), иначе performance.<key> (базовые).
        Один флаг proxy_pool.enabled переключает весь профиль — не править параметры руками."""
        if self.get("proxy_pool.enabled", False):
            ov = self.get(f"proxy_pool.overrides.{key}")
            if ov is not None:
                return ov
        return self.get(f"performance.{key}", default)

    def get_telegram_token(self) -> str:
        """Получает токен Telegram бота"""
        return self.get("telegram.token", "")
    
    def get_admin_id(self) -> str:
        """Получает ID администратора"""
        return self.get("telegram.admin_id", "")
    
    def get_exchange_config(self) -> Dict[str, Any]:
        """Получает конфигурацию бирж"""
        return self.get("exchanges", {})
    
    def get_analysis_config(self) -> Dict[str, Any]:
        """Получает конфигурацию анализа"""
        return self.get("analysis", {})
    
    def get_subscription_config(self) -> Dict[str, Any]:
        """Получает конфигурацию подписок"""
        return self.get("subscriptions", {})
    
    def get_logging_config(self) -> Dict[str, Any]:
        """Получает конфигурацию логирования"""
        return self.get("logging", {})
    
    def get_all(self) -> Dict[str, Any]:
        """Получает всю конфигурацию"""
        return self.config

    def set(self, key: str, value: Any) -> None:
        """Устанавливает значение по dot-separated ключу (in-memory)."""
        keys = key.split(".")
        d = self.config
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value

    def save(self) -> bool:
        """Сохраняет текущий in-memory конфиг в config.yaml и reload."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            # Merge in-memory changes into raw YAML
            self._deep_merge(raw, self.config)
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            self.reload()
            return True
        except Exception:
            logger.exception("config.save() failed")
            return False

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Рекурсивный merge override в base."""
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                ConfigLoader._deep_merge(base[k], v)
            else:
                base[k] = v
        return base

    def reload(self) -> None:
        """Перечитывает config.yaml с диска без перезапуска бота."""
        self.config = self.load_config()
        logger.info("Конфигурация перезагружена с диска")

    def save_indicators(
        self,
        wt_n1: int,
        wt_n2: int,
        wt_ob: float,
        wt_os: float,
        trend_atr_period: int,
        trend_factor: float,
    ) -> bool:
        """
        Обновляет секцию analysis.indicators в config.yaml и вызывает reload().
        """
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            raw.setdefault("analysis", {}).setdefault("indicators", {})
            raw["analysis"]["indicators"]["wavetrend"] = {
                "n1": int(wt_n1),
                "n2": int(wt_n2),
                "ob_threshold": float(wt_ob),
                "os_threshold": float(wt_os),
            }
            raw["analysis"]["indicators"]["trend"] = {
                "atr_period": int(trend_atr_period),
                "factor": round(float(trend_factor), 2),
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            self.reload()
            logger.info(
                "Параметры индикаторов сохранены: wt=(%d,%d,%.0f,%.0f) trend=(%d,%.1f)",
                wt_n1, wt_n2, wt_ob, wt_os, trend_atr_period, trend_factor,
            )
            return True
        except Exception as e:
            logger.error("Ошибка сохранения параметров индикаторов: %s", e)
            return False

    def save_analysis(
        self,
        volume_multiplier: float,
        price_threshold: float,
        check_interval: int,
        history_size: int,
    ) -> bool:
        """
        Обновляет секцию analysis в config.yaml и вызывает reload().
        Читает сырой YAML (без подстановки env-vars) чтобы не затирать ${...} плейсхолдеры.
        """
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            raw.setdefault("analysis", {})
            raw["analysis"]["volume_multiplier"] = round(float(volume_multiplier), 2)
            raw["analysis"]["price_threshold"] = round(float(price_threshold), 2)
            raw["analysis"]["check_interval"] = int(check_interval)
            raw["analysis"]["history_size"] = int(history_size)
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            self.reload()
            logger.info(
                "Параметры анализа сохранены: vol_mult=%.1f price_thr=%.1f interval=%d history=%d",
                volume_multiplier, price_threshold, check_interval, history_size,
            )
            return True
        except Exception as e:
            logger.error("Ошибка сохранения конфигурации: %s", e)
            return False

    def save_trading(
        self,
        use_tsl: bool,
        tsl_activation_r: float,
        tsl_buffer_pct: float,
    ) -> bool:
        """Обновляет секцию trading в config.yaml и вызывает reload()."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            raw.setdefault("trading", {})
            raw["trading"]["use_tsl"] = bool(use_tsl)
            raw["trading"]["tsl_activation_r"] = round(float(tsl_activation_r), 2)
            raw["trading"]["tsl_buffer_pct"] = round(float(tsl_buffer_pct), 3)
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            self.reload()
            logger.info(
                "TSL настройки сохранены: use_tsl=%s activation_r=%.1f buffer=%.3f",
                use_tsl, tsl_activation_r, tsl_buffer_pct,
            )
            return True
        except Exception as e:
            logger.error("Ошибка сохранения trading конфига: %s", e)
            return False

    def save_signal_quality(
        self,
        sl_cooldown_hours: int,
        dedup_minutes: int,
        min_volume_usd: int,
        min_strength: int,
        min_strength_register: int,
        counter_trend_strength_threshold: int = 70,
    ) -> bool:
        """Обновляет секцию signal_quality в config.yaml и вызывает reload()."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            raw.setdefault("signal_quality", {})
            raw["signal_quality"]["sl_cooldown_hours"] = int(sl_cooldown_hours)
            raw["signal_quality"]["dedup_minutes"] = int(dedup_minutes)
            raw["signal_quality"]["min_volume_usd"] = int(min_volume_usd)
            raw["signal_quality"]["min_strength"] = int(min_strength)
            raw["signal_quality"]["min_strength_register"] = int(min_strength_register)
            raw["signal_quality"]["counter_trend_strength_threshold"] = int(counter_trend_strength_threshold)
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            self.reload()
            logger.info(
                "Качество сигналов сохранено: cooldown=%dh dedup=%dm vol=%d strength=%d/%d ct_thr=%d",
                sl_cooldown_hours, dedup_minutes, min_volume_usd, min_strength,
                min_strength_register, counter_trend_strength_threshold,
            )
            return True
        except Exception as e:
            logger.error("Ошибка сохранения signal_quality конфига: %s", e)
            return False

    def save_detectors(
        self,
        volume_ratio_threshold: float,
        volume_ma_period: int,
        min_bars: int,
        strength_trend_multiplier: int,
        strength_counter_multiplier: int,
    ) -> bool:
        """Обновляет секцию detectors.anomaly в config.yaml и вызывает reload()."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            raw.setdefault("detectors", {}).setdefault("anomaly", {})
            raw["detectors"]["anomaly"]["min_bars"] = int(min_bars)
            raw["detectors"]["anomaly"]["volume_ma_period"] = int(volume_ma_period)
            raw["detectors"]["anomaly"]["volume_ratio_threshold"] = round(float(volume_ratio_threshold), 2)
            raw["detectors"]["anomaly"]["strength_trend_multiplier"] = int(strength_trend_multiplier)
            raw["detectors"]["anomaly"]["strength_counter_multiplier"] = int(strength_counter_multiplier)
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            self.reload()
            logger.info(
                "Детекторы сохранены: ratio_thr=%.1f ma=%d min_bars=%d str=%d/%d",
                volume_ratio_threshold, volume_ma_period, min_bars,
                strength_trend_multiplier, strength_counter_multiplier,
            )
            return True
        except Exception as e:
            logger.error("Ошибка сохранения detectors конфига: %s", e)
            return False

    def save_monitoring(
        self,
        divergences_every_n_cycles: int,
        background_every_n_cycles: int,
        cascade_div_every_n_cycles: int,
    ) -> bool:
        """Обновляет секцию monitoring.check_intervals в config.yaml."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            raw.setdefault("monitoring", {}).setdefault("check_intervals", {})
            raw["monitoring"]["check_intervals"]["divergences_every_n_cycles"] = int(divergences_every_n_cycles)
            raw["monitoring"]["check_intervals"]["background_every_n_cycles"] = int(background_every_n_cycles)
            raw["monitoring"]["check_intervals"]["cascade_div_every_n_cycles"] = int(cascade_div_every_n_cycles)
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            self.reload()
            logger.info(
                "Мониторинг сохранён: div_every=%d bg_every=%d cascade_every=%d",
                divergences_every_n_cycles, background_every_n_cycles, cascade_div_every_n_cycles,
            )
            return True
        except Exception as e:
            logger.error("Ошибка сохранения monitoring конфига: %s", e)
            return False


    def save_risk(
        self,
        deposit_usdt: float,
        risk_pct: float,
        leverage: int,
    ) -> bool:
        """Обновляет параметры риск-менеджмента в секции trading config.yaml."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            raw.setdefault("trading", {})
            raw["trading"]["deposit_usdt"] = round(float(deposit_usdt), 2)
            raw["trading"]["risk_pct"]     = round(float(risk_pct), 2)
            raw["trading"]["leverage"]     = int(leverage)
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            self.reload()
            logger.info(
                "Риск-менеджмент сохранён: deposit=%.2f risk_pct=%.2f leverage=%d",
                deposit_usdt, risk_pct, leverage,
            )
            return True
        except Exception as e:
            logger.error("Ошибка сохранения риск конфига: %s", e)
            return False


# Глобальный экземпляр конфигурации
config = ConfigLoader()
