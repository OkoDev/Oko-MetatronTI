"""
MTF SMC Specialist — DEV-139 / ARCH-68 Фаза 2.

RandomForest на SMC-снимках 4 таймфреймов.
Вектор: 4 TF × (9 булевых + 18 непрерывных) = 108 полей, из которых fit отбирает
K сильнейших по объёму выборки (~25 наблюдений на признак, ARCH-137.6).
Предсказывает вероятность TP и возвращает SMCVerdict.

Shadow mode: результат пишется в recommendation.metadata["smc_verdict"].
Не влияет на strength/action пока нет 200+ сделок с smc_snap.

Источник данных: features_json["smc_snap"] — кладётся в recommendation.metadata
внутри analyze_symbol (trading_intelligence.py:1115), оттуда register_trade_async
переносит в features.

🔴 02.09: замер покрытия — snap есть лишь у 10% сделок. Метаданные наполняет
ТОЛЬКО analyze_symbol; стратегии, идущие через trade_router со своим
recommendation (atr_change, ote_nested, wl_breach, impulse_fib, radar...),
приносят metadata без snap → 0% покрытия. Вместе со snap теряются wt_snap и
narrative — падают синхронно, корень один. Сентябрь: 119 сделок, покрытие 0%.
"""
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MIN_TRADES = 50

# ARCH-137.6: сколько наблюдений должно приходиться на ОДИН признак.
# Вектор вырос с 36 до 108 полей (добавлены непрерывные), сделок со snap ~300.
# Замер 02.09, nested CV с отбором внутри фолда и перестановочным контролем:
#   топ-8  AUC 0.595 ± 0.032     топ-14 AUC 0.575
#   топ-10 AUC 0.587             топ-27 AUC 0.476  ← хуже монетки
#   контроль на перемешанных метках: 0.510
# 300/8 ≈ 37; берём 25 с запасом — кривая вокруг оптимума пологая.
# Модель растит себе вектор сама, по мере накопления сделок.
_SAMPLES_PER_FEATURE = 25
_MIN_FEATURES = 4

# ═══ ВЕРСИЯ СХЕМЫ SNAP (ARCH-137.6, 02.09.2026) ═══════════════════════════
# Причина: замер показал, что модель училась на СМЕСИ НЕСОВМЕСТИМЫХ данных.
# Доля True поля `fvg_open` на 1h по месяцам: апрель 2% → май 99%. Это не рынок,
# это починка детекторов (см. комментарии в _build_smc_snap_from_df про
# AttributeError и TypeError — до починки поля были всегда False).
# AUC по месяцам: 04 — 0.436, 05 — 0.461, 06 — 0.422, 07 — 0.486, 08 — 0.551,
# а ВСЁ ВМЕСТЕ — 0.379, то есть ХУЖЕ ЛЮБОГО отдельного месяца. Смесь эпох
# создаёт ложные закономерности. Отсюда и «AUC 0.180», а вовсе не из вывода
# «SMC не работает».
# Теперь каждый snap несёт версию схемы, а fit учится только на ОДНОЙ версии.
# 🔴 Поднимать при ЛЮБОМ изменении смысла полей: смена детектора, порога,
# добавление/удаление признака. Иначе история снова отравит модель.
#   v1 — до 02.09.2026 (не проставлялась, определяется по отсутствию поля)
#   v2 — 02.09.2026: SMC сведён на эталон (ARCH-137.5) + непрерывные признаки
#   v3 — 19.09.2026: «все на канон!» — ote_zone считается по канону core.smc.fibonacci (0.5–0.79),
#        а не по ICT 0.705–0.786 (признак был истинен 8% времени; смысл поля сменился → новая версия)
SNAP_SCHEMA_VERSION = 3

# 4 TF по спеке ARCH-68
_TFS = ["1d", "4h", "1h", "15m"]
_N_FEATURES = len(_TFS) * (9 + 18)  # 9 булевых (совместимость) + 18 непрерывных

_MODEL_FILE = "smc_specialist_model.pkl"

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import cross_val_score
    _SKLEARN_OK = True
except ImportError:
    _SKLEARN_OK = False
    logger.warning("MTFSMCSpecialist: sklearn не установлен — predict вернёт None")


@dataclass
class SMCVerdict:
    label: str        # "STRONG_BULL_ZONE" | "WEAK_ZONE" | "STRONG_BEAR_ZONE" | "NEUTRAL"
    confidence: float  # 0.0–1.0


# ARCH-137.6: непрерывные признаки — расстояния в ATR, размеры, возраст в барах.
# Порядок фиксирован: он задаёт позиции в векторе, менять только вместе с моделью.
_CONT_KEYS = (
    "ob_bull_dist_atr", "ob_bull_age", "ob_bear_dist_atr",
    "fvg_dist_atr", "fvg_size_atr", "fvg_age", "fvg_fill_pct",
    "brk_age", "brk_dist_atr", "brk_strength", "brk_internal",
    "fib_pos", "ote_dist_atr", "fib_dir_long", "eqh_dist_atr", "eql_dist_atr",
    "liq_buy_dist_atr", "liq_sell_dist_atr",
)
# «признака нет» ≠ «ноль»: ноль означает «зона ровно на цене».
_MISS = -99.0


def _build_smc_features(smc_snap: Dict[str, Any]) -> Optional[List[float]]:
    """
    Строит вектор 4 TF × 27 = 108 признаков.

    Per TF — 9 БУЛЕВЫХ (историческая часть, сделки в БД собраны с ними):
      ob_bull          (bool 0/1) — бычий OB активен
      ob_distance_pct  (float)    — % до ближайшего OB
      fvg_open         (bool 0/1) — незакрытый FVG
      choch            (bool 0/1) — CHoCH последние 5 баров
      bos              (bool 0/1) — BOS
      ote_zone         (bool 0/1) — цена в OTE по канону core.smc.fibonacci [0.5-0.79]
      eqh_near         (bool 0/1) — EQH рядом
      eql_near         (bool 0/1) — EQL рядом
      liquidity_above  (bool 0/1) — пул ликвидности выше

    Возвращает None если smc_snap пуст.
    """
    v: List[float] = []
    has_data = False
    for tf in _TFS:
        snap = smc_snap.get(tf) or {}
        if snap:
            has_data = True
        # ── прежние 9 булевых: сделки в БД собраны с ними, ломать нельзя ──
        v.append(1.0 if snap.get("ob_bull") else 0.0)
        v.append(float(snap.get("ob_distance_pct") or 0.0))
        v.append(1.0 if snap.get("fvg_open") else 0.0)
        v.append(1.0 if snap.get("choch") else 0.0)
        v.append(1.0 if snap.get("bos") else 0.0)
        v.append(1.0 if snap.get("ote_zone") else 0.0)
        v.append(1.0 if snap.get("eqh_near") else 0.0)
        v.append(1.0 if snap.get("eql_near") else 0.0)
        v.append(1.0 if snap.get("liquidity_above") else 0.0)
        # ── ARCH-137.6: непрерывные. У старых снапов их нет → _MISS ──
        # _MISS выбран вне рабочего диапазона (зоны лежат в пределах ±10 ATR),
        # чтобы дерево могло отделить «нет зоны» от «зона далеко», а не путать
        # отсутствие с нулём, который означает «зона ровно на цене».
        for k in _CONT_KEYS:
            x = snap.get(k)
            v.append(float(x) if isinstance(x, (int, float, bool)) else _MISS)
    if not has_data:
        return None
    return v


def _label_from_proba(p_win: float, smc_snap: Dict[str, Any]) -> str:
    """Категориальный label из вероятности и SMC-снимка."""
    # OB active на 4h/1h → усиленный сигнал
    ob_4h = (smc_snap.get("4h") or {}).get("ob_bull", False)
    ob_1h = (smc_snap.get("1h") or {}).get("ob_bull", False)

    if p_win > 0.65:
        if ob_4h or ob_1h:
            return "STRONG_BULL_ZONE"
        return "STRONG_BULL_ZONE"
    if p_win < 0.35:
        return "STRONG_BEAR_ZONE"
    if 0.45 <= p_win <= 0.55:
        return "NEUTRAL"
    return "WEAK_ZONE"


def _build_smc_snap_from_df(
    df: Any,  # pd.DataFrame
    current_price: float,
) -> Dict[str, Any]:
    """
    Вычисляет SMC-признаки для одного TF из DataFrame.
    Используется в trading_intelligence._build_smc_snap() для сбора smc_snap.

    Возвращает dict: `_v` + 9 булевых (историческая часть, совместимость с БД)
    + до 18 непрерывных (ARCH-137.6, блок ниже) = до 28 полей.
    """
    snap: Dict[str, Any] = {
        "_v": SNAP_SCHEMA_VERSION,   # версия схемы — fit учится на ОДНОЙ версии
        "ob_bull": False, "ob_distance_pct": 0.0,
        "fvg_open": False, "choch": False, "bos": False,
        "ote_zone": False, "eqh_near": False, "eql_near": False,
        "liquidity_above": False,
    }
    if df is None or len(df) < 30:
        return snap
    try:
        from core.smc.swing_points import detect_swing_points
        from core.smc.structure import detect_structure
        from core.smc.order_blocks import detect_order_blocks
        from core.smc.fvg import detect_fvg
        from core.smc.liquidity import detect_liquidity, detect_equal_highs_lows
        from core.smc.fibonacci import detect_fibonacci

        # ── Базовый анализ структуры и свингов ──
        # detect_structure возвращает StructureAnalysis (нужен для OB и Fib)
        # detect_swing_points возвращает SwingAnalysis (нужен для liquidity)
        structure = detect_structure(df, swing_period=5)
        swings_analysis = detect_swing_points(df, period=5)

        # CHoCH / BOS из structure.last_break
        if structure.last_break:
            snap["choch"] = structure.last_break.is_choch
            snap["bos"] = structure.last_break.is_bos

        # ── Order Blocks ──
        # detect_order_blocks возвращает OBAnalysis с готовыми nearest_bull/nearest_bear.
        # Раньше код передавал swings вместо structure → AttributeError → весь блок падал.
        try:
            obs = detect_order_blocks(df, structure)
            if obs.nearest_bull and current_price > 0:
                snap["ob_bull"] = True
                snap["ob_distance_pct"] = abs(obs.nearest_bull.midpoint - current_price) / current_price * 100
        except Exception as e:
            logger.debug("smc_snap OB error: %s", e)

        # ── FVG ──
        # detect_fvg возвращает FVGAnalysis с active_bull/active_bear списками.
        # Раньше код пытался итерироваться по объекту → TypeError.
        try:
            fvgs = detect_fvg(df)
            snap["fvg_open"] = bool(fvgs.active_bull) or bool(fvgs.active_bear)
        except Exception as e:
            logger.debug("smc_snap FVG error: %s", e)

        # ── OTE zone (канон core.smc.fibonacci 0.5–0.79, 19.09 «все на канон!») ──
        # Раньше код импортировал несуществующий detect_ote_zone → ImportError.
        # Реальная функция: detect_fibonacci(df, structure) → FibAnalysis с active_ote.
        try:
            fib = detect_fibonacci(df, structure)
            if fib.active_ote and fib.active_ote.price_in_ote:
                snap["ote_zone"] = True
        except Exception as e:
            logger.debug("smc_snap OTE error: %s", e)

        # ── Equal Highs / Equal Lows ──
        try:
            eqhl = detect_equal_highs_lows(df, threshold_pct=0.01, lookback=50)
            snap["eqh_near"] = bool(eqhl.get("eqh_near", False))
            snap["eql_near"] = bool(eqhl.get("eql_near", False))
        except Exception as e:
            logger.debug("smc_snap EQH/EQL error: %s", e)

        # ── Liquidity ──
        # detect_liquidity ожидает SwingAnalysis объект, не список свингов.
        try:
            liq = detect_liquidity(df, swings_analysis)
            snap["liquidity_above"] = liq.nearest_buy is not None
        except Exception as e:
            logger.debug("smc_snap LIQ error: %s", e)

        # ══ ARCH-137.6: НЕПРЕРЫВНЫЕ признаки ═══════════════════════════════
        # Перемер 02.09 показал: булевы «есть ли зона» вырождаются тем сильнее,
        # чем ЛУЧШЕ работает детектор. После починки FVG поле fvg_open стало
        # True в 100% случаев — вопрос «есть ли открытый FVG» перестал различать.
        # Поэтому рядом со старыми полями (нужны для совместимости со сделками,
        # уже лежащими в БД) кладём величины: РАССТОЯНИЕ до зоны, её РАЗМЕР и
        # ВОЗРАСТ события. Всё в ATR и барах — величины сопоставимы между
        # инструментами и ТФ, в отличие от процентов цены.
        try:
            _atr = _atr_value(df)
            if _atr > 0 and current_price > 0:
                n = len(df)

                def _d(level: float) -> float:
                    """Знаковое расстояние в ATR: + зона выше цены, − ниже."""
                    return round((float(level) - current_price) / _atr, 3)

                # Order Blocks: расстояние до ближайшего с каждой стороны
                try:
                    if obs.nearest_bull:
                        snap["ob_bull_dist_atr"] = _d(obs.nearest_bull.midpoint)
                        snap["ob_bull_age"] = int(n - 1 - obs.nearest_bull.index)
                    if obs.nearest_bear:
                        snap["ob_bear_dist_atr"] = _d(obs.nearest_bear.midpoint)
                except (NameError, AttributeError):
                    pass

                # FVG: ближайшая активная зона — расстояние и размер
                try:
                    _act = list(fvgs.active_bull or []) + list(fvgs.active_bear or [])
                    if _act:
                        z = min(_act, key=lambda f: abs(f.midpoint - current_price))
                        snap["fvg_dist_atr"] = _d(z.midpoint)
                        snap["fvg_size_atr"] = round((z.top - z.bottom) / _atr, 3)
                        snap["fvg_age"] = int(n - 1 - z.index)
                        snap["fvg_fill_pct"] = round(float(z.mitigation_pct), 3)
                except (NameError, AttributeError):
                    pass

                # Структура: возраст последнего слома и расстояние до его уровня
                if structure.last_break:
                    lb = structure.last_break
                    snap["brk_age"] = int(n - 1 - lb.break_index)
                    snap["brk_dist_atr"] = _d(lb.level)
                    snap["brk_strength"] = int(getattr(lb, "strength", 0))
                    # слой эталона: микроструктура или старшая структура
                    snap["brk_internal"] = bool(getattr(lb, "internal", True))

                # Фибо: положение цены в диапазоне — непрерывная замена ote_zone
                try:
                    # active_ote заполняется, ТОЛЬКО когда цена внутри OTE — то есть
                    # редко. Для непрерывного признака берём свежую зону из fib.zones:
                    # положение цены в импульсе осмысленно всегда, а не только в OTE.
                    _z = fib.active_ote or (fib.zones[-1] if getattr(fib, "zones", None) else None)
                    if _z is not None:
                        _hi = float(getattr(_z, "impulse_high", 0) or 0)
                        _lo = float(getattr(_z, "impulse_low", 0) or 0)
                        if _hi > _lo > 0:
                            snap["fib_pos"] = round((current_price - _lo) / (_hi - _lo), 3)
                            snap["ote_dist_atr"] = _d(float(_z.ote_midpoint))
                            snap["fib_dir_long"] = bool(str(_z.direction).upper() == "LONG")
                except (NameError, AttributeError, IndexError):
                    pass

                # EQH/EQL: расстояние до ближайшего НЕСНЯТОГО уровня
                try:
                    if eqhl.get("eqh_level"):
                        snap["eqh_dist_atr"] = _d(eqhl["eqh_level"])
                    if eqhl.get("eql_level"):
                        snap["eql_dist_atr"] = _d(eqhl["eql_level"])
                except (NameError, AttributeError):
                    pass

                # Ликвидность: расстояние до ближайшего пула сверху и снизу
                try:
                    if liq.nearest_buy:
                        snap["liq_buy_dist_atr"] = _d(liq.nearest_buy.level)
                    if liq.nearest_sell:
                        snap["liq_sell_dist_atr"] = _d(liq.nearest_sell.level)
                except (NameError, AttributeError):
                    pass
        except Exception as e:
            logger.debug("smc_snap continuous error: %s", e)

    except Exception as e:
        logger.debug("_build_smc_snap_from_df error: %s", e)

    return snap


def _atr_value(df: Any, period: int = 14) -> float:
    """ATR (Wilder) последнего бара. 0.0 если посчитать нельзя."""
    try:
        import pandas as pd
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
                       axis=1).max(axis=1)
        v = float(tr.ewm(alpha=1.0 / period, adjust=False).mean().iloc[-1])
        return v if v == v and v > 0 else 0.0
    except Exception:
        return 0.0


class MTFSMCSpecialist:
    """
    SMC Specialist: RandomForest на 36 признаках (4 TF × 9).

    Использование:
        spec = MTFSMCSpecialist()
        spec.fit("subscriptions.db")
        verdict = spec.predict(smc_snap_dict)
        # → SMCVerdict(label="STRONG_BULL_ZONE", confidence=0.71)
    """

    def __init__(self) -> None:
        self._model = None
        self._trained = False
        self._n_samples = 0
        self._cv_score: Optional[float] = None
        # ARCH-137.6: индексы признаков, отобранных при обучении.
        # predict обязан подавать ровно их — иначе порядок полей поедет.
        self._feat_idx: Optional[List[int]] = None

    # ------------------------------------------------------------------
    def fit(self, db_path: str = "subscriptions.db") -> bool:
        if not _SKLEARN_OK:
            return False
        try:
            rows = self._load_closed_trades(db_path)
            X, y = [], []
            skipped_ver = 0
            for r in rows:
                try:
                    fj = json.loads(r.get("features_json") or "{}")
                    smc_snap = fj.get("smc_snap")
                    if not smc_snap:
                        continue
                    # ARCH-137.6: только текущая версия схемы. Смесь версий даёт
                    # AUC 0.379 против 0.551 на однородном месяце — см. константу.
                    _v = 1
                    for _tf_snap in smc_snap.values():
                        if isinstance(_tf_snap, dict) and "_v" in _tf_snap:
                            _v = int(_tf_snap["_v"]); break
                    if _v != SNAP_SCHEMA_VERSION:
                        skipped_ver += 1
                        continue
                    fv = _build_smc_features(smc_snap)
                    if fv is None:
                        continue
                    X.append(fv)
                    # DEV-190: учёт скрытых TSL exits под status='SL'
                    from core.trading.effective_status import is_win as _is_win
                    y.append(1 if _is_win(r["status"], r.get("R_multiple"), r.get("tsl_activated")) else 0)
                except Exception as row_err:
                    logger.debug("MTFSMCSpecialist: пропуск строки — %s", row_err)
                    continue

            if len(X) < MIN_TRADES:
                logger.info(
                    "MTFSMCSpecialist: недостаточно данных схемы v%d (%d/%d) — пропуск"
                    "%s. Модель молчит, пока не накопится свежая история — это НЕ сбой,"
                    " а защита от обучения на смеси версий (ARCH-137.6).",
                    SNAP_SCHEMA_VERSION, len(X), MIN_TRADES,
                    f"; отброшено по версии: {skipped_ver}" if skipped_ver else "",
                )
                return False

            if len(set(y)) < 2:
                logger.warning("MTFSMCSpecialist: в y только 1 класс — пропуск")
                return False

            model = RandomForestClassifier(
                n_estimators=200,
                max_depth=5,
                min_samples_leaf=5,
                random_state=42,
                n_jobs=-1,
            )
            # ── ARCH-137.6: отбор признаков по объёму выборки ──────────────
            # Вектор вырос с 36 до 108 полей (добавлены непрерывные), а сделок
            # со snap порядка 300. Обучение на всех 108 = переобучение: замер
            # 02.09 (nested CV, отбор внутри фолда) дал монотонную кривую —
            #   топ-8  AUC 0.595 ± 0.032
            #   топ-14 AUC 0.575
            #   топ-27 AUC 0.476   (хуже монетки)
            # Поэтому K привязан к объёму: ~25 наблюдений на признак. Модель
            # растит себе вектор сама, по мере накопления сделок.
            k = max(_MIN_FEATURES, min(len(X) // _SAMPLES_PER_FEATURE, len(X[0])))
            feat_idx = list(range(len(X[0])))
            if k < len(X[0]):
                ranker = RandomForestClassifier(
                    n_estimators=200, max_depth=6, min_samples_leaf=5,
                    random_state=42, n_jobs=-1,
                ).fit(X, y)
                order = sorted(range(len(X[0])),
                               key=lambda j: -ranker.feature_importances_[j])
                feat_idx = sorted(order[:k])
            Xs = [[row[j] for j in feat_idx] for row in X]
            self._feat_idx = feat_idx

            try:
                scores = cross_val_score(
                    model, Xs, y, cv=min(5, len(Xs) // 10), scoring="roc_auc",
                )
                self._cv_score = float(scores.mean())
            except Exception:
                self._cv_score = None

            model.fit(Xs, y)
            self._model = model
            self._trained = True
            self._n_samples = len(Xs)

            model_path = os.path.join(os.path.dirname(db_path) or ".", _MODEL_FILE)
            try:
                import joblib
                # 🔴 Индексы сохраняются ВМЕСТЕ с моделью: predict обязан подавать
                # ровно те же признаки, иначе порядок поедет и вердикт станет мусором.
                joblib.dump({"model": model, "feat_idx": feat_idx}, model_path)
            except Exception:
                pass

            win_rate = sum(y) / len(y) * 100
            logger.info(
                "MTFSMCSpecialist: обучено на %d сделках | win_rate=%.1f%% | CV AUC=%s",
                len(X), win_rate,
                f"{self._cv_score:.3f}" if self._cv_score else "n/a",
            )
            return True

        except Exception as e:
            logger.exception("MTFSMCSpecialist.fit: %s", e)
            return False

    # ------------------------------------------------------------------
    def predict(self, smc_snap: Dict[str, Any]) -> Optional[SMCVerdict]:
        if not self._trained or self._model is None:
            return None
        if not smc_snap:
            return None
        try:
            fv = _build_smc_features(smc_snap)
            if fv is None:
                return None
            # ARCH-137.6: тот же отбор, что применён при обучении. Без него модель
            # получит 108 полей вместо K и вернёт мусор с видом уверенности.
            idx = getattr(self, "_feat_idx", None)
            if idx:
                if max(idx) >= len(fv):
                    logger.debug("MTFSMCSpecialist: вектор короче обученного — пропуск")
                    return None
                fv = [fv[j] for j in idx]
            proba = self._model.predict_proba([fv])[0]
            p_win = float(proba[1])
            label = _label_from_proba(p_win, smc_snap)
            return SMCVerdict(label=label, confidence=p_win)
        except Exception as e:
            logger.debug("MTFSMCSpecialist.predict: %s", e)
            return None

    # ------------------------------------------------------------------
    @staticmethod
    def _load_closed_trades(db_path: str) -> List[Dict]:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            # DEV-190: добавлены tsl_activated и R_multiple для is_win helper
            cur.execute("""
                SELECT status, features_json, tsl_activated, R_multiple
                FROM simulated_trades
                WHERE status IN ('TP', 'SL', 'TSL')
                  AND features_json IS NOT NULL
                  AND features_json != '{}'
            """)
            return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    @property
    def is_trained(self) -> bool:
        return self._trained

    def info(self) -> Dict:
        return {
            "trained": self._trained,
            "n_samples": self._n_samples,
            "cv_auc": self._cv_score,
            "n_features": _N_FEATURES,
        }
