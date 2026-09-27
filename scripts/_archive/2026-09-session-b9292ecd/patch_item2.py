import ast, os
os.chdir(r"E:\MTF BOT\CURSOR\crypto_volume_bot")

p = "scripts/wave5_shadow.py"; s = open(p, encoding="utf-8").read()
old = '''            prev.update({"analyst_png": r["png"], "analyst_json": r["json"], "zone_1d": r["zone"], "depth_1d": r["depth"]})
            print(f"  разбор {prev['sym']}: {r['zone']} ({r['depth']}) → {r['png']}", flush=True)'''
assert old in s
s = s.replace(old, '''            prev.update({"analyst_png": r["png"], "analyst_json": r["json"], "zone_1d": r["zone"], "depth_1d": r["depth"]})
            print(f"  разбор {prev['sym']}: {r['zone']} ({r['depth']}) → {r['png']}", flush=True)
            write_ai_review(k, prev)''')
old = '''def refresh_analyst(state):'''
assert old in s
s = s.replace(old, '''def write_ai_review(key, prev):
    """🧪 Строка «ИИ» на /waves: вердикт правил методички (core.waves.wave_audit) → reviews.json. Оценку Егора не трогаем."""
    from core.waves.wave_audit import audit_setup
    try:
        aj = None
        if prev.get("analyst_json"):
            pj = ROOT / "data" / "wave_analyst" / prev["analyst_json"]
            if pj.exists():
                aj = json.loads(pj.read_text(encoding="utf-8"))
        res = audit_setup(prev, aj)
        rp = DATA / "reviews.json"
        rv = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
        rec = rv.setdefault(key, {})
        rec.update({"ai": res["ai"], "ai_note": res["ai_note"], "ai_ts": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M")})
        rp.write_text(json.dumps(rv, ensure_ascii=False, indent=1), encoding="utf-8")
        prev["ai"], prev["ai_note"] = res["ai"], res["ai_note"]
    except Exception as e_:
        print(f"  [ИИ-сверка] {prev.get('sym')}: {type(e_).__name__} {e_}", flush=True)


def refresh_analyst(state):''')
ast.parse(s); open(p, "w", encoding="utf-8").write(s)

p = "web/structure_terminal.py"; s = open(p, encoding="utf-8").read()
old = '''    return web.json_response({"rows": out, "verdicts": _WV_VERDICTS, "ts": int(time.time())})'''
assert old in s
s = s.replace(old, '''    try:
        from core.waves.wave_audit import agreement
        agr = agreement(rv)
    except Exception:
        agr = {"n": 0, "hit": 0, "by_egor": {}}
    return web.json_response({"rows": out, "verdicts": _WV_VERDICTS, "agreement": agr, "ts": int(time.time())})''')
old = '''<span class=bt data-f="unrated">без оценки</span><span class=sp id=cnt></span></div>'''
assert old in s
s = s.replace(old, '''<span class=bt data-f="unrated">без оценки</span><span class=sp id=cnt></span><span class=mut id=agr title="сколько раз вердикт правил совпал с оценкой Егора"></span></div>''')
old = '''async function load(){var r=await fetch('/api/waves/journal',{cache:'no-store'});var d=await r.json();V=d.verdicts;ROWS=d.rows;render();}'''
assert old in s
s = s.replace(old, '''async function load(){var r=await fetch('/api/waves/journal',{cache:'no-store'});var d=await r.json();V=d.verdicts;ROWS=d.rows;
 var a=d.agreement||{};document.getElementById('agr').textContent=a.n?(' · согласие ИИ ↔ Егор: '+a.hit+'/'+a.n+' ('+Math.round(a.hit/a.n*100)+'%)'):' · согласие ИИ ↔ Егор: оценок Егора пока нет';
 render();}''')
ast.parse(s); open(p, "w", encoding="utf-8").write(s)
print("ok")
