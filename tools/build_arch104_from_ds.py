"""Поток 2 (ARCH-128): DS-315/316 намайненные паттерны → arch104_patterns.yaml.

Конвертирует walkforward результаты DS (на ЭТАЛОННЫХ признаках, ARCH-118) в production-реестр
arch104. Отбор строгий: mht+stable + avgR/n пороги + дедуп + баланс + лимит. Превью перед заливкой.

Формат паттерна (loader core/confirmations/arch104_patterns.py):
  ID: {direction, anchor_factors[], weight, test_n/avgR/WR, detection_tf, fallback_tp_r, enabled}
match: anchor_factors ⊆ active_flags (на detection_tf).

Запуск:
  python tools/build_arch104_from_ds.py              # превью (не пишет)
  python tools/build_arch104_from_ds.py --write      # залить в config/arch104_patterns.yaml
"""
from __future__ import annotations
import sys, argparse
from pathlib import Path
import pandas as pd
import yaml

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
DS315 = ROOT / "data/research/2026-06-03--ds315/walkforward_full_mht.csv"
DS316 = ROOT / "data/research/2026-06-03--ds316/nested_ltf_15m_results.csv"
OUT = ROOT / "config/arch104_patterns.yaml"

# ── пороги отбора ───────────────────────────────────────────────────────────
MIN_AVGR = 0.8          # test_avgR (качество)
MIN_N = 30              # test_n (статзначимость)
LIMIT = 200             # квоты по src×direction (50 каждая: HTF/LTF × LONG/SHORT)
_TF_ORDER = {"5m": 0, "15m": 1, "1h": 2, "4h": 3, "1d": 4, "1w": 5}


def _factors(pattern: str) -> list[str]:
    return [f.strip() for f in str(pattern).split("+") if f.strip()]


def _detection_tf(factors: list[str]) -> str:
    """detection_tf = МИНИМАЛЬНЫЙ TF среди факторов (где live срабатывает раньше всего).
    Суффиксы смешанного регистра (_1d / _1D / _1W). Cap на 4h — observer сканит
    только 5m/15m/1h/4h (не 1d), 1d-only паттерны проверяются на 4h (reindex 1d→4h)."""
    tfs = []
    for f in factors:
        fl = f.lower()
        for tf in _TF_ORDER:
            if fl.endswith("_" + tf):
                tfs.append(tf); break
    if not tfs:
        return "1h"
    mn = min(tfs, key=lambda t: _TF_ORDER[t])
    return mn if _TF_ORDER[mn] <= _TF_ORDER["4h"] else "4h"   # observer max detection = 4h


def _weight(avg_r: float) -> int:
    return int(max(10, min(19, round(10 + avg_r * 5))))   # avgR 0.8→14, 1.8→19


def _slug(direction: str, factors: list[str], i: int) -> str:
    core = "_".join(f.replace("_", "") [:6] for f in factors[:3])
    return f"DS_{direction[0]}{i:03d}_{core}"[:48]


def load_ds315() -> pd.DataFrame:
    """HTF паттерны (1h/4h/1d), walkforward+MHT-валидированы."""
    df = pd.read_csv(DS315)
    df = df[(df["mht_passed"] == True) & (df["stable"] == True)]
    df = df[(df["test_avgR"] >= MIN_AVGR) & (df["test_n"] >= MIN_N)]
    df["factors"] = df["pattern"].map(_factors)
    df["nfac"] = df["factors"].map(len)
    df = df[df["nfac"] >= 2]
    df["src"] = "DS-315"
    return df[["pattern", "direction", "test_avgR", "test_n", "test_WR", "composite_score", "factors", "nfac", "src"]]


def load_ds316() -> pd.DataFrame:
    """LTF 15m nested паттерны. НЕ walkforward (простой бэктест) → пороги СТРОЖЕ
    (avgR>=1.0, n>=40) для защиты от оверфита. detection_tf=15m → частые срабатывания."""
    df = pd.read_csv(DS316)
    df = df.rename(columns={"avgR": "test_avgR", "n": "test_n", "WR": "test_WR", "score": "composite_score"})
    df = df[(df["test_avgR"] >= 1.0) & (df["test_n"] >= 40)]   # строже: нет walkforward-валидации
    df["factors"] = df["pattern"].map(_factors)
    df["nfac"] = df["factors"].map(len)
    df = df[df["nfac"] >= 2]
    df["src"] = "DS-316"
    return df[["pattern", "direction", "test_avgR", "test_n", "test_WR", "composite_score", "factors", "nfac", "src"]]


def dedup(df: pd.DataFrame) -> pd.DataFrame:
    """Убрать надмножества: если набор факторов A ⊃ B и avgR(A)<=avgR(B)+0.1 → A лишний
    (B проще и не хуже). Оставляем сильнейшие минимальные паттерны."""
    df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)
    kept = []
    kept_sets = []
    for _, r in df.iterrows():
        fs = frozenset(r["factors"])
        # пропускаем если уже есть подмножество с не худшим avgR
        red = any(ks < fs and r["test_avgR"] <= ka + 0.1 for ks, ka in kept_sets)
        if red:
            continue
        kept.append(r); kept_sets.append((fs, r["test_avgR"]))
    return pd.DataFrame(kept)


def select(df: pd.DataFrame) -> pd.DataFrame:
    """Квоты по src×direction: HTF(DS-315) + LTF(DS-316), баланс LONG/SHORT.
    LTF даёт частые срабатывания (15m), HTF — редкие но сильные конфлюенции."""
    out = []
    for src in ("DS-315", "DS-316"):
        for d in ("LONG", "SHORT"):
            sub = df[(df["src"] == src) & (df["direction"] == d)].nlargest(LIMIT // 4, "composite_score")
            out.append(sub)
    return pd.concat(out).reset_index(drop=True)


def to_patterns(df: pd.DataFrame) -> dict:
    pats = {}
    counters = {"LONG": 0, "SHORT": 0}
    for _, r in df.iterrows():
        d = r["direction"]; counters[d] += 1
        factors = r["factors"]
        pid = _slug(d, factors, counters[d])
        pats[pid] = {
            "enabled": True,
            "direction": d,
            "anchor_factors": list(factors),
            "detection_tf": _detection_tf(factors),
            "weight": _weight(float(r["test_avgR"])),
            "test_n": int(r["test_n"]),
            "test_avgR": round(float(r["test_avgR"]), 3),
            "test_WR": round(float(r["test_WR"]), 1),
            "fallback_tp_r": 2.0,
            "tp_strategy": "no_trail",
            "time_exit_hours": 24,
            "source": str(r["src"]) + (" walkforward_mht" if r["src"] == "DS-315" else " LTF-15m nested"),
        }
    return pats


def _combinator_schema() -> set:
    """Полная схема combinator-флагов (все TF). Паттерн валиден ⟺ его факторы ⊆ схемы
    (ARCH-118 один калькулятор: не заливать флаги, которых live combinator не генерит)."""
    import sys as _s
    _s.path.insert(0, str(ROOT / "tools" / "pattern_mining"))
    import ccxt, pandas as _pd, combinator_v2 as cb
    ex = ccxt.bingx(); schema = set()
    for tf in ("5m", "15m", "1h", "4h", "1d"):
        o = ex.fetch_ohlcv("BTC/USDT:USDT", tf if tf != "1d" else "4h", limit=400)
        df = _pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = _pd.to_datetime(df["ts"], unit="ms", utc=True); df = df.set_index("ts")
        try: schema |= set(cb.compute_flags(df, tf, include_pivots=True).columns)
        except Exception: schema |= set(cb.compute_flags(df, tf).columns)
    return schema


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    schema = _combinator_schema()
    print(f"combinator schema: {len(schema)} флагов")
    d315 = load_ds315(); d316 = load_ds316()
    for _d in (d315, d316):                                # фильтр несовместимых флагов
        _d.drop(_d[~_d["factors"].map(lambda fs: all(f in schema for f in fs))].index, inplace=True)
    print(f"DS-315 HTF (mht+stable, avgR>={MIN_AVGR}, n>={MIN_N}): {len(d315)}")
    print(f"DS-316 LTF-15m (avgR>=1.0, n>=40, строже — нет walkforward): {len(d316)}")
    df = pd.concat([d315, d316]).reset_index(drop=True)
    df = dedup(df)
    print(f"после дедупа надмножеств: {len(df)}")
    df = select(df)
    print(f"после отбора топ-{LIMIT} (квоты HTF/LTF × L/S): {len(df)} "
          f"(LONG={sum(df['direction']=='LONG')} SHORT={sum(df['direction']=='SHORT')} | "
          f"HTF={sum(df['src']=='DS-315')} LTF={sum(df['src']=='DS-316')})")
    pats = to_patterns(df)

    # превью
    print("\nТОП-8 паттернов (превью):")
    for pid, p in list(pats.items())[:8]:
        print(f"  {pid} [{p['direction']}] tf={p['detection_tf']} w={p['weight']} "
              f"avgR={p['test_avgR']} WR={p['test_WR']} n={p['test_n']} | {'+'.join(p['anchor_factors'])[:55]}")
    # детекшн tf распределение
    from collections import Counter
    tfd = Counter(p["detection_tf"] for p in pats.values())
    print(f"\ndetection_tf распределение: {dict(tfd)}")
    print(f"avgR диапазон: {min(p['test_avgR'] for p in pats.values()):.2f} .. {max(p['test_avgR'] for p in pats.values()):.2f}")

    if args.write:
        doc = {
            "version": 2,
            "generated": "2026-06-04",
            "source": "DS-315/316 walkforward_mht на эталонных признаках (ARCH-118 один калькулятор)",
            "note": "Поток 2 ARCH-128: заменил старый реестр 2026-05-20 (устаревший combinator). "
                    f"Отбор: mht+stable, avgR>={MIN_AVGR}, n>={MIN_N}, дедуп, топ-{LIMIT} баланс.",
            "patterns": pats,
        }
        OUT.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
        print(f"\n✅ ЗАЛИТО: {OUT} ({len(pats)} паттернов)")
    else:
        print(f"\n(превью — для заливки добавь --write; старый реестр уже в config/archive/)")


if __name__ == "__main__":
    main()
