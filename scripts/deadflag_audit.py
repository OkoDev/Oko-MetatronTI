# -*- coding: utf-8 -*-
"""DEAD-FLAG AUDIT (12.07, Егор «нужен сторож»): класс бага «несовпадение ключа/бара →
combinator-флаг молча 0» повторился 3× (eqh/eql свип, ote_long/short, div-строка). Сторож:
раз в неделю прогон compute_flags по N символам, частота КАЖДОГО булева флага. Флаг с
частотой 0 (или ниже порога) за тысячи баров = мёртвый/сломанный → 🔴 TG SYSTEM.

Принцип (как pivot-sanity/ledger-audit): не доверять что «фича считается» — проверять что
она реально ЗАГОРАЕТСЯ. Мёртвый флаг = потерянный сигнал для обучения и детекторов.

pm2 cron: 06:30 UTC воскресенье. Тест: python scripts/deadflag_audit.py
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import collections
import sqlite3

CACHE_DB = "ohlcv_cache.db"
N_SYMBOLS = 25
BARS = 500
TFS = ("15m", "1h")
# известные РЕДКИЕ-по-природе флаги (не алертить): свипы/сломы — событийные, база <0.5%
RARE_OK_PREFIXES = ("eqh_sweep", "eql_sweep", "bull_bos", "bear_bos",
                    "bull_choch", "bear_choch", "bull_ob", "bear_ob")


def run() -> None:
    import pandas as pd
    from core.calculators.combinator_core import compute_flags

    conn = sqlite3.connect(CACHE_DB)
    syms = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM ohlcv_cache WHERE symbol NOT LIKE 'bingx:%' LIMIT ?",
        (N_SYMBOLS,)).fetchall()]

    def L(sym, tf):
        try:
            return pd.read_sql(
                f"SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                f"WHERE symbol='{sym}' AND timeframe='{tf}' ORDER BY time DESC LIMIT {BARS}",
                conn).iloc[::-1].reset_index(drop=True)
        except Exception:
            return None

    truecount: collections.Counter = collections.Counter()
    seen: set = set()
    bars_tot = 0
    for sym in syms:
        for tf in TFS:
            df = L(sym, tf)
            if df is None or len(df) < 200:
                continue
            try:
                ff = compute_flags(df, tf)
            except Exception:
                continue
            bars_tot += len(ff)
            for c in ff.columns:
                col = ff[c]
                if col.dtype == bool or set(pd.Series(col).dropna().unique()) <= {0, 1, True, False}:
                    base = c.rsplit("_", 1)[0] if c.rsplit("_", 1)[-1] in \
                        ("15m", "1h", "4h", "1d", "5m", "3m") else c
                    seen.add(base)
                    try:
                        truecount[base] += int(col.sum())
                    except Exception:
                        pass

    dead = sorted(b for b in seen if truecount[b] == 0)
    print(f"[DEAD-FLAG] баров {bars_tot}, флаг-баз {len(seen)}, МЁРТВЫХ {len(dead)}")
    for b in dead:
        print(f"   🔴 {b}")
    conn.close()

    if dead:
        try:
            from oko_feed.alerts import send_tg
            lines = "\n".join(f"• <code>{b}</code>" for b in dead[:12])
            send_tg(f"🔴 <b>DEAD-FLAG AUDIT</b> — {len(dead)} флаг(ов) НЕ загораются "
                    f"за {bars_tot} баров (сломаны/мёртвы — потеря сигнала для обучения):\n{lines}\n"
                    f"<i>класс бага: несовпадение ключа/бара (eqh/eql, ote_long 12.07)</i>\n\n#SYSTEM",
                    channel="system")
        except Exception as e:
            print(f"[DEAD-FLAG] tg err: {e}")


if __name__ == "__main__":
    run()
