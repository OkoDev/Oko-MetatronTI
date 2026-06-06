import sys, time, json; sys.path.insert(0,'.'); sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, sqlite3
from datetime import datetime, timezone
import ccxt
ex=ccxt.bingx({'enableRateLimit':True})
from core.smc.smc_engine import ote_retest_setups, detect_fvg
from tools.pattern_mining.combinator_v2 import atr_supertrend
def fetch(tf,lim=400):
    o=ex.fetch_ohlcv('XLM/USDT',tf,limit=lim); x=pd.DataFrame(o,columns=['ts','open','high','low','close','volume'])
    x['ts']=pd.to_datetime(x['ts'],unit='ms',utc=True); return x.set_index('ts')
def write_db(entry,sl,tp1,runner,feat):
    db=sqlite3.connect('subscriptions.db',timeout=15)
    cur=db.execute('INSERT INTO simulated_trades (symbol,timeframe,signal_type,direction,entry_price,stop_loss,take_profit,tp1_price,strategy_name,strategy_type,status,sl_source,tp_source,features_json,confidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
      ('XLMUSDT','5m','ote_gun','LONG',entry,sl,runner,tp1,'ote_nested_gun','SINGLE','OPEN','impulse_low','impulse_high',json.dumps(feat),0.9))
    db.commit(); rid=cur.lastrowid; db.close(); return rid
def best_fvg(d3, lo, hi, w0):
    """bull FVG в зоне с учётом ЗАПОЛНЕНИЯ. Возвращает непокрытую зону (fb..unfilled_top) или None."""
    best=None
    for fv in detect_fvg(d3.loc[w0:]):
        ts0,top,bot,dr=fv[0],max(fv[1],fv[2]),min(fv[1],fv[2]),fv[3]
        if dr!='bull' or not (lo*0.999<=bot and top<=hi*1.001): continue
        after=d3.loc[fv[5]:]                       # бары после образования FVG
        min_low=after['low'].min() if len(after) else top
        if min_low<=bot: continue                  # ПОЛНОСТЬЮ перекрыт (mitigated) → пропуск
        unfilled_top=min(top, min_low)             # непокрытая часть = [bot..unfilled_top]
        fill_pct=(top-min_low)/(top-bot) if top>bot else 0
        if best is None or bot<best[0]: best=(bot, unfilled_top, fill_pct, top)  # глубже = ближе к свежему
    return best
MAXIT=30
for it in range(MAXIT):
    now=datetime.now(timezone.utc).strftime('%H:%M')
    try:
        d5=fetch('5m'); d3=fetch('3m'); px=float(d5['close'].iloc[-1])
        longs=[s for s in ote_retest_setups(d5,depth=11,dev_mult=3.0,only_choch=False,provisional=True) if s['direction']=='long']
        if not longs: print('[%s] LONG OTE нет'%now,flush=True); time.sleep(120); continue
        s=longs[-1]; lo,hi=s['ote']; imp_lo,imp_hi=s['from'][1],s['to'][1]; w0=s['from'][0]
        fvg=best_fvg(d3,lo,hi,w0)
        a3=atr_supertrend(d3); atr_up=(a3[-1]==1)
        o=d3['open'].values;h=d3['high'].values;l=d3['low'].values;c=d3['close'].values;n=len(d3)
        fire=False
        if fvg:
            fb,uf,fill,top=fvg
            for k in range(n-3,n):
                if k<1: continue
                rng=h[k]-l[k]
                if rng<=0: continue
                touched=l[k]<=uf and h[k]>=fb*0.998      # касание НЕПОКРЫТОЙ части
                bull=c[k]>o[k] and (c[k]-l[k])/rng>0.55 and c[k]>=fb
                if touched and bull and atr_up:
                    e=float(c[k]); sl=float(min(l[k-1:k+1].min(),imp_lo)); r=e-sl
                    if r>0:
                        feat={'impulse':[imp_lo,imp_hi],'ote':[lo,hi],'trigger':'FVG_3m','fvg_unfilled':[fb,uf],'fvg_fill_pct':round(fill,2),'atr_trend':'UP'}
                        rid=write_db(e,imp_lo,e+r,imp_hi,feat)
                        print('[%s] 🔥🔥🔥 ВЫСТРЕЛ! LONG XLM entry=%.5g SL=%.5g TP1=%.5g runner=%.5g (FVG fill %.0f%%) → БД id=%d 🔥🔥🔥'%(now,e,sl,e+r,imp_hi,fill*100,rid),flush=True)
                        fire=True; break
        if fire: break
        if fvg:
            fb,uf,fill,top=fvg
            print('[%s] цена %.5g | FVG непокрыт[%.5g..%.5g] fill=%.0f%% | ATRTrend %s | ждём'%(now,px,fb,uf,fill*100,'UP' if atr_up else 'DOWN'),flush=True)
        else:
            print('[%s] цена %.5g | FVG в зоне перекрыт/нет | ATRTrend %s'%(now,px,'UP' if atr_up else 'DOWN'),flush=True)
    except Exception as e:
        print('[%s] err %s'%(now,e),flush=True)
    time.sleep(120)
else:
    print('мониторинг завершён (таймаут %d мин)'%(MAXIT*2),flush=True)
