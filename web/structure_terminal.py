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
</style></head><body>
<h1><span class=dot></span>OKO · Структура рынка <small id=age>…</small></h1>
<div class="row tri" id=tri></div>
<div class=row style=margin-top:14px><div class=banner b-w id=rot>…</div></div>
<div class="card phase" id=phase></div>
<div class=card style=margin-top:14px>
  <div class=lbl>🔭 СКРИНЕР OKO-SM · пары у OTE-зон (нога старшего 4h · схождения · WT)</div>
  <div style="overflow-x:auto;margin-top:10px">
  <table id=scr style="width:100%;border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums">
    <thead><tr style="color:var(--dim);text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em">
      <th style=padding:4px>пара</th><th>нога</th><th>откат</th><th>статус</th><th>score</th><th>схождения</th><th>WT</th><th>див</th></tr></thead>
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
async function scr(){
 try{const r=await fetch('/api/screener?limit=40',{cache:'no-store'});const d=await r.json();
  const tb=document.querySelector('#scr tbody');
  tb.innerHTML=(d.rows||[]).map(x=>{
   const st=x.in_zone?'🎯 в зоне':(x.approach?'→ подход':'—');
   const legc=x.trend==='long'?'var(--up)':'var(--dn)';
   const hits=(JSON.parse(x.hits||'[]')).slice(0,3).join(' ∩ ')||'—';
   return '<tr style="border-top:1px solid var(--line)">'+
    '<td style="padding:5px 4px;font-weight:600">'+x.symbol+'</td>'+
    '<td style="color:'+legc+'">'+(x.trend||'—').toUpperCase()+'</td>'+
    '<td>'+(x.retr!=null?(x.retr*100).toFixed(0)+'%':'—')+'</td>'+
    '<td>'+st+(x.noise?' <span style=color:var(--dim2)>шум</span>':'')+'</td>'+
    '<td style="font-weight:600;color:'+(x.conf_score>=3?'var(--gold,#e0b25c)':'inherit')+'">'+(x.conf_score||0).toFixed(1)+'</td>'+
    '<td style="color:var(--dim);max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+hits+'</td>'+
    '<td>'+(x.wt>0?'+':'')+Math.round(x.wt||0)+'</td>'+
    '<td>'+(x.div?'R+':'—')+'</td></tr>';
  }).join('')||'<tr><td colspan=8 style="padding:8px;color:var(--dim)">скринер наполняется (цикл вахты 15 мин)…</td></tr>';
 }catch(e){}
}
tick();scr();setInterval(tick,30000);setInterval(scr,60000);
</script></body></html>"""


async def index(_req):
    return web.Response(text=_HTML, content_type="text/html")


def main():
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/structure", api)
    app.router.add_get("/api/screener", api_screener)
    app.router.add_get("/api/pair/{base}", api_pair)
    print(f"[STRUCT] терминал структуры → http://localhost:{PORT} (развязан от oko-bot/прокси)")
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
