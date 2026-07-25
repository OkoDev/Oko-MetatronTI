# -*- coding: utf-8 -*-
"""STRUCTURE TERMINAL — развязанный live-терминал структуры рынка (24.07, Егор «полноценный
терминал, а не TG-лента»; «дашборд мёртв из-за прокси/лупов»).

Отдельный ЛЁГКИЙ процесс (порт :8010). НОЛЬ зависимости от oko-bot / :8000 / прокси / скан-лупов:
читает самодостаточные движки (marketcap_engine — доминации+ротация) + phase_state. Данные
лёгкие (CMC + Binance ticker), поэтому жив даже когда бот перезапускается / прокси выключены.

Отдаёт: /api/structure (JSON, кэш 45с) + / (self-render HTML-кокпит, поллинг 30с).
Запуск: python web/structure_terminal.py · pm2 --name structure-term (autorestart). Открыть :8010.
"""
import sys, sqlite3, time
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
from aiohttp import web

from core.context.marketcap_engine import live_dominance, rotation_now

PORT = 8010
_DB = "subscriptions.db"
_cache = {"ts": 0.0, "data": None}
_TTL = 45.0


def _phase():
    try:
        c = sqlite3.connect(_DB)
        r = c.execute("SELECT ts, phase, side, detail FROM phase_state WHERE level='macro' "
                      "ORDER BY ts DESC LIMIT 1").fetchone()
        c.close()
        if r:
            return {"ts": r[0], "phase": r[1], "side": r[2], "detail": r[3]}
    except Exception:
        pass
    return None


def _build():
    now = time.time()
    if now - _cache["ts"] < _TTL and _cache["data"] is not None:
        return _cache["data"]
    dom = None; rot = None
    try:
        dom = live_dominance()
    except Exception as e:
        print(f"[STRUCT] dominance err: {e}")
    try:
        rot = rotation_now()
    except Exception as e:
        print(f"[STRUCT] rotation err: {e}")
    data = {"ts": int(now), "dominance": dom, "rotation": rot, "phase": _phase()}
    _cache["ts"] = now; _cache["data"] = data
    return data


async def api(_req):
    return web.json_response(_build())


def _screener_rows(limit=60):
    try:
        c = sqlite3.connect(_DB)
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM screener_state ORDER BY in_zone DESC, approach DESC, conf_score DESC "
            "LIMIT ?", (limit,)).fetchall()]
        c.close()
        return rows
    except Exception:
        return []


async def api_screener(req):
    """GET /api/screener — таблица пар (Неделя-1 плана DC): нога/зона/схождения/WT."""
    limit = int(req.query.get("limit", 60))
    return web.json_response({"rows": _screener_rows(limit), "ts": int(time.time())})


_CLEAN_ERA = "2026-07-11"   # sl_touch+costs (грязь размечена data_era)
_TRACK = ["radar_pump", "radar_spring", "radar_build", "atr_s2", "atr_change",
          "ds_advisor", "breakout"]


def _scoreboard():
    """⚖️ ФОРВАРД-ТАБЛО (Егор 25.07): net% каждого источника рядом → гейт «30 чистых net+»
    виден цифрой. Чистая эра (≥11.07, sl_touch+costs). net = profit_pct − costs_pct."""
    try:
        c = sqlite3.connect(_DB)
        c.row_factory = sqlite3.Row
        rows = c.execute(f"""SELECT signal_type,
              CASE WHEN execution_mode='VST' THEN 'vst' ELSE 'sim' END mode,
              COUNT(*) n,
              ROUND(AVG(CASE WHEN profit_pct>0 THEN 100.0 ELSE 0 END)) wr,
              ROUND(AVG(COALESCE(profit_pct,0)-COALESCE(costs_pct,0)),3) net
            FROM simulated_trades
            WHERE status IN ('SL','TP','TSL') AND created_at >= '{_CLEAN_ERA}'
            GROUP BY signal_type, mode""").fetchall()
        c.close()
        agg: dict = {}
        for r in rows:
            agg.setdefault(r["signal_type"], {})[r["mode"]] = {
                "n": r["n"], "wr": r["wr"], "net": r["net"]}
        return [{"src": s, "vst": agg.get(s, {}).get("vst"),
                 "sim": agg.get(s, {}).get("sim")} for s in _TRACK]
    except Exception:
        return []


async def api_scoreboard(_req):
    """GET /api/scoreboard — форвард net% по источникам (гейт-табло)."""
    return web.json_response({"board": _scoreboard(), "gate": 30, "ts": int(time.time())})


_EXT_DB = "oko_feed/external_data.db"


def _inplay():
    """🎯 Монеты 'в игре' СЕЙЧАС (Егор 25.07) — конфлюэнция внимания всех источников:
    радар(pump🚀/spring🌱/build🔨 со стороной) + OKO-SM скринер(OTE🎯) + DC🤖 + trending🔥.
    Больше источников = выше. → [{sym, tags}]. Терминал развязан → читает БД напрямую."""
    since2 = int(time.time()) - 7200
    coins: dict[str, list[str]] = {}

    def add(sym, tag):
        s = str(sym or "").split("/")[0].split("-")[0].upper().replace("USDT", "").strip()
        if not s:
            return
        coins.setdefault(s, [])
        if tag not in coins[s]:
            coins[s].append(tag)

    try:
        ed = sqlite3.connect(_EXT_DB, timeout=5)
        for tbl, ico, col in (("pump_signals", "🚀", "side"), ("spring_signals", "🌱", "dir"),
                              ("build_signals", "🔨", "side")):
            try:
                for sym, side in ed.execute(f"SELECT symbol,{col} FROM {tbl} WHERE ts>?", (since2,)):
                    add(sym, ico + ("↑" if str(side or "").upper() in ("BUY", "LONG", "UP") else "↓"))
            except Exception:
                pass
        try:
            row = ed.execute("SELECT coins FROM cg_trending ORDER BY ts DESC LIMIT 1").fetchone()
            for sym in (json.loads(row[0]) if row else []):
                add(sym, "🔥")
        except Exception:
            pass
        ed.close()
    except Exception:
        pass
    try:
        sc = sqlite3.connect(_DB, timeout=5)
        for sym, sco in sc.execute("SELECT symbol,conf_score FROM screener_state WHERE in_zone=1 "
                                   "AND conf_score>=3 ORDER BY conf_score DESC LIMIT 10"):
            add(sym, f"🎯{sco:.0f}")
        for (sym,) in sc.execute("SELECT DISTINCT symbol FROM simulated_trades WHERE "
                                 "signal_type='ds_advisor' AND status IN ('OPEN','PENDING_ENTRY')"):
            add(sym, "🤖")
        sc.close()
    except Exception:
        pass
    ranked = sorted(coins.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [{"sym": s, "tags": "".join(t)} for s, t in ranked[:24]]


async def api_inplay(_req):
    """GET /api/inplay — монеты в игре сейчас (радар/скринер/DC/trending)."""
    return web.json_response({"coins": _inplay(), "ts": int(time.time())})


async def api_pair(req):
    """GET /api/pair/{base} — полная строка пары из screener_state."""
    base = req.match_info["base"].upper()
    rows = [r for r in _screener_rows(500) if r["symbol"] == base]
    return web.json_response(rows[0] if rows else {"error": f"{base} нет в скринере"})


_HTML = """<!doctype html><html lang=ru><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>OKO · Структура рынка</title><style>
:root{--bg:#0b0e14;--card:#141922;--line:#232a36;--tx:#d1d6e0;--dim:#7b8496;
--up:#26a69a;--dn:#ef5350;--y:#ffca28;--g:#26a69a;--r:#ef5350;--o:#ff9800}
*{box-sizing:border-box;margin:0}body{background:var(--bg);color:var(--tx);
font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;padding:18px;max-width:1100px;margin:0 auto}
h1{font-size:17px;font-weight:600;letter-spacing:.3px}h1 small{color:var(--dim);font-weight:400;font-size:12px}
.row{display:grid;gap:14px;margin-top:16px}.tri{grid-template-columns:repeat(3,1fr)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
.card .lbl{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.5px}
.card .val{font-size:34px;font-weight:700;margin-top:4px;font-variant-numeric:tabular-nums}
.card .d{font-size:13px;margin-top:2px}.up{color:var(--up)}.dn{color:var(--dn)}
.banner{border-radius:12px;padding:16px 18px;font-size:16px;font-weight:600;border:1px solid var(--line)}
.b-y{background:rgba(255,202,40,.10);border-color:#5a4a12;color:var(--y)}
.b-g{background:rgba(38,166,154,.10);border-color:#134a44;color:var(--g)}
.b-r{background:rgba(239,83,80,.10);border-color:#5a1f1e;color:var(--r)}
.b-o{background:rgba(255,152,0,.10);border-color:#5a3d0f;color:var(--o)}
.b-w{background:var(--card)}
.meta{color:var(--dim);font-size:12px;margin-top:6px}.phase{margin-top:14px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--up);margin-right:6px;animation:p 2s infinite}
@keyframes p{50%{opacity:.3}}.err{color:var(--dn)}
.gold{color:#e0b25c}
.chips{display:flex;gap:7px;flex-wrap:wrap;margin:12px 0 4px}
.chip{font-size:12px;padding:4px 11px;border-radius:20px;border:1px solid var(--line);color:var(--dim);
  background:transparent;cursor:pointer;user-select:none;transition:.15s;font-family:inherit}
.chip:hover{border-color:#3a4658;color:var(--tx)}
.chip.on{background:rgba(224,178,92,.14);border-color:#5a4a28;color:#e0b25c}
#scr th{padding:6px 8px;cursor:pointer;white-space:nowrap;user-select:none}
#scr th:hover{color:var(--tx)}#scr th .ar{opacity:.5;font-size:9px}
#scr td{padding:6px 8px;border-top:1px solid var(--line)}
#scr tbody tr{transition:background .1s}#scr tbody tr:hover{background:rgba(255,255,255,.03)}
#scr a{color:inherit;text-decoration:none}#scr a:hover{color:#e0b25c;text-decoration:underline}
.sbar{display:inline-block;height:5px;border-radius:3px;background:linear-gradient(90deg,#5a4a28,#e0b25c);vertical-align:middle;margin-left:6px}
.lk{color:var(--dim);font-size:10.5px;letter-spacing:.03em}
.ipwrap{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.ipc{display:inline-flex;align-items:center;gap:5px;padding:6px 10px;border-radius:9px;
  background:var(--bg);border:1px solid var(--line);font-size:13px;text-decoration:none;color:var(--tx);transition:.12s}
.ipc:hover{border-color:#5a4a28;color:#e0b25c}
.ipc b{font-weight:600}.ipc .tg{font-size:12px;letter-spacing:-1px}
.ipc.hot{border-color:#5a4a28}
.sbgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:9px;margin-top:10px}
.sbcell{border:1px solid var(--line);border-radius:9px;padding:9px 11px;background:var(--bg)}
.sbsrc{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.04em}
.sbnet{font-size:20px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
.sbmeta{font-size:11px;color:var(--dim2,#5b6480);margin-top:2px}
.sbbar{height:4px;border-radius:3px;background:var(--line);margin-top:6px;overflow:hidden}
.sbbar span{display:block;height:100%}
</style></head><body>
<h1><span class=dot></span>OKO · Структура рынка <small id=age>…</small></h1>
<div class="row tri" id=tri></div>
<div class=row style=margin-top:14px><div class=banner b-w id=rot>…</div></div>
<div class="card phase" id=phase></div>
<div class=card style=margin-top:14px>
  <div class=lbl>⚖️ ФОРВАРД-ТАБЛО · net% источников <span class=dim style=text-transform:none>· чистая эра ≥11.07 · гейт 30 net+ → реальные деньги</span></div>
  <div class=sbgrid id=board></div>
</div>
<div class=card style=margin-top:14px>
  <div class=lbl>🎯 В ИГРЕ сейчас <span class=dim style=text-transform:none>· радар🚀🌱🔨 · OTE🎯 · DC🤖 · хайп🔥 (сортировка: конфлюэнция внимания)</span></div>
  <div class=ipwrap id=inplay></div>
</div>
<div class=card style=margin-top:14px>
  <div class=lbl>🔭 СКРИНЕР OKO-SM · нога старшего 4h · схождения · WT <span id=scount class=dim></span></div>
  <div class=chips id=filters>
    <span class=chip data-f=all>все</span>
    <span class=chip data-f=zone>🎯 в зоне</span>
    <span class=chip data-f=approach>→ подход</span>
    <span class=chip data-f=long>LONG</span>
    <span class=chip data-f=short>SHORT</span>
    <span class=chip data-f=conf>score ≥ 3</span>
    <span class=chip data-f=breakout>⚡ пробой (≤3% к уровню)</span>
  </div>
  <div style="overflow-x:auto;margin-top:6px">
  <table id=scr style="width:100%;border-collapse:collapse;font-size:12.5px;text-align:left;font-variant-numeric:tabular-nums">
    <thead><tr style="color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.05em">
      <th data-s=symbol>пара</th><th data-s=trend>нога</th><th data-s=retr>откат</th>
      <th data-s=status>статус</th><th data-s=conf_score>score <span class=ar>▼</span></th>
      <th data-s=res_dist>уровень ↑↓</th><th>схождения</th><th data-s=wt>WT</th><th data-s=div>див</th><th></th></tr></thead>
    <tbody></tbody>
  </table></div>
</div>
<div class=meta id=foot></div>
<script>
function arrow(x){return x>0.001?'<span class=up>▲ '+x.toFixed(3)+'</span>':x<-0.001?'<span class=dn>▼ '+x.toFixed(3)+'</span>':'· '+x.toFixed(3)}
function bcls(v){if(!v)return'b-w';if(v.includes('🟢'))return'b-g';if(v.includes('🟡'))return'b-y';if(v.includes('🔴'))return'b-r';if(v.includes('🟠'))return'b-o';return'b-w'}
async function tick(){
 try{const r=await fetch('/api/structure',{cache:'no-store'});const d=await r.json();
  const dm=d.dominance,rt=d.rotation;
  const du=rt?rt.d_usdtd:0,db=rt?rt.d_btcd:0,da=rt?rt.d_alt_pct:0;
  const cards=[['USDT.D',dm?dm.usdt_d:null,du,'пп'],['BTC.D',dm?dm.btc_d:null,db,'пп'],['ALT.D',dm?dm.alt_d:null,da,'% mcap']];
  document.getElementById('tri').innerHTML=cards.map(c=>
   '<div class=card><div class=lbl>'+c[0]+'</div><div class=val>'+(c[1]!=null?c[1].toFixed(2)+'%':'—')+'</div><div class=d>'+arrow(c[2])+' <span style=color:var(--dim)>'+c[3]+' /'+(rt?rt.window_h:'?')+'ч</span></div></div>').join('');
  const rot=document.getElementById('rot');rot.className='banner '+bcls(rt&&rt.verdict);rot.textContent=rt?rt.verdict:'ротация: нет данных (CMC)';
  const ph=d.phase;document.getElementById('phase').innerHTML=ph?('<div class=lbl>ФАЗА РЫНКА</div><div style=font-size:18px;font-weight:600;margin-top:4px>'+ph.phase+'</div><div class=meta>'+(ph.detail||'')+'</div>'):'<div class=lbl>ФАЗА</div><div class=meta>нет данных phase_state</div>';
  const cov=dm?(' · покрытие '+(dm.cov_mcap*100).toFixed(0)+'% mcap'):'';
  document.getElementById('foot').textContent='total '+(dm?('$'+(dm.total_mcap/1e12).toFixed(3)+'T'):'—')+cov+' · self-computed (без TW/прокси)';
  document.getElementById('age').textContent='обновлено '+new Date(d.ts*1000).toLocaleTimeString('ru');
 }catch(e){document.getElementById('age').innerHTML='<span class=err>сервер недоступен</span>';}
}
var SR={rows:[],sort:'conf_score',dir:-1,filt:'all'};
function lvlCell(x){
 var up=(x.res_lvl!=null)?{l:x.res_lvl,t:x.res_touches,d:x.res_dist,a:'↑',c:'var(--up)',s:'лонг-пробой'}:null;
 var dn=(x.sup_lvl!=null)?{l:x.sup_lvl,t:x.sup_touches,d:x.sup_dist,a:'↓',c:'var(--dn)',s:'шорт-пробой'}:null;
 var n=(up&&dn)?(Math.abs(up.d)<=Math.abs(dn.d)?up:dn):(up||dn);
 if(!n)return '<span class=dim>—</span>';
 var near=Math.abs(n.d)<=3;
 return '<span title="'+n.s+'" style="color:'+(near?'#e0b25c':n.c)+'">'+n.a+(+n.l).toPrecision(4)+
   '</span> <span class=lk>×'+(n.t||0)+' '+(n.d>0?'+':'')+(n.d||0).toFixed(1)+'%</span>';
}
function scRender(){
 var f=SR.filt,rows=SR.rows.filter(function(x){
  if(f=='zone')return x.in_zone;if(f=='approach')return x.approach;
  if(f=='long')return x.trend=='long';if(f=='short')return x.trend=='short';
  if(f=='conf')return x.conf_score>=3;
  if(f=='breakout')return (x.res_dist!=null&&x.res_dist<=3)||(x.sup_dist!=null&&x.sup_dist>=-3);return true;});
 var k=SR.sort;rows.sort(function(a,b){
  if(k=='symbol'||k=='trend')return SR.dir*String(a[k]||'').localeCompare(String(b[k]||''));
  var va=k=='status'?(a.in_zone?2:a.approach?1:0):(a[k]||0),vb=k=='status'?(b.in_zone?2:b.approach?1:0):(b[k]||0);
  return SR.dir*(va-vb);});
 document.getElementById('scount').textContent='· '+rows.length;
 var mx=Math.max.apply(null,rows.map(function(x){return x.conf_score||0}).concat([5]));
 document.querySelector('#scr tbody').innerHTML=rows.map(function(x){
  var st=x.in_zone?'<span class=gold>🎯 в зоне</span>':(x.approach?'→ подход':'—');
  var legc=x.trend=='long'?'var(--up)':'var(--dn)';
  var hits=(JSON.parse(x.hits||'[]')).slice(0,3).join(' ∩ ')||'—';
  var bw=Math.round(36*(x.conf_score||0)/mx);
  var tw='https://ru.tradingview.com/chart/?symbol=BINGX%3A'+x.symbol+'USDT.P&interval=240';
  var bx='https://bingx.com/ru/perpetual/'+x.symbol+'-USDT';
  return '<tr>'+
   '<td style="font-weight:600"><a href="'+tw+'" target=_blank>'+x.symbol+'</a></td>'+
   '<td style="color:'+legc+'">'+(x.trend||'—').toUpperCase()+'</td>'+
   '<td>'+(x.retr!=null?Math.round(x.retr*100)+'%':'—')+'</td>'+
   '<td>'+st+(x.noise?' <span style=color:var(--dim)>шум</span>':'')+'</td>'+
   '<td style="font-weight:600;color:'+(x.conf_score>=3?'#e0b25c':'inherit')+'">'+(x.conf_score||0).toFixed(1)+
     '<span class=sbar style="width:'+bw+'px"></span></td>'+
   '<td>'+lvlCell(x)+'</td>'+
   '<td style="color:var(--dim);max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+hits+'</td>'+
   '<td>'+(x.wt>0?'+':'')+Math.round(x.wt||0)+'</td>'+
   '<td>'+(x.div?'<span class=up>R+</span>':'—')+'</td>'+
   '<td class=lk><a href="'+bx+'" target=_blank>BINGX↗</a></td></tr>';
 }).join('')||'<tr><td colspan=10 style="padding:10px;color:var(--dim)">скринер наполняется (цикл вахты 15 мин)…</td></tr>';
}
async function scr(){try{var r=await fetch('/api/screener?limit=150',{cache:'no-store'});var d=await r.json();SR.rows=d.rows||[];scRender();}catch(e){}}
async function ip(){try{var r=await fetch('/api/inplay',{cache:'no-store'});var d=await r.json();
 document.getElementById('inplay').innerHTML=(d.coins||[]).map(function(x){
  var multi=(x.tags.match(/[🚀🌱🔨🎯🤖🔥]/gu)||[]).length>=2;
  var tw='https://ru.tradingview.com/chart/?symbol=BINGX%3A'+x.sym+'USDT.P&interval=240';
  return '<a class="ipc'+(multi?' hot':'')+'" href="'+tw+'" target=_blank><b>'+x.sym+'</b><span class=tg>'+x.tags+'</span></a>';
 }).join('')||'<span class=dim style=font-size:13px>тихо — активных сетапов нет</span>';
}catch(e){}}
document.querySelectorAll('#scr th[data-s]').forEach(function(th){th.addEventListener('click',function(){
 var k=th.getAttribute('data-s');SR.dir=(SR.sort==k)?-SR.dir:-1;SR.sort=k;
 document.querySelectorAll('#scr th .ar').forEach(function(a){a.remove()});
 var ar=document.createElement('span');ar.className='ar';ar.textContent=SR.dir<0?' ▼':' ▲';th.appendChild(ar);scRender();});});
document.querySelectorAll('#filters .chip').forEach(function(ch){ch.addEventListener('click',function(){
 document.querySelectorAll('#filters .chip').forEach(function(c){c.classList.remove('on')});
 ch.classList.add('on');SR.filt=ch.getAttribute('data-f');scRender();});});
document.querySelector('#filters .chip[data-f=all]').classList.add('on');
async function sb(){try{var r=await fetch('/api/scoreboard',{cache:'no-store'});var d=await r.json();var g=d.gate||30;
 document.getElementById('board').innerHTML=(d.board||[]).map(function(x){
  var v=x.vst,s=x.sim;                              // VST = гейт (реал исполнение); SIM = shadow-research
  var prim=v||s,shadow=!v&&s;                       // нет VST → показываем SIM как shadow
  if(!prim)return '<div class=sbcell><div class=sbsrc>'+x.src+'</div><div class=sbnet style=color:var(--dim)>—</div><div class=sbmeta>нет сделок</div></div>';
  var pos=prim.net>0,c=pos?'var(--up)':'var(--dn)';
  var prog=Math.min(100,Math.round(100*((v?v.n:0))/g));
  return '<div class=sbcell><div class=sbsrc>'+x.src+(shadow?' <span style=color:#e0b25c>shadow</span>':'')+'</div>'+
   '<div class=sbnet style="color:'+c+'">'+(pos?'+':'')+prim.net.toFixed(2)+'%</div>'+
   '<div class=sbmeta>'+(v?('VST n '+v.n+'/'+g+' · WR '+v.wr+'%'):('SIM n '+s.n+' · WR '+s.wr+'%'))+
     (v&&s?(' <span style=color:var(--dim2)>· sim '+(s.net>0?'+':'')+s.net.toFixed(2)+'%</span>'):'')+'</div>'+
   '<div class=sbbar><span style="width:'+prog+'%;background:'+c+'"></span></div></div>';
 }).join('');
}catch(e){}}
tick();scr();ip();sb();setInterval(tick,30000);setInterval(scr,60000);setInterval(ip,60000);setInterval(sb,120000);
</script></body></html>"""


async def index(_req):
    return web.Response(text=_HTML, content_type="text/html")


def main():
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/structure", api)
    app.router.add_get("/api/screener", api_screener)
    app.router.add_get("/api/scoreboard", api_scoreboard)
    app.router.add_get("/api/inplay", api_inplay)
    app.router.add_get("/api/pair/{base}", api_pair)
    print(f"[STRUCT] терминал структуры → http://localhost:{PORT} (развязан от oko-bot/прокси)")
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
