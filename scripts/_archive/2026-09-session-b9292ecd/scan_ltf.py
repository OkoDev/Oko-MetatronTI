"""Есть ли сетапы ядра на младших ТФ ПРЯМО СЕЙЧАС (Егор 16.09: «есть сетапы на 1h сейчас? или на ещё более младших тф?»).
Тот же детектор, что в тени и бэктесте (core.waves.mark_impulse), только HTF = 1h/15m/5m вместо 4h.
Живые закрытые бары BingX (core.waves.bingx_klines), вселенная — как у тени (swap USDT, оборот ≥ min_vol).
ВАЖНО: правила входа/стопа/цели ядра мерились на 4h. Здесь только РАЗМЕТКА, статистики по этим ТФ у нас нет.
Запуск: python scan_ltf.py [ТФ через запятую] [сколько монет]"""
import sys, warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import ccxt
from core.waves import mark_impulse, WaveParams
from core.waves.wave5_core import TF_MIN
from core.waves.bingx_klines import fetch_closed

NOW = pd.Timestamp.utcnow()
P = WaveParams()


def _utc(t):
    """Время сетапа приходит и наивным, и с зоной — приводим к UTC один раз (иначе pd.Timestamp(t, tz=…) роняет ValueError)."""
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


NOW_UTC = _utc(NOW)
FRESH_BARS = 24          # «сейчас» = вершина пятой не старше 24 баров своего ТФ (на 4h это наши 96 ч окна входа)
MIN_VOL = 2e6


def uni(n):
    """Ликвидные swap-пары BingX. Ключи рынков ('BTC/USDT:USDT') и тикеров ('BTC/USDT') у ccxt.bingx не совпадают —
    оборот ищем по базовому активу, иначе список выходит пустым."""
    ex = ccxt.bingx({"enableRateLimit": True})
    mk = ex.load_markets(); tk = ex.fetch_tickers()
    vol = {}
    for s, t in tk.items():
        vol[s.split("/")[0].split(":")[0]] = t.get("quoteVolume") or 0
    liq = sorted(((m["base"], vol.get(m["base"], 0)) for s, m in mk.items()
                  if m.get("swap") and m.get("quote") == "USDT" and m.get("active")), key=lambda x: -x[1])
    print(f"обороты BingX: топ {liq[0][1]:,.0f} · пар {len(liq)} · берём {'все' if n <= 0 else 'топ-' + str(n)}", flush=True)
    return [f"{b}/USDT" for b, v in liq][:n] if n > 0 else [f"{b}/USDT" for b, v in liq]


def scan(args):
    sym, tf = args
    try:
        dh = fetch_closed(sym, tf, 1000, now=NOW)
        if dh is None or len(dh) < 6 * P.sw + 50:
            return []
        # lookback обязателен: ядро размечает сетап на баре ПОДТВЕРЖДЕНИЯ, на текущем баре его уже не видно
        # (проверено на SOLV/RECALL: без lookback — 0, с lookback=24 — ровно те сетапы, что держит тень)
        setups = mark_impulse(dh, NOW, P, tf, lookback=FRESH_BARS)
        px = float(dh.close.iloc[-1])
        out = []
        for s in setups:
            age_bars = (NOW_UTC - _utc(s["top_time"])) / pd.Timedelta(minutes=TF_MIN[tf])
            if age_bars > FRESH_BARS:
                continue
            short = s["side"] == "SHORT"
            risk = abs(s["p5"] - px) / px * 100
            tgt = abs(s["p4_target"] - px) / px * 100
            out.append({"sym": sym.split("/")[0], "tf": tf, "side": s["side"], "возр_баров": round(age_bars, 1),
                        "цена": px, "стоп_p5": s["p5"], "цель_w4": s["p4_target"], "риск%": round(risk, 2),
                        "потенц%": round(tgt, 2), "RR": round(tgt / risk, 2) if risk > 0 else np.nan,
                        "ядро": s.get("core_full") or s.get("core"), "фрактал": s.get("fractal"),
                        "depth5": round(float(s.get("depth5") or 0), 2), "импульс%": round(float(s.get("imp_pct") or 0), 1),
                        "вершина": pd.Timestamp(s["top_time"]).strftime("%d.%m %H:%M"),
                        "в_пользу": (px < s["p5"]) if short else (px > s["p5"])})
        return out
    except Exception as e:
        print(f"  ! {sym} {tf}: {type(e).__name__}: {e}", flush=True)   # молча глушить нельзя: так и потеряли все сетапы
        return []


if __name__ == "__main__":
    tfs = (sys.argv[1] if len(sys.argv) > 1 else "1h,15m,5m").split(",")
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    syms = uni(n)
    print(f"вселенная BingX: {len(syms)} монет (оборот ≥ ${MIN_VOL:,.0f}) · ТФ: {', '.join(tfs)} · {NOW:%d.%m %H:%M} UTC", flush=True)
    jobs = [(s, tf) for tf in tfs for s in syms]
    rows = []
    with ThreadPoolExecutor(int(sys.argv[3]) if len(sys.argv) > 3 else 6) as ex:   # не мешаем лимитам живого бота
        for r in ex.map(scan, jobs):
            rows.extend(r)
    d = pd.DataFrame(rows)
    if d.empty:
        print("сетапов нет ни на одном ТФ"); sys.exit()
    print(f"\nвсего свежих сетапов (вершина ≤{FRESH_BARS} баров назад): {len(d)}")
    print(d.groupby(["tf", "side"]).size().unstack(fill_value=0).to_string(), "\n")
    for tf in tfs:
        g = d[d.tf == tf].sort_values("возр_баров")
        if g.empty:
            print(f"--- {tf}: пусто\n"); continue
        print(f"--- {tf}: {len(g)} сетапов")
        cols = ["sym", "side", "вершина", "возр_баров", "риск%", "потенц%", "RR", "ядро", "фрактал", "depth5", "импульс%", "в_пользу"]
        print(g[cols].to_string(index=False), "\n")
    d.to_csv(Path(__file__).with_name("scan_ltf.csv"), index=False, encoding="utf-8-sig")
    print("таблица: scan_ltf.csv")
