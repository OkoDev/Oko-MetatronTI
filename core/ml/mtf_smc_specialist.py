"""
MTF SMC Specialist — DEV-139 / ARCH-68 Фаза 2.

RandomForest на SMC-снимках 4 таймфреймов (36 признаков = 4 TF × 9).
Предсказывает вероятность TP и возвращает SMCVerdict.

Shadow mode: результат пишется в recommendation.metadata["smc_verdict"].
Не влияет на strength/action пока нет 200+ сделок с smc_snap.

Источник данных: features_json["smc_snap"] — добавляется в register_trade_async
через _build_smc_snap() в trading_intelligence.py.
"""
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MIN_TRADES = 50

# 4 TF по спеке ARCH-68
_TFS = ["1d", "4h", "1h", "15m"]
_N_FEATURES = len(_TFS) * 9  # 36

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


def _build_smc_features(smc_snap: Dict[str, Any]) -> Optional[List[float]]:
    """
    Строит вектор из 36 признаков (4 TF × 9).

    Per TF:
      ob_bull          (bool 0/1) — бычий OB активен
      ob_distance_pct  (float)    — % до ближайшего OB
      fvg_open         (bool 0/1) — незакрытый FVG
      choch            (bool 0/1) — CHoCH последние 5 баров
      bos              (bool 0/1) — BOS
      ote_zone         (bool 0/1) — цена в OTE [0.705-0.786]
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
        v.append(1.0 if snap.get("ob_bull") else 0.0)
        v.append(float(snap.get("ob_distance_pct") or 0.0))
        v.append(1.0 if snap.get("fvg_open") else 0.0)
        v.append(1.0 if snap.get("choch") else 0.0)
        v.append(1.0 if snap.get("bos") else 0.0)
        v.append(1.0 if snap.get("ote_zone") else 0.0)
        v.append(1.0 if snap.get("eqh_near") else 0.0)
        v.append(1.0 if snap.get("eql_near") else 0.0)
        v.append(1.0 if snap.get("liquidity_above") else 0.0)
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

    Возвращает dict с 9 признаками.
    """
    snap: Dict[str, Any] = {
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

        # Structure: CHoCH / BOS
        sa = detect_structure(df, swing_period=5)
        if sa.last_break:
            snap["choch"] = sa.last_break.is_choch
            snap["bos"]   = sa.last_break.is_bos

        # Order Blocks
        swings = detect_swing_points(df, period=5)
        obs = detect_order_blocks(df, swings)
        bull_obs = [ob for ob in obs if ob.direction == "LONG" and ob.is_active]
        if bull_obs and current_price > 0:
            # Ближайший бычий OB
            nearest = min(bull_obs, key=lambda ob: abs(ob.level - current_price))
            snap["ob_bull"] = True
            snap["ob_distance_pct"] = abs(nearest.level - current_price) / current_price * 100

        # FVG
        fvgs = detect_fvg(df)
        snap["fvg_open"] = any(not fvg.filled for fvg in fvgs)

        # OTE zone (Fib 0.705–0.786) — упрощённая проверка по последнему swing
        try:
            from core.smc.fibonacci import detect_ote_zone
            fib = detect_ote_zone(df)
            if fib and fib.active_ote:
                snap["ote_zone"] = fib.active_ote.price_in_ote
        except Exception:
            pass

        # EQH/EQL
        eqhl = detect_equal_highs_lows(df, threshold_pct=0.01, lookback=50)
        snap["eqh_near"] = eqhl["eqh_near"]
        snap["eql_near"] = eqhl["eql_near"]

        # Liquidity above
        liq = detect_liquidity(df, swings)
        snap["liquidity_above"] = liq.nearest_buy is not None

    except Exception as e:
        logger.debug("_build_smc_snap_from_df error: %s", e)

    return snap


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

    # ------------------------------------------------------------------
    def fit(self, db_path: str = "subscriptions.db") -> bool:
        if not _SKLEARN_OK:
            return False
        try:
            rows = self._load_closed_trades(db_path)
            X, y = [], []
            for r in rows:
                try:
                    fj = json.loads(r.get("features_json") or "{}")
                    smc_snap = fj.get("smc_snap")
                    if not smc_snap:
                        continue
                    fv = _build_smc_features(smc_snap)
                    if fv is None:
                        continue
                    X.append(fv)
                    y.append(1 if r["status"] in ("TP", "TSL") else 0)
                except Exception as row_err:
                    logger.debug("MTFSMCSpecialist: пропуск строки — %s", row_err)
                    continue

            if len(X) < MIN_TRADES:
                logger.info(
                    "MTFSMCSpecialist: недостаточно данных с smc_snap (%d/%d) — пропуск",
                    len(X), MIN_TRADES,
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
            try:
                scores = cross_val_score(
                    model, X, y, cv=min(5, len(X) // 10), scoring="roc_auc",
                )
                self._cv_score = float(scores.mean())
            except Exception:
                self._cv_score = None

            model.fit(X, y)
            self._model = model
            self._trained = True
            self._n_samples = len(X)

            model_path = os.path.join(os.path.dirname(db_path) or ".", _MODEL_FILE)
            try:
                import joblib
                joblib.dump(model, model_path)
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
            cur.execute("""
                SELECT status, features_json
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
