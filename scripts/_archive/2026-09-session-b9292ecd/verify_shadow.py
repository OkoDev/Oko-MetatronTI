"""П.3: перепроверка сетапов тени на чистых свечах BingX v3 на момент детекции. Сравнение разметки, флагов ядра и входа."""
import json, sys
import numpy as np, pandas as pd
sys.path.insert(0, r"E:\MTF BOT\CURSOR\crypto_volume_bot")
from core.waves.bingx_klines import fetch_closed
from core.waves.wave5_core import mark_impulse, ltf_status, WaveParams

ROOT = r"E:\MTF BOT\CURSOR\crypto_volume_bot"
st = json.load(open(ROOT + r"\data\wave5_shadow\state.json", encoding="utf-8"))
P = WaveParams()
FIX_TS = pd.Timestamp("2026-09-14 05:32", tz="UTC")               # переход тени на v3
rows = []
for key, s in st.items():
    sym = s["sym"]; det = pd.Timestamp(s["detected_at"], tz="UTC")
    now_real = pd.Timestamp.utcnow()
    n4 = int((now_real - det) / pd.Timedelta(hours=4)) + 1000
    dh = fetch_closed(sym, "4h", n4, now=det)                     # только бары, закрытые к моменту детекции
    setups = mark_impulse(dh, det, P, "4h") if len(dh) >= 400 else []
    kk = key.split("|", 1)[1]
    m = next((x for x in setups if x["key"] == kk), None)
    same_side = [x for x in setups if x["side"] == s["side"]]
    rec = {"key": key, "sym": sym, "до фикса": det < FIX_TS, "детекция": s["detected_at"], "бар 4h": len(dh)}
    if m is None:
        rec["вердикт"] = "ПРИЗРАК: на чистых свечах сетапа нет" + (f" (есть другой {same_side[0]['key']})" if same_side else "")
        rows.append(rec); continue
    diffs = []
    for f, tol in (("p0", 1e-9), ("p4_target", 1e-9), ("p5", 1e-9), ("depth5", 0.02), ("w2_retr", 0.02), ("w4_retr", 0.02)):
        a, b = s.get(f), m.get(f)
        if a is None or b is None:
            continue
        rel = abs(float(a) - float(b)) / max(abs(float(b)), 1e-12) if f in ("p0", "p4_target", "p5") else abs(float(a) - float(b))
        if rel > (0.002 if f in ("p0", "p4_target", "p5") else tol):
            diffs.append(f"{f} {a} → {b}")
    for f in ("fractal", "altern", "count_ok", "core", "core_full", "side"):
        if s.get(f) != m.get(f):
            diffs.append(f"{f} {s.get(f)} → {m.get(f)}")
    # вход: LTF 15m на момент детекции
    dl = fetch_closed(sym, "15m", int((now_real - pd.Timestamp(m["top_time"])) / pd.Timedelta(minutes=15)) + 50, now=det)
    ls = ltf_status(m, dl, P) if len(dl) > 50 else {}
    cf = ls.get("cross_first"); l24 = ls.get("line24_first")
    rec.update({"разметка": "совпадает" if not diffs else "ОТЛИЧАЕТСЯ: " + "; ".join(diffs),
                "кросс v3": str(cf)[:16] if cf is not None else None, "кросс тень": str(s.get("cross_first"))[:16],
                "линия24 v3": str(l24)[:16] if l24 is not None else None, "линия24 тень": str(s.get("line24_first"))[:16],
                "вход тени": f"{s.get('entry_trigger')} {s.get('entered_at')} @ {s.get('entry_price')}"})
    trig_t = pd.Timestamp(cf) if (s.get("entry_trigger") == "cross" and cf is not None) else (pd.Timestamp(l24) if l24 is not None else None)
    if trig_t is not None:
        trig_t = trig_t.tz_localize("UTC") if trig_t.tzinfo is None else trig_t
        lag_h = (pd.Timestamp(s["entered_at"], tz="UTC") - trig_t) / pd.Timedelta(hours=1)
        rec["опоздание входа, ч"] = round(lag_h, 1)
        # цена на реальном триггере (закрытие бара триггера) против цены входа тени
        k_ = int(np.searchsorted(dl.index.values.astype("datetime64[ns]"), trig_t.tz_convert(None).to_datetime64() if trig_t.tzinfo else trig_t.to_datetime64()))
        if k_ < len(dl):
            rec["цена на триггере"] = float(dl.close.iloc[k_])
    rec["вердикт"] = ("ок" if not diffs else "разметка разошлась") + ("" if rec.get("опоздание входа, ч", 0) <= 1 else " · вход опоздал")
    rows.append(rec)
df = pd.DataFrame(rows)
pd.set_option("display.width", 300); pd.set_option("display.max_colwidth", 120)
print(df.to_string(index=False))
df.to_json(ROOT + r"\data\wave5_shadow\verify_v3.json", orient="records", force_ascii=False, indent=1, default_handler=str)
