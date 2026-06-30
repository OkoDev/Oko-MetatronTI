"""OTE Signal Generator — движок генерации сигналов из шкафа сетапов.

НЕ новая сфера: обёртка над эталоном `smc_engine` (ОДИН калькулятор, ARCH-118 → parity
live==бэктест). Читает шкаф `config/ote_setups.yaml`, для каждого enabled-сетапа строит
OTE-зону (provisional нога = live-зрение), собирает зональные триггеры (OB/FVG/EQL/SC)
и проверяет ВЫСТРЕЛ (касание триггера + бычья реакция + ATRTrend↑).

Конвейер: ПИСТОЛЕТ (OTE-зона) → ПРЕДОХРАНИТЕЛЬ (триггеры в зоне) → КУРОК (цена в зоне)
          → ВЫСТРЕЛ (реакция от триггера + ATRTrend) → OTESignal(status=FIRE).

Поток: ote_observer_loop → generate(sym, dfs) → [OTESignal] → trade_simulator (VST).
Калибровки (ночь 04.06): zigzag per-ТФ · FVG mitigation fv[5] · SC свип+CHoCH+FVG ·
detect_structure_breaks length=5 · EQL фильтр отскока.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import yaml

from core.smc.smc_engine import (
    ote_retest_setups, detect_fvg, detect_order_blocks, detect_structure_breaks,
    detect_equal_levels, detect_sponsored_candle,
)

_CONFIG = Path(__file__).resolve().parents[2] / "config" / "ote_setups.yaml"


_CB = None
def _combinator():
    """ARCH-118.3: ЧИСТЫЙ единый калькулятор из core (без sys.path/combinator_v2 хака)."""
    global _CB
    if _CB is None:
        from core.calculators import combinator_core as m
        _CB = m
    return _CB


def _atr_trend_up(df) -> bool:
    """ATRTrend (supertrend) развёрнут вверх на последнем баре. Эталон combinator."""
    try:
        a = _combinator().atr_supertrend(df)
        return bool(a[-1] == 1)
    except Exception:
        return False


def _raw_wt_cross(df, up: bool, look: int = 3) -> bool:
    """СЫРОЙ WaveTrend cross (как глаз/Pine OKO-SM), БЕЗ strict-условия OS<-60 (DEV-234).
    up=True → wt1 пересёк wt2 снизу вверх в последних look барах. Для OTE-подтверждения."""
    try:
        import pandas as pd
        wt = _combinator().wavetrend(df).values
        wt2 = pd.Series(wt).rolling(4, min_periods=1).mean().values
    except Exception:
        return False
    n = len(wt)
    for i in range(max(1, n - look), n):
        if up and wt[i - 1] <= wt2[i - 1] and wt[i] > wt2[i]:
            return True
        if not up and wt[i - 1] >= wt2[i - 1] and wt[i] < wt2[i]:
            return True
    return False


@dataclass
class OTESignal:
    """Сигнал из шкафа. status=ARMED (цена в зоне, ждём) / FIRE (выстрел — регистрировать)."""
    symbol: str
    setup_id: str            # "4h_5m_pull"
    tier: int                # 1/2/3
    weight: float
    type: str                # pull / cont
    direction: str           # long / short
    htf: str
    ltf: str
    status: str              # ARMED / FIRE
    entry: float
    sl: float                # за свип/структуру/инвалидацию
    tp1: float               # +1R
    tp_runner: float         # cont→HTF-target, pull→OTE
    risk: float
    ote_zone: tuple          # (lo, hi)
    trigger_type: str        # FVG/OB/EQL/SC (что сработало) или "" для ARMED
    trigger_zone: tuple      # зона триггера
    atr_trend_up: bool
    confirmations: list      # сработавшие подтверждения (div/wt_cross/fvg_held/vol/liq_sweep/atr)
    conf_score: int          # len(confirmations)
    entry_ts: object
    meta: dict = field(default_factory=dict)


class OTESignalGenerator:
    """Читает шкаф → генерит OTE-сигналы (ARMED/FIRE) по enabled-сетапам."""

    def __init__(self, config_path: Path | str = _CONFIG):
        self.config_path = Path(config_path)
        self._load()

    def _load(self) -> None:
        cfg = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        self.execution = cfg.get("execution", {})
        # выстрел = касание+реакция + score подтверждений ≥ min_confirmations (config)
        self.min_confirmations = int(self.execution.get("min_confirmations", 3))
        # runner должен давать ≥ этого RR (иначе rr_filter роутера зарежет → скип FIRE заранее).
        # ДОЛЖНО совпадать с config.yaml → trading.min_rr_ratio (2.0).
        self.min_runner_rr = float(self.execution.get("min_runner_rr", 2.0))
        self.tier_weights = cfg.get("tier_weights", {1: 1.0, 2: 0.6, 3: 0.3})
        self.zigzag_params = cfg.get("zigzag_params", {})
        self.ds_patterns = cfg.get("ds_patterns", {})
        self.setups: List[dict] = []
        for tname, tnum in (("tier1", 1), ("tier2", 2), ("tier3", 3)):
            for s in cfg.get(tname, []):
                if s.get("enabled"):
                    s = dict(s); s["tier"] = tnum
                    self.setups.append(s)

    def reload(self) -> None:
        self._load()

    def _zz(self, tf: str):
        """Per-ТФ zigzag параметры (калибровка под OKO-SM), дефолт 11/3."""
        p = self.zigzag_params.get(tf) or {}
        return int(p.get("depth") or 11), float(p.get("dev") or 3.0)

    # ── сбор зональных триггеров (OB/FVG/EQL/SC) ───────────────────────────────
    def _collect_triggers(self, ote_lo, ote_hi, direction, dfs, w0, w1) -> list:
        """Триггеры В OTE-зоне из ОКНА ИМПУЛЬСА [w0..w1] (эталон XLM: сам импульс,
        НЕ от импульса до now). Приоритет силы: SC*>EQL>OB>FVG.
        FVG mitigation по fv[5] · EQL фильтр отскока · SC свип+CHoCH+FVG."""
        want = "bull" if direction == "long" else "bear"
        out = []
        for tf in ("15m", "5m", "3m"):
            df = dfs.get(tf)
            if df is None:
                continue
            # окно = САМ импульс [from..to] (где сформированы OB/FVG/SC), не хвост до now
            imp = df.loc[w0:w1] if (len(df) and df.index[0] <= w1) else df
            if len(imp) < 5:
                continue
            # FVG (mitigation fv[5]=None=активен)
            for fv in detect_fvg(imp):
                top, bot, dr, mit = max(fv[1], fv[2]), min(fv[1], fv[2]), fv[3], fv[5]
                import pandas as pd
                if dr == want and ote_lo * 0.999 <= bot and top <= ote_hi * 1.001:
                    if mit is not None and pd.notna(mit):
                        continue                          # mitigated по close → пропуск
                    out.append(("FVG", tf, bot, top, (top + bot) / 2, 2))
            # OB (length=5)
            for ob in detect_order_blocks(imp, detect_structure_breaks(imp, length=5)):
                if ob.kind == want:
                    t, b = max(ob.top, ob.bottom), min(ob.top, ob.bottom)
                    if ote_lo * 0.999 <= b and t <= ote_hi * 1.001:
                        w = 1 if ob.mitigated_idx >= 0 else 3
                        out.append(("OB", tf, b, t, (b + t) / 2, w))
            # EQL/EQH (фильтр отскока >1.5%)
            for (t1, p1, t2, p2, lab) in detect_equal_levels(imp):
                lvl = (p1 + p2) / 2
                ok = (direction == "long" and lab == "EQL") or (direction == "short" and lab == "EQH")
                if ok and ote_lo <= lvl <= ote_hi:
                    seg = imp.loc[t1:t2]
                    if len(seg) and (seg["high"].max() - lvl) / lvl * 100 > 1.5:
                        out.append(("EQL", tf, lvl, lvl, lvl, 4))
            # SC (свип+разворот; confirmed=свип+CHoCH+FVG)
            for sc in detect_sponsored_candle(imp):
                if sc.direction == want and (ote_lo <= sc.bottom <= ote_hi or ote_lo <= sc.top <= ote_hi):
                    out.append(("SC*" if sc.confirmed else "SC", tf, sc.bottom, sc.top, sc.mt, 5 if sc.confirmed else 4))
        return self._merge(out)

    def _merge(self, trg) -> list:
        """Схлопывает перекрывающиеся по цене триггеры в зоны. КОНФЛЮЕНЦИЯ:
        совпадение разных ТФ/типов в одном месте → вес растёт (+1 за доп. ТФ).
        Чистит шум (127 мелких FVG → несколько сильных зон). Сильнейшие первыми."""
        trg = sorted(trg, key=lambda x: min(x[2], x[3]))
        merged = []
        for t in trg:
            lo, hi = min(t[2], t[3]), max(t[2], t[3])
            for m in merged:
                if not (hi < m["lo"] or lo > m["hi"]):       # пересечение зон
                    m["lo"], m["hi"] = min(m["lo"], lo), max(m["hi"], hi)
                    m["tfs"].add(t[1]); m["types"].add(t[0]); m["w"] = max(m["w"], t[5])
                    break
            else:
                merged.append({"lo": lo, "hi": hi, "tfs": {t[1]}, "types": {t[0]}, "w": t[5]})
        out = []
        for m in merged:
            w = m["w"] + (len(m["tfs"]) - 1)                 # конфлюенс-бонус за мульти-ТФ
            typ = "+".join(sorted(m["types"]))
            out.append((typ, ",".join(sorted(m["tfs"])), m["lo"], m["hi"], (m["lo"] + m["hi"]) / 2, w))
        return sorted(out, key=lambda x: -x[5])             # сильнейшие первыми

    # ── курок: касание триггера + реакция (БАЗА, обязательна) ───────────────────
    def _check_shot(self, trg, df_ltf, direction, look=5):
        """Возвращает (touched_react, entry, bar) — касание триггер-зоны + бычья/медвежья
        РЕАКЦИЯ (свеча). ATRTrend убран из обязательных → стал голосом в confirmation-score."""
        _, _, a, b, mid, _ = trg
        zlo, zhi = min(a, b), max(a, b)
        o = df_ltf["open"].values; h = df_ltf["high"].values
        l = df_ltf["low"].values; c = df_ltf["close"].values
        n = len(df_ltf)
        for k in range(max(1, n - look), n):
            rng = h[k] - l[k]
            if rng <= 0:
                continue
            if direction == "long":
                touched = l[k] <= zhi and h[k] >= zlo * 0.998
                react = c[k] > o[k] and (c[k] - l[k]) / rng > 0.55 and c[k] >= zlo
            else:
                touched = h[k] >= zlo and l[k] <= zhi * 1.002
                react = c[k] < o[k] and (h[k] - c[k]) / rng > 0.55 and c[k] <= zhi
            if touched and react:
                return True, float(c[k]), float(h[k]), float(l[k])
        return False, 0.0, 0.0, 0.0

    # ── стек подтверждений входа (пазлы собираются) ────────────────────────────
    def _ltf_flags(self, df, ltf):
        """compute_flags на LTF один раз (эталон combinator). last row или None."""
        if df is None or len(df) < 60:
            return None
        try:
            return _combinator().compute_flags(df, ltf).iloc[-1]
        except Exception:
            return None

    def _confirmations(self, direction, dfs, ltf, flast) -> list:
        """Стек подтверждений (ОДИН калькулятор combinator + сырой WT). Список сработавших.
        div · fvg_held · vol · liq_sweep (combinator-флаги) · wt_cross (сырой) · atr (3m/15m)."""
        is_long = direction == "long"
        want = "bull" if is_long else "bear"
        conf = []
        if flast is not None:
            g = lambda k: bool(flast.get(k, False))
            if g(f"rsi_div_{want}_regular_{ltf}") or g(f"rsi_div_{want}_hidden_{ltf}"):
                conf.append("div")
            if g(f"{want}_fvg_overlap_held_{ltf}"):
                conf.append("fvg_held")
            if g(f"vol_spike_{ltf}"):
                conf.append("vol")
            if g(f"{'eql' if is_long else 'eqh'}_sweep_{ltf}"):
                conf.append("liq_sweep")
        dfl = dfs.get(ltf)
        if dfl is not None and _raw_wt_cross(dfl, is_long):       # сырой WT (не strict OS<-60)
            conf.append("wt_cross")
        for atf in ("3m", "15m"):                                 # ATR на НЕ-шумном ТФ (не entry)
            d = dfs.get(atf)
            if d is not None and len(d) > 30 and _atr_trend_up(d) == is_long:
                conf.append("atr"); break
        return conf

    # ── ядро ────────────────────────────────────────────────────────────────
    def generate(self, symbol: str, dfs: Dict[str, "pd.DataFrame"]) -> List[OTESignal]:
        """dfs: {'3m','5m','15m','1h','4h','1d'}. Возвращает ARMED/FIRE сигналы."""
        out: List[OTESignal] = []
        flags_cache: dict = {}                              # ltf -> compute_flags last row (1 раз)
        for st in self.setups:
            df_htf = dfs.get(st["htf"]); df_ltf = dfs.get(st["ltf"])
            if df_htf is None or df_ltf is None or len(df_htf) < 50 or len(df_ltf) < 50:
                continue
            depth, dev = self._zz(st["htf"])
            # ЭТАЛОН + provisional нога (live-зрение)
            setups = ote_retest_setups(df_htf, depth=depth, dev_mult=dev,
                                       only_choch=False, provisional=True)
            if not setups:
                continue
            sig = self._emit(symbol, st, setups, dfs, flags_cache)
            if sig is not None:
                out.append(sig)
        return out

    def _emit(self, symbol, st, setups, dfs, flags_cache) -> Optional[OTESignal]:
        h = setups[-1]
        ote_lo, ote_hi = h["ote"]; htf_dir = h["direction"]; stype = st["type"]
        ltf = st["ltf"]; df_ltf = dfs[ltf]
        price = float(df_ltf["close"].values[-1])
        if not (ote_lo <= price <= ote_hi):
            return None                                     # цена не в зоне → даже не ARMED
        direction = htf_dir if stype == "cont" else ("short" if htf_dir == "long" else "long")
        tp_runner = h["to"][1] if stype == "cont" else (ote_lo + ote_hi) / 2.0
        w0, w1 = h["from"][0], h["to"][0]
        triggers = self._collect_triggers(ote_lo, ote_hi, direction, dfs, w0, w1)
        status, trg_type, trg_zone, entry = "ARMED", "", (0.0, 0.0), price
        bar_hi = bar_lo = 0.0
        confs: list = []
        # ВЫСТРЕЛ = касание+реакция (база) + score подтверждений ≥ min_confirmations.
        # Перебор ВСЕХ триггеров (не только сильнейшего!) — цена реагирует от зоны ГДЕ ОНА,
        # а сильнейший по конфлюенции может быть в стороне. Среди коснувшихся — сильнейший.
        fired = None
        for tg in triggers:                              # отсортированы по силе
            touched, e, bh, bl = self._check_shot(tg, df_ltf, direction)
            if touched:
                fired = (tg, e, bh, bl)
                break
        if fired:
            tg, e, bh, bl = fired
            if ltf not in flags_cache:
                flags_cache[ltf] = self._ltf_flags(dfs.get(ltf), ltf)
            confs = self._confirmations(direction, dfs, ltf, flags_cache[ltf])
            if len(confs) >= self.min_confirmations:
                status, entry, bar_hi, bar_lo = "FIRE", e, bh, bl
                trg_type, trg_zone = tg[0], (tg[2], tg[3])
        atr_up = "atr" in confs
        # 🔴 ШИРОКИЙ direction-correct SL (30.06) = за начало LTF-СЛОМА-импульса в сторону сделки
        # (как honest-backtest +0.296R). НЕ HTF h["sl"] (он = начало HTF-импульса → для pull
        # инвертирован). Берём последний LTF-слом direction==сделки → levels[1.0]. ОБЯЗАТЕЛЬНАЯ
        # проверка инверсии (long: sl<entry, short: sl>entry) + fallback свеча — защита от повтора
        # бага инверсии. [[ote_production_drift_root]].
        imp_lo, imp_hi = h["from"][1], h["to"][1]
        buf = 0.0015
        sl = None
        try:
            from core.smc.smc_engine import find_setups_zz as _fsz, zigzag_atr as _zz
            _cands = []
            for _s in _fsz(_zz(df_ltf), df_ltf):
                if _s.get("direction") != direction:
                    continue
                lv = float(_s["levels"][1.0])
                lv = lv * (1 - buf) if direction == "long" else lv * (1 + buf)
                # direction-correct: long SL ниже входа, short выше
                if (direction == "long" and lv < entry) or (direction == "short" and lv > entry):
                    _cands.append(lv)
            if _cands:
                # БЛИЖАЙШИЙ к entry (компактный, не гигантский последний слом) + cap 15%
                _best = max(_cands) if direction == "long" else min(_cands)
                if abs(entry - _best) / entry <= 0.15:
                    sl = _best
        except Exception:
            sl = None
        if sl is None:                                      # fallback: свеча реакции / последние бары
            if status == "FIRE" and (bar_hi or bar_lo):
                sl = bar_hi * (1 + buf) if direction == "short" else bar_lo * (1 - buf)
            else:
                lb = min(10, len(df_ltf) - 1)
                sl = (float(df_ltf["high"].values[-lb:].max()) if direction == "short"
                      else float(df_ltf["low"].values[-lb:].min()))
        risk = abs(entry - sl)
        if risk <= 0:
            return None
        tp1 = entry + risk if direction == "long" else entry - risk
        # RR-фильтр ЗАРАНЕЕ: rr_filter роутера/register режут RR<2.0 (строго). Не плодим
        # мёртвый FIRE — если runner не даёт >= min_runner_rr, остаёмся ARMED (ждём цель/вход).
        runner_ok = ((direction == "long" and tp_runner > entry) or
                     (direction == "short" and tp_runner < entry))
        rr_runner = abs(tp_runner - entry) / risk if runner_ok else 0.0
        # 27.06 ОЖИВЛЕНИЕ: снят min_runner_rr-гейт (FIRE→ARMED по runner-RR). Выход = tp1 (1R),
        # runner отключён → его RR нерелевантен. Раньше резал FIRE если runner<2R. rr_runner
        # ниже оставлен только для ARMED-отчётности tp_runner.
        if not runner_ok:
            tp_runner = tp1                                        # для ARMED-отчётности
        return OTESignal(
            symbol=symbol, setup_id=st["id"], tier=st["tier"],
            weight=self.tier_weights.get(st["tier"], 0.3),
            type=stype, direction=direction, htf=st["htf"], ltf=st["ltf"], status=status,
            entry=round(entry, 8), sl=round(float(sl), 8), tp1=round(float(tp1), 8),
            tp_runner=round(float(tp_runner), 8), risk=round(float(risk), 8),
            ote_zone=(round(ote_lo, 8), round(ote_hi, 8)),
            trigger_type=trg_type, trigger_zone=(round(trg_zone[0], 8), round(trg_zone[1], 8)),
            atr_trend_up=atr_up, confirmations=confs, conf_score=len(confs),
            entry_ts=df_ltf.index[-1],
            meta={"impulse": [imp_lo, imp_hi], "triggers_n": len(triggers),
                  "avgR_backtest": st.get("avgR"), "wr_backtest": st.get("wr"), "unconfirmed": h.get("unconfirmed")},
        )


if __name__ == "__main__":
    import sys, pandas as pd
    sys.stdout.reconfigure(encoding="utf-8")
    gen = OTESignalGenerator()
    print(f"enabled-сетапов: {len(gen.setups)}")
    sym = "BTCUSDT"; dfs = {}
    for tf in ["3m", "5m", "15m", "1h"]:
        p = Path(f"data/history/{tf}/{sym}.parquet")
        if p.exists():
            dfs[tf] = pd.read_parquet(p).tail(5000)
    if "1h" in dfs:
        b = dfs["1h"]
        for tf, rule in [("4h", "4h"), ("1d", "1D")]:
            dfs[tf] = pd.DataFrame({"open": b["open"].resample(rule).first(), "high": b["high"].resample(rule).max(),
                "low": b["low"].resample(rule).min(), "close": b["close"].resample(rule).last()}).dropna()
    sigs = gen.generate(sym, dfs)
    print(f"сигналов: {len(sigs)} (ARMED={sum(s.status=='ARMED' for s in sigs)} FIRE={sum(s.status=='FIRE' for s in sigs)})")
    for s in sigs:
        print(f"  [{s.setup_id} T{s.tier}] {s.status} {s.direction} entry={s.entry} SL={s.sl} "
              f"TP1={s.tp1} trg={s.trigger_type} conf={s.conf_score}{s.confirmations}")
