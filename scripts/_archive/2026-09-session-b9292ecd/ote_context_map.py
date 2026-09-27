"""OTE КАК КОНТЕКСТ (Егор 21.09) — для КАЖДОЙ механики карты: где лежит цена входа внутри структурной ноги старшего ТФ
(OKO-SM `run_structure` + `current_leg`, канон `core/smc/fibonacci.ote_band`: мелкая <0.5 · 0.5–0.62 · OTE 0.62–0.79 ·
глубокая 0.79–1.0 · за пределами >1; плюс «за экстремумом» = цена дальше экстремума ноги) и совпадает ли сторона сделки
с ногой (по ноге / против ноги). Каузально: нога по ПОСЛЕДНЕМУ ЗАКРЫТОМУ бару HTF до входа. HTF = 4h и 1d.
Сделки: карта v1 (regime_map/map_trades.pkl: ядро волн, WT), impulse_fib_15m (replay), map_replays (impulse_fib 1h, choch,
rangefade ×3 — боевая конфигурация). Контроли уже в строках (Δr/Δt). python ote_context_map.py"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot"); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf
from core.smc.oko_sm_engine import run_structure
from core.smc.fibonacci import ote_band
import logging; logging.disable(logging.CRITICAL)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 400)
OUT = Path("G:/oko_lab/out/ote_context"); OUT.mkdir(parents=True, exist_ok=True)

# ---- сделки всех механик в одну таблицу: sym, mech, side, entry_t, entry_px, pnl, risk_pct, ctl_rand, ctl_time, год
A = pd.read_pickle("G:/oko_lab/out/regime_map/map_trades.pkl")[["sym", "mech", "side", "entry_t", "pnl", "risk_pct", "ctl_rand", "ctl_time", "год"]].copy(); A["entry_px"] = np.nan
B = pd.read_pickle("G:/oko_lab/out/impulse_fib_15m_replay/trades.pkl"); B = B[B.filled].copy()
B["mech"] = np.where(B["дверь"] == "EQH/EQL", "impulse_fib_15m+EQH", "impulse_fib_15m"); B = B.rename(columns={"entry": "entry_px"})[["sym", "mech", "side", "entry_t", "entry_px", "pnl", "risk_pct", "ctl_rand", "ctl_time", "год"]]
C = pd.read_pickle("G:/oko_lab/out/map_replays/trades.pkl"); C = C[C["вошла"]][["sym", "mech", "side", "entry_t", "entry_px", "pnl", "risk_pct", "ctl_rand", "ctl_time", "год"]].copy()
T = pd.concat([A, B, C], ignore_index=True); T["entry_t"] = pd.to_datetime(T.entry_t)
print("сделок:", len(T), T.mech.value_counts().to_dict())

# ---- контекст ноги HTF
def leg_context(sym, trades):
    out = {}
    m1 = load_tf(sym, "1h"); c1 = m1.close
    for tf in ("4h", "1d"):
        m = load_tf(sym, tf); dd = m.reset_index(drop=True)
        st = run_structure(dd, swing_len=50, internal_len=5, record_legs=True); legs = st.leg_history; idx = m.index.values
        rel, band, depth_l = [], [], []
        for r in trades.itertuples():
            k = int(np.searchsorted(idx, np.datetime64(r.entry_t), "right")) - 2      # последний ЗАКРЫТЫЙ бар HTF до входа
            px = r.entry_px
            if not (px == px):
                j = int(np.searchsorted(c1.index.values, np.datetime64(r.entry_t), "right")) - 1; px = float(c1.values[j]) if j >= 0 else np.nan
            leg = legs[k] if 0 <= k < len(legs) else None
            if not leg or not (px == px):
                rel.append("нет ноги"); band.append("нет ноги"); depth_l.append(np.nan); continue
            o, x = float(leg["origin"]), float(leg["extreme"]); L = abs(x - o)
            if L <= 0:
                rel.append("нет ноги"); band.append("нет ноги"); depth_l.append(np.nan); continue
            d = (x - px) / L if leg["trend"] == "long" else (px - x) / L
            rel.append("по ноге" if (leg["trend"] == "long") == (r.side == "LONG") else "против ноги")
            band.append("за экстремумом" if d < 0 else ote_band(d)); depth_l.append(d)
        out[f"rel_{tf}"] = rel; out[f"band_{tf}"] = band; out[f"depth_{tf}"] = depth_l
    return pd.DataFrame(out, index=trades.index)

parts = []
for i, (sym, g) in enumerate(T.groupby("sym")):
    try:
        parts.append(leg_context(sym, g))
    except Exception as e:
        print("  ", sym, "ошибка", type(e).__name__, str(e)[:60])
    if i % 50 == 0:
        print(f"  {i} монет", flush=True)
X = pd.concat(parts); T = T.join(X); T.to_pickle(OUT / "trades_ote_context.pkl")

def agg(g):
    return g.agg(n=("pnl", "size"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"), мед=("pnl", "median"),
                 ctl_r=("ctl_rand", "mean"), ctl_t=("ctl_time", "mean")).assign(Δr=lambda x: (x["ср"] - x.ctl_r).round(2), Δt=lambda x: (x["ср"] - x.ctl_t).round(2)).round(2)

ORDER = ["за экстремумом", "мелкая (<0.5)", "мелкая 0.5–0.62", "OTE 0.62–0.79", "глубокая 0.79–1.0", "за пределами ноги (>1)", "нет ноги"]
for tf in ("4h", "1d"):
    print(f"\n\n################ КОНТЕКСТ НОГИ {tf}: механика × сторона × (по ноге / против) × корзина отката")
    T[f"band_{tf}"] = pd.Categorical(T[f"band_{tf}"], ORDER, ordered=True)
    g = agg(T.groupby(["mech", "side", f"rel_{tf}", f"band_{tf}"], observed=True))
    print(g[g.n >= 30].to_string())
    print(f"\n=== {tf}: по ноге / против ноги (все корзины)"); print(agg(T.groupby(["mech", "side", f"rel_{tf}"], observed=True)).to_string())
    print(f"\n=== {tf}: только OTE 0.62–0.79 по ноге vs всё остальное — по годам (ср)")
    T["ote_ctx"] = np.where((T[f"rel_{tf}"] == "по ноге") & (T[f"band_{tf}"] == "OTE 0.62–0.79"), "в OTE по ноге", "остальное")
    print(T.groupby(["mech", "side", "ote_ctx", "год"]).pnl.mean().round(2).unstack("год").to_string())
