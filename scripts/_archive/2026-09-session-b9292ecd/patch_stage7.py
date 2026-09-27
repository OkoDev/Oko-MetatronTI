import ast, os
os.chdir(r"E:\MTF BOT\CURSOR\crypto_volume_bot")

p = "scripts/wave5_shadow.py"; s = open(p, encoding="utf-8").read()
old = '''        if i % 50 == 0: print(f"  {i}/{len(syms)}", flush=True)
    save_and_report(state, a)'''
assert old in s
s = s.replace(old, '''        if i % 50 == 0: print(f"  {i}/{len(syms)}", flush=True)
    if not a.asof:
        refresh_analyst(state)
    save_and_report(state, a)


def refresh_analyst(state):
    """🌊 Волновой разбор (core.waves.wave_analyst) для каждого активного сетапа раз в 4h: схема для /waves,
    зона пятой в дневной ноге (OTE/глубокая/за пределами) — главный признак по замеру 14.09."""
    from core.waves.wave_analyst import report_for
    for k, prev in state.items():
        if prev.get("status") == "closed":
            continue
        try:
            r = report_for(prev["sym"], "3m", ROOT / "data" / "wave_analyst", now=NOW)
            prev.update({"analyst_png": r["png"], "analyst_json": r["json"], "zone_1d": r["zone"], "depth_1d": r["depth"]})
            print(f"  разбор {prev['sym']}: {r['zone']} ({r['depth']}) → {r['png']}", flush=True)
        except Exception as e_:
            print(f"  [разбор] {prev['sym']}: {type(e_).__name__} {e_}", flush=True)''')
s = s.replace('"entered_at", "entry_price", "p4_target", "p5_ext", "stop", "outcome", "pnl_pct", "egor", "egor_note", "ai", "ai_note",',
              '"entered_at", "entry_price", "p4_target", "p5_ext", "stop", "outcome", "pnl_pct", "zone_1d", "depth_1d", "egor", "egor_note", "ai", "ai_note",')
ast.parse(s); open(p, "w", encoding="utf-8").write(s)

p = "web/structure_terminal.py"; s = open(p, encoding="utf-8").read()
old = '''"line24_broken", "outcome", "pnl_pct", "detected_at", "bos1", "bos3", "ns", "absorbed")},'''
assert old in s
s = s.replace(old, '''"line24_broken", "outcome", "pnl_pct", "detected_at", "bos1", "bos3", "ns", "absorbed",
                                             "analyst_png", "zone_1d", "depth_1d")},''')
old = '''async def waves_page(_req):'''
assert old in s
s = s.replace(old, '''_WA_DIR = os.path.join(os.path.dirname(_WV_DIR), "wave_analyst")


async def waves_analyst_png(req):
    name = os.path.basename(req.match_info["name"])
    p = os.path.join(_WA_DIR, name)
    if not name.endswith(".png") or not os.path.exists(p):
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "max-age=3600"})


async def api_waves_analyze(req):
    """POST /api/waves/analyze {sym, ltf} — 🌊 волновой разбор любой монеты по запросу (core.waves.wave_analyst.report_for)."""
    try:
        b = await req.json()
    except Exception:
        b = {}
    sym = str(b.get("sym", "")).strip().upper().replace("/USDT", "").replace("-USDT", "")
    if sym.endswith("USDT") and len(sym) > 4:
        sym = sym[:-4]
    if not sym or not sym.isalnum():
        return web.json_response({"ok": False, "err": "нужен тикер, например SOLV"}, status=400)
    ltf = b.get("ltf") if b.get("ltf") in ("3m", "5m", "15m") else "3m"
    from core.waves.wave_analyst import report_for
    try:
        r = await asyncio.get_running_loop().run_in_executor(_POOL, report_for, sym, ltf, _WA_DIR)
    except Exception as e:
        return web.json_response({"ok": False, "err": f"{type(e).__name__}: {e}"}, status=500)
    return web.json_response({"ok": True, **r})


async def waves_page(_req):''')
old = '''    app.router.add_get("/waves/chart/{name}", waves_chart)'''
assert old in s
s = s.replace(old, old + '''
    app.router.add_get("/waves/analyst/{name}", waves_analyst_png)
    app.router.add_post("/api/waves/analyze", api_waves_analyze)''')
old = '''<div class=tabs><span class="bt on" data-f="active">активные</span>'''
assert old in s
s = s.replace(old, '''<div class=ask><input id=asym placeholder="тикер, например SOLV" maxlength=20><span class="bt" id=abtn>🌊 разобрать монету</span><span id=astat class=mut></span></div>
<div id=ares></div>
''' + old)
old = '''.empty{color:var(--mut);padding:30px;text-align:center}'''
assert old in s
s = s.replace(old, old + '''
.ask{display:flex;gap:8px;align-items:center;margin:0 0 12px;flex-wrap:wrap}.ask input{background:var(--card);color:var(--tx);border:1px solid var(--line);border-radius:6px;padding:6px 10px;width:220px}
.ask .bt{cursor:pointer}.mut{color:var(--mut);font-size:12.5px}.zone{font-size:11.5px;padding:1px 7px;border-radius:4px;border:1px solid var(--gold);color:var(--gold)}''')
old = ''' (r.chart?'<figure><img src="/waves/chart/'+r.chart+'" alt="'+r.sym+'" loading=lazy></figure>':'<div class=empty>картинки нет (тень без --draw или сетап старше)</div>')+'''
assert old in s
s = s.replace(old, ''' (r.analyst_png?'<figure><img src="/waves/analyst/'+r.analyst_png+'" alt="разбор '+r.sym+'" loading=lazy><figcaption class=mut>волновой разбор: 1D нога · 4h счёт · 3m слом · сценарии A/B'+(r.chart?' · <a href="/waves/chart/'+r.chart+'" target=_blank>разметка ядра</a>':'')+'</figcaption></figure>':
  (r.chart?'<figure><img src="/waves/chart/'+r.chart+'" alt="'+r.sym+'" loading=lazy></figure>':'<div class=empty>картинки нет</div>'))+''')
old = ''' '<div class=meta>вершина '+'''
assert old in s
s = s.replace(old, ''' (r.zone_1d?'<div class=meta><span class=zone>пятая в дневной ноге: '+r.zone_1d+' ('+r.depth_1d+')</span></div>':'')+
 '<div class=meta>вершина '+''')
old = '''load();setInterval(load,120000);'''
assert old in s
s = s.replace(old, '''async function analyze(){var sym=document.getElementById('asym').value.trim();if(!sym)return;
 var st=document.getElementById('astat');st.textContent='считаю разбор '+sym+'… (20-40 с)';
 try{var r=await fetch('/api/waves/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sym:sym})});var d=await r.json();
  if(!d.ok){st.textContent='ошибка: '+d.err;return;}
  st.textContent='';var h='<section class=card><h2>'+d.sym+' · разбор по запросу'+(d.zone?' <span class=zone>'+d.zone+' ('+d.depth+')</span>':'')+'</h2>';
  h+=d.png?'<figure><img src="/waves/analyst/'+d.png+'" alt="разбор '+d.sym+'"></figure>':'<p class=mut>'+d.text.join('<br>')+'</p>';
  document.getElementById('ares').innerHTML=h+'</section>';
  document.querySelectorAll('#ares figure img').forEach(function(i){i.onclick=function(){document.getElementById('lbi').src=i.src;document.getElementById('lb').style.display='flex';};});
 }catch(e){st.textContent='ошибка: '+e;}}
document.getElementById('abtn').onclick=analyze;document.getElementById('asym').onkeydown=function(e){if(e.key=='Enter')analyze();};
load();setInterval(load,120000);''')
ast.parse(s); open(p, "w", encoding="utf-8").write(s)
print("ok")
