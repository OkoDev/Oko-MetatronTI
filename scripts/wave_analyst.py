"""🌊 Волновой разбор монеты (core.waves.wave_analyst): 1D нога · 4h счёт/диагональ · слом младшего ТФ · сценарии A/B.
python scripts/wave_analyst.py --syms SOLV,RECALL [--ltf 15m] → data/wave_analyst/<SYM>_<UTC>.png/.json/.md
Данные — BingX swap через ccxt без ключей, только закрытые бары (тот же fetch, что у тени)."""
import argparse, json, sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import ccxt
from wave5_shadow import fetch, js                      # переиспользуем загрузчик и сериализацию тени
from core.waves.wave_analyst import analyze, render

OUT = ROOT / "data" / "wave_analyst"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--syms", required=True)
    ap.add_argument("--ltf", default="3m")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    ex = ccxt.bingx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    for s in a.syms.split(","):
        sym = s if "/" in s else f"{s}/USDT"
        dh = fetch(ex, sym, "4h", 1500)
        dl = fetch(ex, sym, a.ltf, {"1m": 12000, "3m": 5000, "5m": 3000, "15m": 1500}.get(a.ltf, 1500))   # ≈8-10 суток: пятая + слом + откат
        rep = analyze(sym.split("/")[0], dh, dl, a.ltf)
        stamp = f"{pd.Timestamp.utcnow():%Y%m%d_%H%M}"; base = OUT / f"{sym.split('/')[0]}_{stamp}"
        if rep["structure"] is not None:
            render(rep, dh, dl, base.with_suffix(".png"))
        (base.with_suffix(".md")).write_text("\n\n".join(rep["text"]) + "\n\n" + "\n".join(
            f"### {sc['name']}\n{sc['why']}\n" + "\n".join(f"- {n}: {v:.6g}" for n, v in sc["targets"]) + f"\n- отмена: {sc['invalid']}"
            for sc in rep["scenarios"]), encoding="utf-8")
        clean = {k: v for k, v in rep.items() if k != "structure"}
        (base.with_suffix(".json")).write_text(json.dumps(clean, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"\n=== {sym} → {base}.png")
        print("\n".join(rep["text"]))
        for sc in rep["scenarios"]:
            print(f"  [{sc['name']}] " + " · ".join(f"{n} {v:.6g}" for n, v in sc["targets"]) + f" | отмена: {sc['invalid']}")


if __name__ == "__main__":
    main()
