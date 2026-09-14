"""🌊 Волновой разбор монеты (core.waves.wave_analyst): 1D нога · 4h счёт/диагональ · слом младшего ТФ · сценарии A/B.
python scripts/wave_analyst.py --syms SOLV,RECALL [--ltf 3m] → data/wave_analyst/<SYM>_<UTC>.png/.json
Данные — BingX swap v3 klines (core.waves.bingx_klines), только закрытые бары."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from core.waves.wave_analyst import report_for

OUT = ROOT / "data" / "wave_analyst"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--syms", required=True)
    ap.add_argument("--ltf", default="3m")
    a = ap.parse_args()
    for s in a.syms.split(","):
        r = report_for(s, a.ltf, OUT)
        print(f"\n=== {r['sym']} → {OUT / (r['png'] or r['json'])}")
        print("\n".join(r["text"]))
        for sc in r["scenarios"]:
            print(f"  [{sc['name']}] " + " · ".join(f"{n} {v:.6g}" for n, v in sc["targets"]) + f" | отмена: {sc['invalid']}")


if __name__ == "__main__":
    main()
