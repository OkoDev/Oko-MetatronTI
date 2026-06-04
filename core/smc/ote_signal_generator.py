"""OTE Signal Generator — движок генерации сигналов из шкафа сетапов.

НЕ новая сфера: тонкая обёртка над эталоном `smc_engine.ote_retest_setups`
(ОДИН калькулятор, ARCH-118 → parity live==бэктест). Читает шкаф `config/ote_setups.yaml`,
для каждого enabled-сетапа находит активную OTE-зону и генерит сигнал входа.

Поток: scan_loop → generate(sym, dfs) → [OTESignal] → trade_simulator (VST).
Шкаф: data/research/2026-06-04--ote-cube/SETUP_LIBRARY.md.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import yaml

from core.smc.smc_engine import ote_retest_setups

_CONFIG = Path(__file__).resolve().parents[2] / "config" / "ote_setups.yaml"


@dataclass
class OTESignal:
    """Сигнал входа из шкафа — готов к регистрации VST-сделки."""
    symbol: str
    setup_id: str            # напр. "4h_5m_pull"
    tier: int                # 1/2/3
    weight: float            # tier_weight
    type: str                # pull / cont
    direction: str           # long / short
    htf: str                 # масштаб зоны (4h)
    ltf: str                 # масштаб входа (5m)
    entry: float
    sl: float                # LTF-структура (риск ×10)
    tp1: float               # +1R (частичный 50%)
    tp_runner: float         # цель runner (pull→OTE-зона, cont→HTF-target)
    risk: float
    confluence: int          # OB/FVG в зоне (из эталона)
    ote_zone: tuple          # (lo, hi)
    entry_ts: object         # время ретеста
    meta: dict = field(default_factory=dict)


class OTESignalGenerator:
    """Читает шкаф → генерит OTE-сигналы по enabled-сетапам."""

    def __init__(self, config_path: Path | str = _CONFIG, recent_bars: int = 3):
        self.config_path = Path(config_path)
        self.recent_bars = recent_bars      # «свежесть» ретеста: вход в последних N барах LTF
        self._load()

    def _load(self) -> None:
        cfg = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        self.execution = cfg.get("execution", {})
        self.tier_weights = cfg.get("tier_weights", {1: 1.0, 2: 0.6, 3: 0.3})
        self.ds_patterns = cfg.get("ds_patterns", {})
        self.setups: List[dict] = []
        for tname, tnum in (("tier1", 1), ("tier2", 2), ("tier3", 3)):
            for s in cfg.get(tname, []):
                if s.get("enabled"):
                    s = dict(s); s["tier"] = tnum
                    self.setups.append(s)

    def reload(self) -> None:
        """Перечитать шкаф (поменял enabled/веса — без рестарта)."""
        self._load()

    # ── ядро ────────────────────────────────────────────────────────────────
    def generate(self, symbol: str, dfs: Dict[str, "pd.DataFrame"]) -> List[OTESignal]:
        """dfs: {'5m': df, '15m': df, '1h': df, '4h': df, '1d': df}. Возвращает свежие сигналы."""
        out: List[OTESignal] = []
        for st in self.setups:
            df_htf = dfs.get(st["htf"])
            df_ltf = dfs.get(st["ltf"])
            if df_htf is None or df_ltf is None or len(df_htf) < 50 or len(df_ltf) < 50:
                continue
            # ЭТАЛОН — один калькулятор (parity с бэктестом by design)
            htf_setups = ote_retest_setups(df_htf, only_choch=False)
            if not htf_setups:
                continue
            sig = self._emit(symbol, st, htf_setups, df_ltf)
            if sig is not None:
                out.append(sig)
        return out

    def _emit(self, symbol, st, htf_setups, df_ltf) -> Optional[OTESignal]:
        """Берём последнюю свежую HTF-зону, генерим сигнал нужного типа."""
        import numpy as np
        h = htf_setups[-1]                      # последний сетап = самая свежая зона
        ote_lo, ote_hi = h["ote"]
        htf_dir = h["direction"]                # тренд импульса HTF
        stype = st["type"]                      # pull / cont
        ltf_close = df_ltf["close"].values
        ltf_low = df_ltf["low"].values
        ltf_high = df_ltf["high"].values
        price = ltf_close[-1]

        # цена сейчас должна быть В OTE-зоне (ретест идёт)
        if not (ote_lo <= price <= ote_hi):
            return None

        if stype == "cont":
            direction = htf_dir                 # вход ПО тренду
            tp_runner = h["to"][1]              # HTF-target (далёкая цель)
        else:  # pull — откат, контр-тренд
            direction = "short" if htf_dir == "long" else "long"
            tp_runner = (ote_lo + ote_hi) / 2.0  # OTE-зона (близкая цель)

        entry = price
        # SL = LTF-структура (компактный): недавний экстремум LTF
        lb = min(10, len(df_ltf) - 1)
        sl = ltf_low[-lb:].min() if direction == "long" else ltf_high[-lb:].max()
        risk = abs(entry - sl)
        if risk <= 0:
            return None
        tp1 = entry + risk if direction == "long" else entry - risk
        # валидность цели runner относительно входа
        if (direction == "long" and tp_runner <= entry) or (direction == "short" and tp_runner >= entry):
            tp_runner = tp1                     # fallback: хотя бы 1R

        return OTESignal(
            symbol=symbol, setup_id=st["id"], tier=st["tier"],
            weight=self.tier_weights.get(st["tier"], 0.3),
            type=stype, direction=direction, htf=st["htf"], ltf=st["ltf"],
            entry=round(float(entry), 8), sl=round(float(sl), 8),
            tp1=round(float(tp1), 8), tp_runner=round(float(tp_runner), 8),
            risk=round(float(risk), 8), confluence=h.get("confluence", 0),
            ote_zone=(round(ote_lo, 8), round(ote_hi, 8)),
            entry_ts=df_ltf.index[-1],
            meta={"htf_dir": htf_dir, "avgR_backtest": st.get("avgR"), "wr_backtest": st.get("wr")},
        )


if __name__ == "__main__":
    # smoke-тест на parquet (исторические данные как «живые»)
    import sys, pandas as pd
    sys.stdout.reconfigure(encoding="utf-8")
    gen = OTESignalGenerator()
    print(f"Загружено enabled-сетапов: {len(gen.setups)}")
    sym = "BTCUSDT"
    dfs = {}
    for tf in ["5m", "15m", "1h"]:
        p = Path(f"data/history/{tf}/{sym}.parquet")
        if p.exists():
            dfs[tf] = pd.read_parquet(p).tail(5000)
    # 4h/1d ресемпл из 1h
    if "1h" in dfs:
        b = dfs["1h"]
        for tf, rule in [("4h", "4h"), ("1d", "1D")]:
            dfs[tf] = pd.DataFrame({
                "open": b["open"].resample(rule).first(), "high": b["high"].resample(rule).max(),
                "low": b["low"].resample(rule).min(), "close": b["close"].resample(rule).last(),
            }).dropna()
    sigs = gen.generate(sym, dfs)
    print(f"Сгенерировано сигналов на последнем баре {sym}: {len(sigs)}")
    for s in sigs:
        print(f"  [{s.setup_id} T{s.tier}] {s.direction:<5} entry={s.entry} SL={s.sl} "
              f"TP1={s.tp1} runner={s.tp_runner} risk={s.risk:.4f} confl={s.confluence}")
