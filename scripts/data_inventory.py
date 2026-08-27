# -*- coding: utf-8 -*-
"""ПОЛНОЕ МЕНЮ ДАННЫХ проекта — что реально можно спрашивать (для DS/роя и для Егора).
Инвентаризует: свечной кэш, БД сделок (+реальные ключи features_json), внешний фид,
ЖИВУЮ шину (полный JSON PairState по реальной паре)."""
import sqlite3, json, os, sys, datetime as dt, urllib.request, urllib.parse
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")
OUT=[]
def p(s=""): OUT.append(str(s)); print(s)
def ts(v):
    try:
        v=float(v); return dt.datetime.fromtimestamp(v/1000 if v>1e11 else v,dt.timezone.utc).strftime("%Y-%m-%d")
    except Exception: return str(v)[:10]
def db_report(path,title,skip_cols=()):
    if not os.path.exists(path): p(f"\n### {title}: НЕТ ФАЙЛА"); return
    p(f"\n### {title}  ({os.path.getsize(path)/1e6:.0f} MB)")
    c=sqlite3.connect(path)
    for t in sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")):
        try:
            n=c.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
            cols=[r[1] for r in c.execute(f"PRAGMA table_info([{t}])")]
            tc=[x for x in cols if x.lower() in ("time","ts","date","created_at","timestamp")]
            rng=""
            if tc and n:
                mn,mx=c.execute(f"SELECT MIN([{tc[0]}]),MAX([{tc[0]}]) FROM [{t}]").fetchone()
                rng=f"  [{ts(mn)} → {ts(mx)}]"
            p(f"  {t:24} n={n:>10,}{rng}")
            p(f"      поля: {', '.join(cols)}")
        except Exception as e: p(f"  {t}: err {e}")
    c.close()
p("="*100); p("# МЕНЮ ДАННЫХ Oko MTF — что можно спрашивать"); p("="*100)
# 1. свечной кэш
p("\n### СВЕЧНОЙ КЭШ ohlcv_cache.db — покрытие по ТФ")
c=sqlite3.connect("ohlcv_cache.db")
for tf in ("1m","3m","5m","15m","30m","1h","4h","1d","1w"):
    r=c.execute("SELECT COUNT(DISTINCT symbol),COUNT(*),MIN(time),MAX(time) FROM ohlcv_cache WHERE timeframe=?",(tf,)).fetchone()
    if r and r[1]: p(f"  {tf:4} символов={r[0]:>4}  свечей={r[1]:>12,}  [{ts(r[2])} → {ts(r[3])}]")
p("  поля свечи: symbol, timeframe, time(ms), open, high, low, close, volume")
for t in ("usdtd","usdtd_1h","usdtd_cg","mcap_supply","mcap_meta","funding_rates","onchain_events"):
    try:
        n=c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        cols=[r[1] for r in c.execute(f"PRAGMA table_info({t})")]
        p(f"  доп.таблица {t:14} n={n:>8,}  поля: {', '.join(cols)}")
    except Exception: pass
c.close()
db_report("subscriptions.db","БД СДЕЛОК subscriptions.db")
db_report("oko_feed/external_data.db","ВНЕШНИЙ ФИД oko_feed/external_data.db")
# 2. реальные ключи features_json
p("\n### FEATURES_JSON — реальные ключи (что бот пишет по каждой сделке)")
try:
    c=sqlite3.connect("subscriptions.db")
    cnt=Counter(); tot=0
    for (fj,) in c.execute("SELECT features_json FROM simulated_trades WHERE features_json IS NOT NULL ORDER BY id DESC LIMIT 4000"):
        try:
            d=json.loads(fj); tot+=1
            for k in d: cnt[k]+=1
        except Exception: pass
    p(f"  проанализировано сделок: {tot}, уникальных ключей: {len(cnt)}")
    for k,v in cnt.most_common(200): p(f"    {k:38} в {100*v/max(tot,1):5.1f}% сделок")
    c.close()
except Exception as e: p(f"  err {e}")
# 3. живая шина
p("\n### ЖИВАЯ ШИНА (PairState) — полный JSON по реальной паре")
try:
    ps=json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/cube/pairs",timeout=10))
    ps=ps if isinstance(ps,list) else ps.get("pairs",[])
    sym=next((s for s in ps if s.startswith("BTC/")),ps[0])
    d=json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/cube/context/"+urllib.parse.quote(sym,safe=""),timeout=15))
    p(f"  пар в шине: {len(ps)} · пример: {sym}")
    p(f"  поля верхнего уровня: {', '.join(sorted(d.keys()))}")
    for k in sorted(d.keys()):
        v=d[k]
        if isinstance(v,dict) and v:
            p(f"    {k}: dict[{', '.join(list(v.keys())[:14])}]")
            for kk in list(v.keys())[:3]:
                if isinstance(v[kk],dict): p(f"        {k}.{kk}: {json.dumps(v[kk],ensure_ascii=False)[:220]}")
        elif isinstance(v,list): p(f"    {k}: list[{len(v)}] пример={json.dumps(v[:1],ensure_ascii=False)[:200]}")
        else: p(f"    {k}: {json.dumps(v,ensure_ascii=False)[:120]}")
except Exception as e: p(f"  шина недоступна: {type(e).__name__} {e}")
open("memory/DATA_MENU.md","w",encoding="utf-8").write("\n".join(OUT))
print("\n→ сохранено в memory/DATA_MENU.md")
