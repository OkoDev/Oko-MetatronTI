"""
ARCH-12.5: AutoCalibrator — rule-based автокалибровка MTF multipliers по реальным исходам.

Цикл Self-Improving Level 1:
  closed trades → сегментация → expectancy → корректировка multipliers → валидация → применение

Запускается еженедельно (воскресенье) в ml_loop, сразу после ML-переобучения.
Результаты сохраняются в calibration.json и подгружаются MTFContext при старте.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Defaults (hardcoded в MTFContext до калибровки) ──────────────────────
DEFAULT_PARAMS = {
    # direction_multiplier coefficients
    "aligned_boost": 0.5,       # aligned: 1.0 + bs * aligned_boost (max 1.5)
    "counter_penalty": 0.7,     # counter: max(counter_floor, 1.0 - bs * counter_penalty)
    "counter_floor": 0.3,       # минимальный множитель против bias

    # zone_multiplier coefficients
    "zone_range": 0.8,          # LONG: (1.0+zone_range/2) - zone_range*zone
    "zone_base_high": 1.4,      # макс множитель зоны (LONG@S5 или SHORT@R5)
    "zone_base_low": 0.6,       # мин множитель зоны (LONG@R5 или SHORT@S5)

    # combination weights
    "dir_weight": 0.7,
    "zone_weight": 0.3,
}

# Минимальное кол-во сделок в сегменте для доверия статистике
MIN_SEGMENT_TRADES = 15

# Пороги expectancy для корректировки
EXPECTANCY_WEAK_THRESHOLD = -0.3    # ослабить
EXPECTANCY_STRONG_THRESHOLD = 0.5   # усилить

# Лимиты корректировки за один цикл (защита от переобучения)
MAX_WEAKEN_STEP = 0.20   # максимум -20% за итерацию
MAX_BOOST_STEP = 0.10    # максимум +10% за итерацию (асимметрия: осторожнее усиливаем)

# Абсолютные границы параметров
PARAM_BOUNDS = {
    "aligned_boost": (0.1, 1.0),
    "counter_penalty": (0.3, 1.0),
    "counter_floor": (0.1, 0.5),
    "zone_range": (0.3, 1.2),
    "zone_base_high": (1.1, 1.8),
    "zone_base_low": (0.3, 0.8),
    "dir_weight": (0.4, 0.9),
    "zone_weight": (0.1, 0.6),
}


@dataclass
class SegmentStats:
    """Статистика одного сегмента сделок."""
    name: str
    total: int = 0
    wins: int = 0
    losses: int = 0
    r_sum: float = 0.0
    r_win_sum: float = 0.0
    r_loss_sum: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total if self.total > 0 else 0.0

    @property
    def avg_r(self) -> float:
        return self.r_sum / self.total if self.total > 0 else 0.0

    @property
    def avg_r_win(self) -> float:
        return self.r_win_sum / self.wins if self.wins > 0 else 0.0

    @property
    def avg_r_loss(self) -> float:
        return self.r_loss_sum / self.losses if self.losses > 0 else 0.0

    @property
    def expectancy(self) -> float:
        """E = WR × avg_R_win - (1-WR) × |avg_R_loss|"""
        if self.total == 0:
            return 0.0
        wr = self.win_rate
        return wr * self.avg_r_win - (1 - wr) * abs(self.avg_r_loss)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "total": self.total,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate * 100, 1),
            "avg_r": round(self.avg_r, 3),
            "expectancy": round(self.expectancy, 3),
        }


@dataclass
class Adjustment:
    """Одна предложенная корректировка параметра."""
    param: str
    old_value: float
    new_value: float
    reason: str
    segment: str
    expectancy: float
    n_trades: int

    def to_dict(self) -> dict:
        return {
            "param": self.param,
            "old": round(self.old_value, 4),
            "new": round(self.new_value, 4),
            "delta_pct": round((self.new_value - self.old_value) / self.old_value * 100, 1)
                if self.old_value != 0 else 0,
            "reason": self.reason,
            "segment": self.segment,
            "expectancy": round(self.expectancy, 3),
            "n_trades": self.n_trades,
        }


@dataclass
class CalibrationResult:
    """Результат одного цикла калибровки."""
    timestamp: str = ""
    segments_analyzed: int = 0
    total_trades: int = 0
    adjustments: List[Adjustment] = field(default_factory=list)
    params_before: Dict[str, float] = field(default_factory=dict)
    params_after: Dict[str, float] = field(default_factory=dict)
    segments: List[Dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "segments_analyzed": self.segments_analyzed,
            "total_trades": self.total_trades,
            "adjustments": [a.to_dict() for a in self.adjustments],
            "params_before": self.params_before,
            "params_after": self.params_after,
            "segments": self.segments,
        }

    def summary_text(self) -> str:
        """Краткий текст для TG-отчёта."""
        lines = [
            f"🔧 <b>Автокалибровка MTF multipliers</b>",
            f"Сделок: {self.total_trades} | Сегментов: {self.segments_analyzed}",
        ]
        if not self.adjustments:
            lines.append("✅ Корректировки не требуются")
        else:
            lines.append(f"📊 <b>{len(self.adjustments)} корректировок:</b>")
            for adj in self.adjustments:
                delta = adj.new_value - adj.old_value
                arrow = "↑" if delta > 0 else "↓"
                lines.append(
                    f"  {arrow} <code>{adj.param}</code>: "
                    f"{adj.old_value:.3f}→{adj.new_value:.3f} "
                    f"({adj.segment}, E={adj.expectancy:+.3f}, n={adj.n_trades})"
                )

        # Топ-3 худших/лучших сегмента
        sorted_segs = sorted(self.segments, key=lambda s: s.get("expectancy", 0))
        if sorted_segs:
            worst = [s for s in sorted_segs if s["expectancy"] < 0][:3]
            best = [s for s in reversed(sorted_segs) if s["expectancy"] > 0][:3]
            if worst:
                lines.append("\n🔴 <b>Худшие сегменты:</b>")
                for s in worst:
                    lines.append(
                        f"  {s['name']}: WR={s['win_rate']:.0f}% E={s['expectancy']:+.3f} n={s['total']}"
                    )
            if best:
                lines.append("\n🟢 <b>Лучшие сегменты:</b>")
                for s in best:
                    lines.append(
                        f"  {s['name']}: WR={s['win_rate']:.0f}% E={s['expectancy']:+.3f} n={s['total']}"
                    )

        return "\n".join(lines)


class AutoCalibrator:
    """
    Rule-based автокалибровка MTF multipliers на основе реальных торговых исходов.

    Принцип:
    - Сегментирует закрытые сделки по (direction × mtf_bias), (direction × zone_bucket), (direction × regime)
    - Для каждого сегмента считает WR, avg_R, expectancy
    - Если expectancy << 0 → ослабляет соответствующий множитель
    - Если expectancy >> 0 → усиливает (осторожнее)
    - Сохраняет откалиброванные параметры в calibration.json
    """

    def __init__(self, db_path: str, calibration_path: Optional[str] = None):
        self.db_path = db_path
        self.calibration_path = calibration_path or os.path.join(
            os.path.dirname(db_path), "calibration.json"
        )
        self.params: Dict[str, float] = dict(DEFAULT_PARAMS)
        self._load_calibration()

    # ── Persistence ──────────────────────────────────────────────────

    def _load_calibration(self):
        """Загружает откалиброванные параметры из JSON."""
        path = Path(self.calibration_path)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                saved_params = data.get("params", {})
                for key in DEFAULT_PARAMS:
                    if key in saved_params:
                        self.params[key] = float(saved_params[key])
                logger.info(
                    "AutoCalibrator: загружены параметры из %s (updated: %s)",
                    self.calibration_path, data.get("updated_at", "?"),
                )
            except Exception as e:
                logger.warning("AutoCalibrator: ошибка загрузки calibration.json: %s", e)

    def _save_calibration(self, result: CalibrationResult):
        """Сохраняет откалиброванные параметры в JSON."""
        data = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "params": {k: round(v, 6) for k, v in self.params.items()},
            "last_calibration": result.to_dict(),
            "history": [],
        }
        # Дописываем историю (последние 10 калибровок)
        path = Path(self.calibration_path)
        if path.exists():
            try:
                old = json.loads(path.read_text())
                history = old.get("history", [])
                history.append({
                    "timestamp": result.timestamp,
                    "adjustments": len(result.adjustments),
                    "total_trades": result.total_trades,
                    "params": result.params_after,
                })
                data["history"] = history[-10:]  # последние 10
            except Exception:
                pass

        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info("AutoCalibrator: параметры сохранены в %s", self.calibration_path)

    # ── Main entry point ─────────────────────────────────────────────

    def calibrate(self, lookback_days: int = 14, min_trades: int = 30) -> CalibrationResult:
        """
        Основной метод: анализ сделок → сегментация → корректировка → сохранение.

        Args:
            lookback_days: сколько дней назад смотреть (default 14)
            min_trades: минимум закрытых сделок для калибровки

        Returns:
            CalibrationResult с деталями
        """
        result = CalibrationResult(
            timestamp=datetime.now(timezone.utc).isoformat(),
            params_before=dict(self.params),
        )

        # 1. Загружаем закрытые сделки
        trades = self._load_closed_trades(lookback_days)
        result.total_trades = len(trades)

        if len(trades) < min_trades:
            logger.info(
                "AutoCalibrator: %d сделок < %d минимум — калибровка пропущена",
                len(trades), min_trades,
            )
            result.params_after = dict(self.params)
            return result

        # 2. Сегментация
        segments = self._build_segments(trades)
        result.segments_analyzed = len(segments)
        result.segments = [s.to_dict() for s in segments.values()]

        # 3. Генерация корректировок
        adjustments = self._propose_adjustments(segments)
        result.adjustments = adjustments

        # 4. Применение
        for adj in adjustments:
            self.params[adj.param] = adj.new_value

        result.params_after = dict(self.params)

        # 5. Сохранение
        if adjustments:
            self._save_calibration(result)
            logger.info(
                "AutoCalibrator: %d корректировок применено из %d сегментов (%d сделок)",
                len(adjustments), len(segments), len(trades),
            )
        else:
            logger.info(
                "AutoCalibrator: корректировки не требуются (%d сегментов, %d сделок)",
                len(segments), len(trades),
            )

        return result

    # ── Data loading ─────────────────────────────────────────────────

    def _load_closed_trades(self, lookback_days: int) -> List[Dict[str, Any]]:
        """Загружает закрытые сделки с MTF фичами за последние N дней."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                # DEV-190: добавлен tsl_activated для is_win helper
                rows = conn.execute("""
                    SELECT symbol, direction, signal_type, status, tsl_activated,
                           R_multiple, strength, confidence, regime,
                           features_json, created_at, closed_at
                    FROM simulated_trades
                    WHERE status IN ('TP', 'SL', 'TSL')
                      AND closed_at > ?
                      AND features_json IS NOT NULL
                      AND features_json LIKE '%mtf_%'
                    ORDER BY closed_at DESC
                """, (cutoff,)).fetchall()

            trades = []
            for row in rows:
                d = dict(row)
                try:
                    d["features"] = json.loads(d["features_json"])
                except (json.JSONDecodeError, TypeError):
                    continue
                trades.append(d)

            logger.info("AutoCalibrator: загружено %d сделок за %d дней", len(trades), lookback_days)
            return trades
        except Exception as e:
            logger.error("AutoCalibrator: ошибка загрузки сделок: %s", e)
            return []

    # ── Segmentation ─────────────────────────────────────────────────

    def _build_segments(self, trades: List[Dict]) -> Dict[str, SegmentStats]:
        """Сегментирует сделки по ключевым осям."""
        segments: Dict[str, SegmentStats] = {}

        for t in trades:
            feat = t.get("features", {})
            direction = t.get("direction", "")
            status = t.get("status", "")
            r_mult = t.get("R_multiple") or 0.0
            # DEV-190: учёт скрытых TSL exits (status='SL'+tsl_act+R>0.1)
            from core.trading.effective_status import is_win as _is_win_fn
            is_win = _is_win_fn(status, r_mult, t.get("tsl_activated"))

            mtf_bias = feat.get("mtf_direction_bias", "NEUTRAL")
            price_zone = feat.get("mtf_price_zone")
            regime = feat.get("mtf_regime") or t.get("regime") or "UNKNOWN"

            # ── Сегмент 1: direction × mtf_bias ──
            seg_name = f"dir={direction}_bias={mtf_bias}"
            seg = segments.setdefault(seg_name, SegmentStats(name=seg_name))
            self._add_trade_to_segment(seg, is_win, r_mult)

            # ── Сегмент 2: direction × zone_bucket ──
            if price_zone is not None:
                if price_zone < 0.3:
                    zone_bucket = "SUPPORT"      # S5-S2
                elif price_zone > 0.7:
                    zone_bucket = "RESISTANCE"   # R2-R5
                else:
                    zone_bucket = "MIDDLE"       # S1-PP-R1
                seg_name = f"dir={direction}_zone={zone_bucket}"
                seg = segments.setdefault(seg_name, SegmentStats(name=seg_name))
                self._add_trade_to_segment(seg, is_win, r_mult)

            # ── Сегмент 3: direction × regime ──
            seg_name = f"dir={direction}_regime={regime}"
            seg = segments.setdefault(seg_name, SegmentStats(name=seg_name))
            self._add_trade_to_segment(seg, is_win, r_mult)

            # ── Сегмент 4: комбинированный (direction × bias × zone) ──
            if price_zone is not None:
                aligned = (
                    (direction == "LONG" and mtf_bias == "LONG") or
                    (direction == "SHORT" and mtf_bias == "SHORT")
                )
                alignment = "aligned" if aligned else ("counter" if mtf_bias != "NEUTRAL" else "neutral")
                seg_name = f"align={alignment}_zone={zone_bucket}"
                seg = segments.setdefault(seg_name, SegmentStats(name=seg_name))
                self._add_trade_to_segment(seg, is_win, r_mult)

        return segments

    @staticmethod
    def _add_trade_to_segment(seg: SegmentStats, is_win: bool, r_mult: float):
        seg.total += 1
        seg.r_sum += r_mult
        if is_win:
            seg.wins += 1
            seg.r_win_sum += r_mult
        else:
            seg.losses += 1
            seg.r_loss_sum += r_mult

    # ── Adjustment proposals ─────────────────────────────────────────

    def _propose_adjustments(self, segments: Dict[str, SegmentStats]) -> List[Adjustment]:
        """Генерирует корректировки на основе expectancy по сегментам."""
        adjustments: List[Adjustment] = []
        proposed: Dict[str, Tuple[float, str, float, int]] = {}  # param → (delta, reason, E, n)

        for name, seg in segments.items():
            if seg.total < MIN_SEGMENT_TRADES:
                continue

            exp = seg.expectancy

            # ── direction × bias сегменты → калибровка aligned_boost / counter_penalty
            if name.startswith("dir=") and "_bias=" in name and "_zone=" not in name and "_regime=" not in name:
                direction = name.split("_bias=")[0].replace("dir=", "")
                bias = name.split("_bias=")[1]

                aligned = (
                    (direction == "LONG" and bias == "LONG") or
                    (direction == "SHORT" and bias == "SHORT")
                )

                if aligned and exp < EXPECTANCY_WEAK_THRESHOLD:
                    # Aligned сигналы убыточны → уменьшить aligned_boost
                    self._propose_param_change(
                        proposed, "aligned_boost", -MAX_WEAKEN_STEP,
                        f"{name}: aligned убыточен", exp, seg.total,
                    )
                elif aligned and exp > EXPECTANCY_STRONG_THRESHOLD:
                    # Aligned прибылен → усилить
                    self._propose_param_change(
                        proposed, "aligned_boost", +MAX_BOOST_STEP,
                        f"{name}: aligned прибылен", exp, seg.total,
                    )
                elif not aligned and bias != "NEUTRAL":
                    if exp < EXPECTANCY_WEAK_THRESHOLD:
                        # Counter убыточен → усилить counter_penalty (больше штраф)
                        self._propose_param_change(
                            proposed, "counter_penalty", +MAX_WEAKEN_STEP,
                            f"{name}: counter убыточен", exp, seg.total,
                        )
                    elif exp > EXPECTANCY_STRONG_THRESHOLD:
                        # Counter прибылен → ослабить penalty
                        self._propose_param_change(
                            proposed, "counter_penalty", -MAX_BOOST_STEP,
                            f"{name}: counter прибылен", exp, seg.total,
                        )

            # ── direction × zone сегменты → калибровка zone_range
            if "_zone=" in name and "_bias=" not in name and "_regime=" not in name:
                direction = name.split("_zone=")[0].replace("dir=", "")
                zone_bucket = name.split("_zone=")[1]

                # LONG@SUPPORT или SHORT@RESISTANCE = "хорошая зона"
                good_zone = (
                    (direction == "LONG" and zone_bucket == "SUPPORT") or
                    (direction == "SHORT" and zone_bucket == "RESISTANCE")
                )
                # LONG@RESISTANCE или SHORT@SUPPORT = "плохая зона"
                bad_zone = (
                    (direction == "LONG" and zone_bucket == "RESISTANCE") or
                    (direction == "SHORT" and zone_bucket == "SUPPORT")
                )

                if good_zone and exp > EXPECTANCY_STRONG_THRESHOLD:
                    # Зона работает хорошо → усилить zone_range
                    self._propose_param_change(
                        proposed, "zone_range", +MAX_BOOST_STEP,
                        f"{name}: хорошая зона прибыльна", exp, seg.total,
                    )
                elif bad_zone and exp < EXPECTANCY_WEAK_THRESHOLD:
                    # Плохая зона убыточна → усилить zone_range (сильнее штрафовать)
                    self._propose_param_change(
                        proposed, "zone_range", +MAX_WEAKEN_STEP,
                        f"{name}: плохая зона убыточна", exp, seg.total,
                    )
                elif bad_zone and exp > EXPECTANCY_STRONG_THRESHOLD:
                    # "Плохая" зона на самом деле прибыльна → ослабить zone_range
                    self._propose_param_change(
                        proposed, "zone_range", -MAX_BOOST_STEP,
                        f"{name}: 'плохая' зона прибыльна, зона переоценена", exp, seg.total,
                    )

            # ── align × zone комбинированные → dir_weight / zone_weight
            if name.startswith("align="):
                alignment = name.split("_zone=")[0].replace("align=", "")
                zone_bucket = name.split("_zone=")[1]

                if alignment == "aligned" and exp > EXPECTANCY_STRONG_THRESHOLD:
                    # Alignment важнее → увеличить dir_weight
                    self._propose_param_change(
                        proposed, "dir_weight", +MAX_BOOST_STEP * 0.5,
                        f"{name}: alignment работает", exp, seg.total,
                    )
                elif alignment == "counter" and zone_bucket in ("SUPPORT", "RESISTANCE"):
                    if exp > EXPECTANCY_STRONG_THRESHOLD:
                        # Counter в хорошей зоне прибылен → zone важнее
                        self._propose_param_change(
                            proposed, "zone_weight", +MAX_BOOST_STEP * 0.5,
                            f"{name}: зона перевешивает alignment", exp, seg.total,
                        )

        # Конвертируем proposed → adjustments
        for param, (delta, reason, exp, n) in proposed.items():
            old_val = self.params[param]
            lo, hi = PARAM_BOUNDS.get(param, (0.0, 10.0))
            new_val = max(lo, min(hi, old_val + delta))

            # Пересчёт dir_weight/zone_weight — они должны дать в сумме 1.0
            if param == "dir_weight":
                new_val = max(lo, min(hi, new_val))
                # zone_weight = 1.0 - dir_weight автоматически
            elif param == "zone_weight":
                new_val = max(lo, min(hi, new_val))

            if abs(new_val - old_val) > 0.001:  # игнорируем микро-изменения
                adjustments.append(Adjustment(
                    param=param,
                    old_value=old_val,
                    new_value=round(new_val, 6),
                    reason=reason,
                    segment=reason.split(":")[0] if ":" in reason else "",
                    expectancy=exp,
                    n_trades=n,
                ))

        # Синхронизация dir_weight + zone_weight = 1.0
        if any(a.param in ("dir_weight", "zone_weight") for a in adjustments):
            for adj in adjustments:
                if adj.param == "dir_weight":
                    # Автокоррекция zone_weight
                    new_zw = round(1.0 - adj.new_value, 6)
                    if abs(new_zw - self.params["zone_weight"]) > 0.001:
                        adjustments.append(Adjustment(
                            param="zone_weight",
                            old_value=self.params["zone_weight"],
                            new_value=new_zw,
                            reason="синхронизация с dir_weight",
                            segment="",
                            expectancy=0,
                            n_trades=0,
                        ))
                    break

        return adjustments

    def _propose_param_change(
        self,
        proposed: Dict[str, Tuple[float, str, float, int]],
        param: str,
        delta: float,
        reason: str,
        expectancy: float,
        n_trades: int,
    ):
        """Добавляет/обновляет предложение по изменению параметра.
        Если несколько сегментов влияют на один параметр — берём самый значимый."""
        existing = proposed.get(param)
        if existing is None or abs(expectancy) > abs(existing[2]):
            proposed[param] = (delta, reason, expectancy, n_trades)

    # ── Public API ───────────────────────────────────────────────────

    def get_params(self) -> Dict[str, float]:
        """Возвращает текущие откалиброванные параметры."""
        return dict(self.params)

    def get_direction_multiplier_params(self) -> Tuple[float, float, float]:
        """Возвращает (aligned_boost, counter_penalty, counter_floor)."""
        return (
            self.params["aligned_boost"],
            self.params["counter_penalty"],
            self.params["counter_floor"],
        )

    def get_zone_multiplier_params(self) -> Tuple[float, float, float]:
        """Возвращает (zone_range, zone_base_high, zone_base_low)."""
        return (
            self.params["zone_range"],
            self.params["zone_base_high"],
            self.params["zone_base_low"],
        )

    def get_combination_weights(self) -> Tuple[float, float]:
        """Возвращает (dir_weight, zone_weight)."""
        return (self.params["dir_weight"], self.params["zone_weight"])
