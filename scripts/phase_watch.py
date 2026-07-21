# -*- coding: utf-8 -*-
"""PHASE-WATCH — shadow-логгер Сферы Фазы (шаг 5, 21.07). НЕ торгует.

Каждый прогон: диагностирует МАКРО-фазу (rev_watch-агрегаты + BTC-структура + USDT.D) и
ПЕР-ПАРА фазу мажоров → пишет в phase_state (subscriptions.db) для форвард-скоринга (шаг 4)
+ TG-алерт при СМЕНЕ макро-фазы (не спам). Егор сверяет вердикт с ГЛАЗОМ 2-3 недели.

Лёгкий (интернет Егора чувствителен): макро дёшев, пер-пара только мажоры (~12×3 klines).
pm2 cron: каждые 30 мин. Тест: python scripts/phase_watch.py
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import json
import sqlite3
import time
import urllib.request

import pandas as pd

from core.context.phase_sphere import diagnose_macro, diagnose_pair
from core.smc.ote_matrix import structure_trend, reversal_state
from core.signals.usdtd_regime import get_usdtd_risk_off

DB = "subscriptions.db"
RADAR_DB = "oko_feed/external_data.db"
MAJORS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "SUI", "TON", "TRX"]


def _kl(sym, tf, lim):
    try:
        req = urllib.request.Request(
            f"https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol={sym}-USDT"
            f"&interval={tf}&limit={lim}", headers={"User-Agent": "M"})
        d = json.load(urllib.request.urlopen(req, timeout=12)).get("data", [])
        df = pd.DataFrame([(int(k["time"]), float(k["open"]), float(k["high"]), float(k["low"]),
                            float(k["close"])) for k in d],
                          columns=["time", "open", "high", "low", "close"]).sort_values("time").reset_index(drop=True)
        return df if len(df) >= 60 else None
    except Exception:
        return None


def _ensure(c):
    c.execute("""CREATE TABLE IF NOT EXISTS phase_state(
        ts INTEGER, level TEXT, symbol TEXT, phase TEXT, side TEXT, strategy_class TEXT,
        concordance TEXT, confidence REAL, detail TEXT)""")
    c.commit()


def main():
    now = int(time.time())
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    _ensure(c)
    e = sqlite3.connect(RADAR_DB)

    # ── МАКРО ──
    rows = e.execute("SELECT quadrant, funding FROM radar_state WHERE ts>?", (now - 900,)).fetchall()
    quads = [r[0] for r in rows if r[0]]
    pdn = 100.0 * sum(1 for q in quads if q == "PDN+OIUP") / len(quads) if quads else None
    funds = sorted(r[1] for r in rows if r[1] is not None)
    medf = funds[len(funds) // 2] * 100 if funds else None
    btc4 = _kl("BTC", "4h", 200)
    btc_trend = structure_trend(btc4).get("trend") if btc4 is not None else None
    risk_off = get_usdtd_risk_off()
    macro = diagnose_macro(pdn, medf, btc_trend, risk_off)
    c.execute("INSERT INTO phase_state VALUES(?,?,?,?,?,?,?,?,?)",
              (now, "macro", "MARKET", macro.phase, macro.bias, None, None, macro.confidence, macro.detail))

    # TG при СМЕНЕ макро-фазы
    prev = c.execute("SELECT phase FROM phase_state WHERE level='macro' AND ts<? ORDER BY ts DESC LIMIT 1",
                     (now,)).fetchone()
    if prev is None or prev["phase"] != macro.phase:
        try:
            from oko_feed.alerts import send_tg
            send_tg(f"🧭 <b>ФАЗА РЫНКА сменилась:</b> {prev['phase'] if prev else '—'} → <b>{macro.phase}</b>\n"
                    f"bias={macro.bias or '—'} veto={macro.veto or '—'} (conf {macro.confidence:.0%})\n"
                    f"{macro.detail}\n\n<i>shadow — сверь с глазом</i>\n#SYSTEM #PHASE", channel="system")
        except Exception as _e:
            print(f"[PHASE] TG: {_e}")
    print(f"[PHASE] МАКРО: {macro.phase} bias={macro.bias} (%PDN+OIUP={pdn} funding={medf} BTC={btc_trend} risk_off={risk_off})")

    # ── ПЕР-ПАРА (мажоры) ──
    for base in MAJORS:
        d4 = _kl(base, "4h", 200); d1 = _kl(base, "1h", 300); d15 = _kl(base, "15m", 300)
        if d4 is None or d1 is None or d15 is None:
            continue
        st = structure_trend(d4)
        rev = reversal_state({"4h": d4, "1h": d1, "15m": d15})
        q = e.execute("SELECT quadrant FROM radar_state WHERE symbol=? ORDER BY ts DESC LIMIT 1", (base,)).fetchone()
        px = float(d15["close"].iloc[-1])
        pp = diagnose_pair(st, rev, q[0] if q else None, None, px)
        c.execute("INSERT INTO phase_state VALUES(?,?,?,?,?,?,?,?,?)",
                  (now, "pair", base, pp.phase, pp.side, pp.strategy_class,
                   str(pp.concordance), pp.confidence, pp.detail))
        if pp.phase != "CHOP":
            print(f"  {base:6} {pp.phase:12} {pp.side or '—':5} {pp.strategy_class or '—':8} conf={pp.confidence:.1f}")
        time.sleep(0.15)
    c.commit()
    n = c.execute("SELECT COUNT(*) FROM phase_state WHERE ts=? AND level='pair'", (now,)).fetchone()[0]
    print(f"[PHASE] записано пер-пара: {n}")


if __name__ == "__main__":
    main()
