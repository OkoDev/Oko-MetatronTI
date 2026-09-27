"""ЖИВАЯ ПРОВЕРКА СЕТАПОВ ПО НАШЕЙ СВЯЗКЕ (Егор 16.09: «проверь сетапы по тени сейчас! интересная ситуация на рынке»).
Свежие сетапы 4h с живых баров BingX прогоняются через то, что измерено сегодня:
отбор ядро fc · импульс 15-50% · вход по первому слому SWING-структуры на 15m · риск на входе · массовость дня.
Запуск: python live_check.py [сколько монет, 0 = все]
"""
import sys, warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import scan_ltf as S
from core.waves.wave5_core import WaveParams, mark_impulse
from core.smc.oko_sm_engine import run_structure
from core.waves.bingx_klines import fetch_closed

P = WaveParams()
FRESH = 24          # вершина не старше 24 баров 4h


def one(sym):
    try:
        dh = fetch_closed(sym, "4h", 1000, now=S.NOW)
        if dh is None or len(dh) < 6 * P.sw + 50:
            return []
        setups = mark_impulse(dh, S.NOW, P, "4h", lookback=FRESH)
        out = []
        for s in setups:
            t5 = S._utc(s["top_time"])
            age = (S.NOW_UTC - t5) / pd.Timedelta(hours=4)
            if age > FRESH:
                continue
            long_ = s["side"] == "LONG"
            rec = {"sym": sym.split("/")[0], "side": s["side"], "вершина": t5.strftime("%d.%m %H:%M"),
                   "возр_бар": round(age, 1), "ядро": bool(s["core_full"]), "фрактал": bool(s["fractal"]),
                   "импульс%": round(float(s["imp_pct"]), 1), "канал": round(float(s["depth5"]), 2),
                   "p5": float(s["p5"]), "цель": float(s["p4_target"]), "слом15m": "—"}
            w = fetch_closed(sym, "15m", 1000, now=S.NOW)
            if w is not None and len(w) > 300:
                x = w.reset_index(drop=True)
                st = run_structure(x[["open", "high", "low", "close"]], swing_len=15, internal_len=4)
                lt = w.index.values
                j5 = int(np.searchsorted(lt, np.datetime64(t5.tz_localize(None))))
                ev = [e for e in st.events if e.kind == "CHoCH" and not e.internal and e.bull == long_ and e.i > j5]
                px = float(x.close.values[-1]); rec["цена"] = px
                if ev:
                    j = ev[0].i
                    ext = float(x.low.values[j5:j + 1].min()) if long_ else float(x.high.values[j5:j + 1].max())
                    p5a = min(float(s["p5"]), ext) if long_ else max(float(s["p5"]), ext)
                    sl = p5a * (1 - P.buf) if long_ else p5a * (1 + P.buf)
                    e = float(x.open.values[j + 1]) if j + 1 < len(x) else px
                    rec.update({"слом15m": pd.Timestamp(lt[j]).strftime("%d.%m %H:%M"), "вход": e, "стоп": sl,
                                "риск%": round(abs(e - sl) / e * 100, 2),
                                "жив": bool((px > sl) if long_ else (px < sl)),
                                "до цели%": round(abs(float(s["p4_target"]) - px) / px * 100, 2)})
                else:
                    rec.update({"риск%": round(abs(px - float(s["p5"])) / px * 100, 2),
                                "до цели%": round(abs(float(s["p4_target"]) - px) / px * 100, 2)})
            out.append(rec)
        return out
    except Exception:
        return []


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    syms = [s for s in S.uni(n) if not s.split("/")[0].startswith("NC")]      # без синтетики BingX
    print(f"монет в скане: {len(syms)} · {S.NOW:%d.%m %H:%M} UTC", flush=True)
    rows = []
    with ThreadPoolExecutor(8) as ex:
        for r in ex.map(one, syms):
            rows.extend(r)
    if not rows:
        print("сетапов нет"); sys.exit()
    d = pd.DataFrame(rows)
    d["день"] = pd.to_datetime(d["вершина"] + " 2026", format="%d.%m %H:%M %Y").dt.floor("D")
    масс = d.groupby("день").size()
    print(f"\nВСЕГО свежих сетапов: {len(d)} · LONG {int((d.side=='LONG').sum())} / SHORT {int((d.side=='SHORT').sum())}")
    print("массовость по дням (наш режим «день ≥11 сигналов»):")
    for day, k in масс.items():
        print(f"   {day:%d.%m}: {k} сетапов {'← МАССОВЫЙ ДЕНЬ' if k >= 11 else ''}")
    sel = d[d["ядро"] & d["импульс%"].between(15, 50)]
    print(f"\n--- прошли отбор (ядро fc + импульс 15-50%): {len(sel)}")
    cols = [c for c in ("sym", "side", "вершина", "возр_бар", "импульс%", "канал", "цена", "слом15m",
                        "вход", "стоп", "риск%", "до цели%", "жив") if c in sel.columns]
    if len(sel):
        print(sel.sort_values("возр_бар")[cols].to_string(index=False))
    print(f"\n--- все свежие лонги без отбора ({int((d.side=='LONG').sum())}):")
    print(d[d.side == "LONG"].sort_values("возр_бар")[cols].head(20).to_string(index=False))
    d.to_csv(Path(__file__).with_name("live_check.csv"), index=False, encoding="utf-8-sig")
