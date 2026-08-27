"""
DC-AGENT v4: LOSS-ANALYZED. below_R3 BLOCK. FVG15m GOLD. Adaptive SL.
"""
import sqlite3, json, time, urllib.request, ssl, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

BUS_URL="http://127.0.0.1:8000/api/cube"
STRUCT_URL="http://127.0.0.1:8010/api/structure"
DB=str(Path(__file__).resolve().parent.parent/"subscriptions.db")
FEED_DB=str(Path(__file__).resolve().parent.parent/"oko_feed"/"external_data.db")
POLL_SEC=60; MAX_OPEN=5; MIN_CONF=2; MAX_LOSSES=2

ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
try: __import__("sys").stdout.reconfigure(encoding="utf-8",line_buffering=True)
except: pass

def log(msg): print(f"[{datetime.now().strftime('%H:%M')}] {msg}")

def moon_phase(date):
    y,m=date.year,date.month
    if m<=2: y-=1; m+=12
    A=y//100; B=2-A+A//4
    jd=int(365.25*(y+4716))+int(30.6001*(m+1))+date.day+B-1524.5
    return ((jd-2451550.1)/29.53058867)%1.0
def is_1q(dt): return 0.185<=moon_phase(dt)<=0.315

def fetch(url,to=5):
    try: r=urllib.request.urlopen(url,timeout=to,context=ctx); return json.loads(r.read())
    except: return None

def get_watch_pairs():
    d=fetch(f"{BUS_URL}/pairs?active=1")
    ps=d.get("pairs") if d and isinstance(d,dict) else []
    return ps if len(ps)>=10 else []

def count_open(conn):
    cur=conn.execute("SELECT (SELECT COUNT(*) FROM ds_signals WHERE processed=0)+(SELECT COUNT(*) FROM simulated_trades WHERE status IN ('OPEN','PENDING_ENTRY') AND signal_type='ds_advisor')")
    return cur.fetchone()[0]

def dedup(conn,sym,dr,mins=120):
    cur=conn.execute("SELECT COUNT(*) FROM ds_signals WHERE symbol=? AND direction=? AND created_at>?",(sym,dr,(datetime.now(timezone.utc)-timedelta(minutes=mins)).isoformat()))
    return cur.fetchone()[0]>0

def get_radar(conn):
    try: return {r[0]:{"quadrant":r[1],"funding":r[2],"oi_d5":r[3],"oi_d15":r[4]} for r in conn.execute("SELECT symbol,quadrant,funding,oi_d5,oi_d15 FROM radar_state")}
    except: return {}

def get_phase(conn):
    try:
        r=conn.execute("SELECT phase,detail FROM phase_state WHERE level='macro' ORDER BY ts DESC LIMIT 1").fetchone()
        return {"p":r[0],"d":r[1]} if r else {}
    except: return {}

def get_dom():
    d=fetch(STRUCT_URL)
    return (d.get("dominance",{}),d.get("rotation",{})) if d else ({},{})

def get_hot(conn):
    """Свежие убытки за 24ч: 2+ SL = пауза. Старые не считаем."""
    try:
        rows=conn.execute("SELECT status, closed_at FROM simulated_trades WHERE signal_type='ds_advisor' AND status IN ('SL','TP','TSL') ORDER BY id DESC LIMIT 10").fetchall()
        cutoff=datetime.now(timezone.utc)-timedelta(hours=24)
        losses=0; count=0
        for st,closed in rows:
            if not closed: continue
            try: ct=datetime.fromisoformat(str(closed).replace('Z','+00:00'))
            except: continue
            if ct>=cutoff:
                count+=1
                if st=='SL': losses+=1
            if count>=3: break
        return losses
    except: return 0

def fetch_state(sym):
    full=sym if "/" in sym else f"{sym}/USDT:USDT"
    return fetch(f"{BUS_URL}/context/{urllib.parse.quote(full,safe='')}")

def analyze(sym,state,rad,macro):
    sig={"sym":sym,"conf":0,"rs":[],"dir":None,"confid":0.0}
    smc=state.get("smc_snap",{}) or {}
    cd=(smc.get("last_choch") or {}).get("direction")
    bd=(smc.get("last_bos") or {}).get("direction")
    pr=state.get("tick_price",0) or 0
    
    # Stale filter: только для BTC (альты НЕ сравнивать с BTC)
    base=sym.split("/")[0]
    if base=="BTC":
        try:
            r=urllib.request.urlopen("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",timeout=3,context=ctx)
            btc=float(json.loads(r.read())["price"])
            if abs(pr-btc)/btc>0.03: log(f"Stale {sym}: {pr} vs BTC {btc:.0f}"); return None
        except: pass
    
    if cd in ("UP","DOWN"): sig["conf"]+=1; sig["rs"].append(f"CHoCH {cd}"); sig["dir"]="LONG" if cd=="UP" else "SHORT"
    if bd in ("UP","DOWN"): sig["conf"]+=1; sig["rs"].append(f"BOS {bd}")
    if bd in ("UP","DOWN") and not sig["dir"]: sig["dir"]="LONG" if bd=="UP" else "SHORT"
    
    # MTF-conflict: если CHoCH на 15m, 1h, 4h в одну сторону = супер
    mtf=state.get("smc_snap",{}).get("by_tf",{}) or {}
    mtf_choch=[mtf[tf].get("choch","") for tf in ["15m","1h","4h"] if tf in mtf and mtf[tf].get("choch")]
    mtf_ups=sum(1 for c in mtf_choch if c=="UP")
    mtf_dns=sum(1 for c in mtf_choch if c=="DOWN")
    if mtf_ups==len(mtf_choch) and mtf_ups>=2 and sig.get("dir")=="LONG": sig["conf"]+=1; sig["rs"].append("MTF CHoCH UP")
    if mtf_dns==len(mtf_choch) and mtf_dns>=2 and sig.get("dir")=="SHORT": sig["conf"]+=1; sig["rs"].append("MTF CHoCH DOWN")
    
    # OB
    bo=smc.get("nearest_bull_ob",{}) or {}; be=smc.get("nearest_bear_ob",{}) or {}
    if abs(bo.get("distance_pct",99) or 99)<2.0: sig["conf"]+=1; sig["rs"].append("Bull OB")
    if abs(be.get("distance_pct",99) or 99)<2.0: sig["conf"]+=1; sig["rs"].append("Bear OB")
    
    # FVG active + gold signal for 15m bear fvg
    bear_fvg_15m=False
    for fl,fd,lb in [(smc.get("bull_fvg_active",[]),"LONG","Bull FVG"),(smc.get("bear_fvg_active",[]),"SHORT","Bear FVG")]:
        for fv in (fl or []):
            if (fv.get("mitigation_pct",100) or 100)<80 and (fv.get("age_bars",999) or 999)<100:
                sig["conf"]+=1; sig["rs"].append(lb)
                if not sig["dir"]: sig["dir"]=fd
                if fv.get("tf","")=="15m" and fd=="SHORT": bear_fvg_15m=True
                break
    if bear_fvg_15m and sig.get("dir")=="SHORT": sig["conf"]+=1; sig["rs"].append("FVG15m GOLD")
    
    # EQH/EQL
    if smc.get("eqh_near",False): sig["conf"]+=1; sig["rs"].append("EQH liq")
    if smc.get("eql_near",False): sig["conf"]+=1; sig["rs"].append("EQL liq")
    
    # WT 4h
    wt4=(state.get("wt_snap",{}) or {}).get("4h",{}) or {}
    w1=wt4.get("wt1",0) or 0; wt_t=wt4.get("trend","") or ""
    if w1>60 and sig.get("dir")=="SHORT": sig["conf"]+=1; sig["rs"].append("WT OB")
    if w1<-60 and sig.get("dir")=="LONG": sig["conf"]+=1; sig["rs"].append("WT OS")
    if "UP" in wt_t and sig.get("dir")=="LONG": sig["conf"]+=1; sig["rs"].append("WT trend UP")
    if "DOWN" in wt_t and sig.get("dir")=="SHORT": sig["conf"]+=1; sig["rs"].append("WT trend DOWN")
    
    # Pivot + near S3
    pp=(state.get("pivot_snap",{}) or {}).get("1D",{}) or {}
    if pp and pr>0:
        r1=pp.get("r1",0)or 0; r3=pp.get("r3",0)or 0; s3=pp.get("s3",0)or 0
        if pr>r1: sig["conf"]+=1; sig["rs"].append("Above R1")
        if s3>0 and abs(pr-s3)/pr<0.02:
            sig["conf"]+=2; sig["rs"].append("Near S3 rev")
    # Недельный контекст: above_R1_1W = бычий фон
    pw=(state.get("pivot_snap",{}) or {}).get("1W",{}) or {}
    if pw and pr>0:
        wr1=pw.get("r1",0)or 0; wr2=pw.get("r2",0)or 0
        if pr>wr1: sig["conf"]+=1; sig["rs"].append("1W above R1")
        if pr>wr2: sig["conf"]+=1; sig["rs"].append("1W above R2")
    
    # BTC regime
    br=str(state.get("btc_regime","") or "")
    if "UP" in br and sig.get("dir")=="SHORT": sig["conf"]-=1; sig["rs"].append("BTC no short")
    if "DOWN" in br and sig.get("dir")=="LONG": sig["conf"]-=1; sig["rs"].append("BTC no long")
    
    # SMC verdict + OTE
    sv=str(smc.get("smc_verdict","") or "")
    if "STRONG_BULL" in sv and sig.get("dir")=="LONG": sig["conf"]+=1; sig["rs"].append("SMC strong B")
    if "STRONG_BEAR" in sv and sig.get("dir")=="SHORT": sig["conf"]+=1; sig["rs"].append("SMC strong B")
    if smc.get("price_in_ote",False) and sig.get("dir"): sig["conf"]+=1; sig["rs"].append("OTE")
    od=smc.get("ote_direction","") or ""
    if "UP" in od and sig.get("dir")=="LONG": sig["conf"]+=1; sig["rs"].append("OTE dir UP")
    if "DOWN" in od and sig.get("dir")=="SHORT": sig["conf"]+=1; sig["rs"].append("OTE dir DOWN")
    
    # Radar
    rd=rad.get(sym,{}) if rad else {}
    if rd:
        q=str(rd.get("quadrant",""))
        if "PDN" in q and "OIUP" in q and sig.get("dir")=="SHORT": sig["conf"]+=1; sig["rs"].append(f"Radar {q}")
        if "PUP" in q and "OIDN" in q and sig.get("dir")=="LONG": sig["conf"]+=1; sig["rs"].append(f"Radar {q}")
    
    # Macro
    if macro:
        mp=str(macro.get("p",""))
        if mp=="TREND_UP" and sig.get("dir")=="LONG": sig["conf"]+=1; sig["rs"].append("Macro UP")
        if mp=="TREND_DOWN" and sig.get("dir")=="SHORT": sig["conf"]+=1; sig["rs"].append("Macro DOWN")
    
    # Protective: только маркеры, не съедают conf
    if sig.get("dir")=="LONG" and w1>60: sig["rs"].append("OB overheat (note)")
    if sig.get("dir")=="SHORT" and w1<-60: sig["rs"].append("OS overheat (note)")
    
    if sig["conf"]<MIN_CONF or pr<=0: return None
    
    sig["entry"]=round(pr,4)
    sl_pct=1.0 if sig["conf"]<4 else 1.5 if sig["conf"]<5 else 2.0
    if sig["dir"]=="LONG":
        sig["sl"]=round(pr*(1-sl_pct/100),4); sig["tp"]=round(pr*(1+sl_pct*2/100),4)
    else:
        sig["sl"]=round(pr*(1+sl_pct/100),4); sig["tp"]=round(pr*(1-sl_pct*2/100),4)
    sig["confid"]=min(0.9,0.2+sig["conf"]*0.08)
    sig["rs"].append(f"SL={sl_pct}% TP=2R")
    return sig

def write(conn,sig):
    conn.execute("INSERT INTO ds_signals(symbol,direction,entry_price,stop_loss,take_profit,ttl_min,thesis,confidence) VALUES(?,?,?,?,?,?,?,?)",
                 (sig["sym"],sig["dir"],sig["entry"],sig["sl"],sig["tp"],2880,"; ".join(sig["rs"]),round(sig["confid"],2)))
    conn.commit()

def main():
    log(f"DC-AGENT v4: BELOW R3 BLOCK | FVG15m GOLD | adaptive SL 1-2% | protect OB/OS overheat")
    while True:
        try:
            now=datetime.now(timezone.utc)
            if is_1q(now): log("1st Quarter - PAUSE"); time.sleep(POLL_SEC*5); continue
            conn=sqlite3.connect(DB)
            h=get_hot(conn)
            if h>=MAX_LOSSES: log(f"{h} losses - PAUSE"); time.sleep(POLL_SEC*10); continue
            oc=count_open(conn)
            if oc>=MAX_OPEN: log(f"OPEN={oc} max"); conn.close(); time.sleep(POLL_SEC); continue
            
            fc=sqlite3.connect(FEED_DB) if Path(FEED_DB).exists() else None
            rad=get_radar(fc) if fc else {}; ph=get_phase(conn); dom,rot=get_dom()
            if fc: fc.close()
            
            pairs=get_watch_pairs()
            if not pairs: log("No pairs"); conn.close(); time.sleep(POLL_SEC); continue
            
            cands=[]
            for sym in pairs:
                if dedup(conn,sym,"LONG") and dedup(conn,sym,"SHORT"): continue
                if (oc+len(cands))>=MAX_OPEN: break
                st=fetch_state(sym)
                if not st: continue
                sig=analyze(sym,st,rad,ph)
                if sig: cands.append(sig)
            
            cands.sort(key=lambda x:-x["conf"])
            for sig in cands[:MAX_OPEN-oc]:
                if not dedup(conn,sig["sym"],sig["dir"]):
                    write(conn,sig)
                    log(f"SIGNAL: {sig['sym']} {sig['dir']} conf={sig['conf']} SL={SL_PCT(sig):.1f}% | {'; '.join(sig['rs'][:4])}")
            log(f"Scan: {len(pairs)}p {len(cands)}sig {oc}op {dom.get('usdt_d','?')}/{dom.get('btc_d','?')}%")
            conn.close()
        except Exception as e: log(f"ERR: {e}")
        time.sleep(POLL_SEC)

def SL_PCT(sig):
    for r in sig["rs"]:
        if "SL=" in r:
            try: return float(r.split("SL=")[1].split("%")[0])
            except: return 1.0
    return 1.0

if __name__=="__main__":
    main()
