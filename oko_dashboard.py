"""
OKO MTF BOT - LOCAL DASHBOARD
Zapusk: .venv\Scripts\python oko_dashboard.py
Otkryt: http://localhost:7771
"""

import os, re, subprocess, json
from pathlib import Path
from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)
BASE = Path(__file__).parent

STATUS_MAP = {
    "\U0001f534": {"label": "SROCHNO",   "cls": "urgent"},
    "\U0001f7e1": {"label": "VAZHNO",    "cls": "important"},
    "\U0001f7e2": {"label": "V PLANE",   "cls": "planned"},
    "\U0001f535": {"label": "BEKLOG",    "cls": "backlog"},
    "\U0001f504": {"label": "V RABOTE",  "cls": "inwork"},
    "\u23f8":     {"label": "OTLOZHENO", "cls": "paused"},
    "\u2705":     {"label": "GOTOVO",    "cls": "done"},
}

def parse_tasks(path):
    if not path.exists():
        return {"sprints": [], "stats": {}}
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    sprints = []
    current_sprint = None
    stats = {s["cls"]: 0 for s in STATUS_MAP.values()}

    for line in lines:
        if "\U0001f680" in line and "SPRINT" in line.upper() or "\U0001f680" in line and "\u0421\u041f\u0420\u041d\u0422" in line:
            idx = line.find("\U0001f680")
            name = line[idx+2:].strip().strip("|").strip()
            name = re.sub(r'\(.*?\)', '', name).strip()
            current_sprint = {"name": name[:80], "tasks": []}
            sprints.append(current_sprint)
            continue

        task_m = re.match(r'\|\s*\[?([A-Z]+-[\w.]+)\]?(?:\([^)]*\))?\s*\|\s*([^\|]+?)\s*\|\s*([^\|]+?)\s*\|\s*([^\|]*?)\s*\|', line)
        if task_m and current_sprint is not None:
            task_id    = task_m.group(1).strip()
            status_raw = task_m.group(2).strip()
            desc       = task_m.group(3).strip()
            role       = task_m.group(4).strip()

            status_info = None
            for emoji, info in STATUS_MAP.items():
                if emoji in status_raw:
                    status_info = info
                    stats[info["cls"]] = stats.get(info["cls"], 0) + 1
                    break

            if status_info and task_id and len(desc) > 2:
                current_sprint["tasks"].append({
                    "id": task_id,
                    "status": status_info,
                    "desc": desc[:200],
                    "role": role
                })

    sprints = [s for s in sprints if s["tasks"]]
    return {"sprints": sprints, "stats": stats}


def get_git_log(n=15):
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-" + str(n)],
            cwd=BASE, capture_output=True, text=True, timeout=5
        )
        commits = []
        for line in result.stdout.strip().splitlines():
            m = re.match(r"([a-f0-9]+)\s+(.+)", line)
            if m:
                commits.append({"hash": m.group(1), "msg": m.group(2)})
        return commits
    except Exception as e:
        return [{"hash": "err", "msg": str(e)}]


def read_head(filename, n=50):
    p = BASE / filename
    if not p.exists():
        return "[not found: " + filename + "]"
    return "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[:n])


def read_analyses():
    folder = BASE / "memory" / "trader_analyses"
    if not folder.exists():
        return []
    entries = []
    for f in sorted(folder.glob("*.md"), reverse=True)[:5]:
        text = f.read_text(encoding="utf-8", errors="replace")
        entries.append({"date": f.stem, "preview": text[:300].replace("\n", " ")})
    return entries


@app.route("/api/tasks")
def api_tasks():
    return jsonify(parse_tasks(BASE / "TASKS.md"))

@app.route("/api/commits")
def api_commits():
    return jsonify(get_git_log())

@app.route("/api/status")
def api_status():
    return jsonify({
        "current_state": read_head("memory/current_state.md", 60),
        "whats_next":    read_head("whats-next.md", 30),
    })

@app.route("/api/analyses")
def api_analyses():
    return jsonify(read_analyses())

@app.route("/api/generate-post", methods=["POST"])
def generate_post():
    import urllib.request as urlreq
    data = request.json or {}
    commits = get_git_log(5)
    commits_str = "\n".join("- " + c["msg"] for c in commits)
    whats_next = read_head("whats-next.md", 20)
    post_type = data.get("type", "update")
    extra = data.get("extra", "")

    prompt = (
        "Ty — avtor Telegram-kanala SYNTH-MIND OKO. Kanal pro razrabotku algotrejding bota na Python dlya BingX.\n\n"
        "Stil: texnicheskij, chestnyj, bez vody. Nemnogo kiberpank-estetiki. Korotkie abzacy. Emoji umestno.\n\n"
        "Tip posta: " + post_type + "\n\n"
        "Poslednie kommity:\n" + commits_str + "\n\n"
        "Chto dal'she:\n" + whats_next + "\n\n"
        + ("Kontekst: " + extra + "\n\n" if extra else "")
        + "Napishi post dlya Telegram (150-250 slov). Yazyk: russkij. Bez markdown-zagolovkov."
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        env_path = BASE / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY"):
                    api_key = line.split("=", 1)[-1].strip().strip('"').strip("'")

    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not found in .env"}), 400

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 600,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urlreq.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
    )
    try:
        with urlreq.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return jsonify({"post": result["content"][0]["text"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>OKO MTF DASHBOARD</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#050810;--bg2:#090e1a;--bg3:#0d1525;--border:#1a2a4a;--cyan:#00e5ff;--mag:#ff0090;--green:#00ff88;--yellow:#ffcc00;--orange:#ff6600;--dim:#3a4a6a;--text:#c8d8f0;--mono:'Share Tech Mono',monospace;--sans:'Rajdhani',sans-serif}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:15px;height:100vh;overflow:hidden}
.layout{display:grid;grid-template-columns:300px 1fr 280px;grid-template-rows:52px 1fr;height:100vh}
header{grid-column:1/-1;background:var(--bg2);border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 18px;gap:16px}
.logo{font-family:var(--mono);font-size:17px;color:var(--cyan);letter-spacing:3px;text-shadow:0 0 20px rgba(0,229,255,0.4)}
.logo span{color:var(--mag)}
.hstats{display:flex;gap:8px;margin-left:auto}
.hs{font-family:var(--mono);font-size:10px;padding:3px 9px;border:1px solid var(--border);border-radius:2px;cursor:pointer;transition:all .2s}
.hs.urgent{border-color:#ff3355;color:#ff3355}
.hs.inwork{border-color:var(--cyan);color:var(--cyan)}
.hs.important{border-color:var(--yellow);color:var(--yellow)}
.clock{font-family:var(--mono);font-size:11px;color:var(--dim);margin-left:12px}
.panel{background:var(--bg2);border-right:1px solid var(--border);overflow-y:auto;padding:14px}
.ptitle{font-family:var(--mono);font-size:10px;letter-spacing:2px;color:var(--dim);margin-bottom:12px;padding-bottom:7px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:7px}
.dot{width:6px;height:6px;border-radius:50%;background:var(--cyan);box-shadow:0 0 6px var(--cyan);display:inline-block}
.dot.m{background:var(--mag);box-shadow:0 0 6px var(--mag)}
.pulse{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 7px var(--green);animation:pulse 2s infinite;display:inline-block}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.sprint-n{font-family:var(--mono);font-size:9px;color:var(--mag);letter-spacing:1px;margin:8px 0 6px}
.task{padding:7px 9px;margin-bottom:5px;border-left:2px solid var(--border);background:var(--bg3);border-radius:0 3px 3px 0;transition:all .15s}
.task:hover{border-left-color:var(--cyan);background:#0f1a2e}
.th{display:flex;align-items:center;gap:7px;margin-bottom:3px}
.tid{font-family:var(--mono);font-size:10px;color:var(--dim)}
.badge{font-size:9px;padding:1px 5px;border-radius:2px;font-family:var(--mono)}
.urgent{background:rgba(255,51,85,.12);color:#ff3355;border:1px solid rgba(255,51,85,.3)}
.important{background:rgba(255,204,0,.1);color:var(--yellow);border:1px solid rgba(255,204,0,.3)}
.planned{background:rgba(0,255,136,.1);color:var(--green);border:1px solid rgba(0,255,136,.3)}
.backlog{background:rgba(0,100,200,.1);color:#4488ff;border:1px solid rgba(0,100,200,.3)}
.inwork{background:rgba(0,229,255,.08);color:var(--cyan);border:1px solid rgba(0,229,255,.3)}
.paused{background:rgba(80,80,80,.15);color:#777;border:1px solid #333}
.done{background:rgba(0,255,136,.03);color:#336644;border:1px solid #224433}
.tdesc{font-size:12px;color:var(--text);line-height:1.4}
.trole{font-family:var(--mono);font-size:9px;color:var(--dim);margin-top:2px}
.filters{display:flex;gap:5px;margin-bottom:10px;flex-wrap:wrap}
.fc{font-family:var(--mono);font-size:9px;padding:2px 7px;border:1px solid var(--border);background:transparent;color:var(--dim);cursor:pointer;border-radius:2px;transition:all .15s}
.fc.active{border-color:var(--cyan);color:var(--cyan);background:rgba(0,229,255,.05)}
.center{background:var(--bg);overflow-y:auto;padding:14px 18px}
.commit{display:flex;gap:9px;padding:6px 0;border-bottom:1px solid var(--border);align-items:flex-start}
.commit:last-child{border-bottom:none}
.chash{font-family:var(--mono);font-size:10px;color:var(--mag);min-width:55px;opacity:.8}
.cmsg{font-size:12px;color:var(--text);line-height:1.4}
.ctag{font-family:var(--mono);font-size:9px;padding:1px 4px;border-radius:2px;margin-right:4px}
.tf{background:rgba(0,229,255,.08);color:var(--cyan)}
.tfx{background:rgba(255,102,0,.12);color:var(--orange)}
.td{background:rgba(100,100,100,.15);color:#888}
.tp{background:rgba(0,255,136,.08);color:var(--green)}
.tr{background:rgba(255,0,144,.08);color:var(--mag)}
.sdiv{font-family:var(--mono);font-size:9px;letter-spacing:2px;color:var(--dim);margin:16px 0 10px;padding-top:11px;border-top:1px solid var(--border);display:flex;align-items:center;gap:7px}
.sdiv::after{content:'';flex:1;height:1px;background:var(--border)}
.tbtn{font-family:var(--mono);font-size:10px;padding:4px 10px;border:1px solid var(--border);background:transparent;color:var(--dim);cursor:pointer;border-radius:2px;transition:all .2s}
.tbtn:hover,.tbtn.active{border-color:var(--cyan);color:var(--cyan);background:rgba(0,229,255,.04)}
.textra{width:100%;background:var(--bg3);border:1px solid var(--border);color:var(--text);font-family:var(--sans);font-size:13px;padding:7px 10px;border-radius:3px;resize:vertical;min-height:55px;margin:8px 0;outline:none}
.textra:focus{border-color:var(--cyan)}
.textra::placeholder{color:var(--dim)}
.gbtn{font-family:var(--mono);font-size:11px;letter-spacing:1px;padding:7px 18px;border:1px solid var(--cyan);background:rgba(0,229,255,.07);color:var(--cyan);cursor:pointer;border-radius:2px;transition:all .2s;text-transform:uppercase}
.gbtn:hover{background:rgba(0,229,255,.14);box-shadow:0 0 14px rgba(0,229,255,.18)}
.gbtn:disabled{opacity:.4;cursor:default}
.tgout{margin-top:12px;background:var(--bg3);border:1px solid var(--border);border-radius:3px;padding:12px;font-size:13px;line-height:1.7;white-space:pre-wrap;position:relative;min-height:60px}
.cpbtn{position:absolute;top:7px;right:7px;font-family:var(--mono);font-size:9px;padding:2px 7px;border:1px solid var(--border);background:var(--bg2);color:var(--dim);cursor:pointer;border-radius:2px;transition:all .2s}
.cpbtn:hover{border-color:var(--green);color:var(--green)}
.loader{display:inline-block;width:12px;height:12px;border:2px solid rgba(0,229,255,.2);border-top-color:var(--cyan);border-radius:50%;animation:spin .8s linear infinite;margin-right:6px;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}
.sblock{font-family:var(--mono);font-size:10px;line-height:1.7;color:#7788aa;white-space:pre-wrap;word-break:break-word}
.ae{padding:7px 0;border-bottom:1px solid var(--border);cursor:pointer}
.ae:hover{color:var(--text)}
.adate{font-family:var(--mono);font-size:9px;color:var(--mag);margin-bottom:2px}
.aprev{font-size:11px;color:#5566aa;line-height:1.4}
.errmsg{color:#ff3355;font-family:var(--mono);font-size:11px;padding:7px}
::-webkit-scrollbar{width:3px}::-webkit-scrollbar-track{background:var(--bg)}::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
</style>
</head>
<body>
<div class="layout">
<header>
  <div class="logo">OKO<span>.</span>MTF</div>
  <div style="font-family:var(--mono);font-size:10px;color:var(--dim);letter-spacing:2px">SYNTH-MIND DASHBOARD</div>
  <div class="hstats" id="hstats"></div>
  <div class="clock" id="clock"></div>
</header>

<div class="panel" id="left">
  <div class="ptitle"><span class="dot"></span>TASKS / BACKLOG</div>
  <div class="filters" id="filters"></div>
  <div id="tasklist"><span style="color:var(--dim);font-family:var(--mono);font-size:11px">loading...</span></div>
</div>

<div class="center">
  <div class="ptitle"><span class="dot m"></span>GIT LOG</div>
  <div id="commits"></div>
  <div class="sdiv">TG POST GENERATOR</div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px" id="typebts">
    <button class="tbtn active" data-t="update">АПДЕЙТ</button>
    <button class="tbtn" data-t="achievement">ДОСТИЖЕНИЕ</button>
    <button class="tbtn" data-t="bug">БАГ ПОФИКСИЛ</button>
    <button class="tbtn" data-t="reflection">МЫСЛИ</button>
    <button class="tbtn" data-t="trade">СДЕЛКА</button>
  </div>
  <textarea class="textra" id="extra" placeholder="Доп. контекст: что случилось, инсайт, сделка..."></textarea>
  <button class="gbtn" id="gbtn" onclick="genPost()">ГЕНЕРИРОВАТЬ ПОСТ</button>
  <div class="tgout" id="tgout" style="display:none"></div>
</div>

<div class="panel" style="border-right:none;border-left:1px solid var(--border)">
  <div class="ptitle"><span class="pulse"></span>&nbsp;CURRENT STATE</div>
  <div class="sblock" id="sblock">loading...</div>
  <div class="sdiv">TRADER LOG</div>
  <div id="analyses"></div>
</div>
</div>

<script>
var ptype='update';
setInterval(function(){
  var n=new Date();
  document.getElementById('clock').textContent=n.toLocaleDateString('ru')+' '+n.toLocaleTimeString('ru');
},1000);

document.querySelectorAll('[data-t]').forEach(function(b){
  b.onclick=function(){
    document.querySelectorAll('[data-t]').forEach(function(x){x.classList.remove('active')});
    b.classList.add('active');ptype=b.dataset.t;
  };
});

function tagHtml(msg){
  var m=msg.match(/^(\w+)(\([^)]+\))?:\s*/);
  if(!m)return '<span class="cmsg">'+msg+'</span>';
  var t=m[1].toLowerCase();
  var cls={feat:'tf',fix:'tfx',docs:'td',chore:'td',perf:'tp',refactor:'tr'}[t]||'td';
  return '<span class="ctag '+cls+'">'+m[1]+'</span><span class="cmsg">'+msg.slice(m[0].length)+'</span>';
}

var allSprints=[];var afilter='all';
function setFilter(f){
  afilter=f;
  document.querySelectorAll('.fc').forEach(function(c){c.classList.toggle('active',c.dataset.f===f)});
  renderTasks();
}
function renderTasks(){
  var html='';
  allSprints.forEach(function(sp){
    var tasks=afilter==='all'?sp.tasks.filter(function(t){return t.status.cls!=='done'}):sp.tasks.filter(function(t){return t.status.cls===afilter});
    if(!tasks.length)return;
    html+='<div class="sprint-n">'+sp.name+'</div>';
    tasks.forEach(function(t){
      html+='<div class="task"><div class="th"><span class="tid">'+t.id+'</span><span class="badge '+t.status.cls+'">'+t.status.label+'</span></div><div class="tdesc">'+t.desc+'</div>'+(t.role?'<div class="trole">'+t.role+'</div>':'')+'</div>';
    });
  });
  document.getElementById('tasklist').innerHTML=html||'<div style="color:var(--dim);font-family:var(--mono);font-size:11px;padding:16px 0">нет задач</div>';
}

fetch('/api/tasks').then(function(r){return r.json()}).then(function(d){
  allSprints=d.sprints||[];
  var stats=d.stats||{};
  var hs=document.getElementById('hstats');
  var order=['urgent','inwork','important'];
  var lbl={urgent:'СРОЧНО',inwork:'В РАБОТЕ',important:'ВАЖНО'};
  hs.innerHTML=order.map(function(c){return (stats[c]||0)>0?'<div class="hs '+c+'" onclick="setFilter(\''+c+'\')">'+lbl[c]+': '+stats[c]+'</div>':''}).join('');
  var fbar=document.getElementById('filters');
  fbar.innerHTML='<button class="fc active" data-f="all" onclick="setFilter(\'all\')">ВСЕ</button>';
  var seen={};
  allSprints.forEach(function(s){s.tasks.forEach(function(t){seen[t.status.cls]=t.status.label})});
  ['urgent','inwork','important','planned','backlog'].forEach(function(c){
    if(seen[c])fbar.innerHTML+='<button class="fc" data-f="'+c+'" onclick="setFilter(\''+c+'\')">'+seen[c]+'</button>';
  });
  renderTasks();
});

fetch('/api/commits').then(function(r){return r.json()}).then(function(cs){
  document.getElementById('commits').innerHTML=cs.map(function(c){
    return '<div class="commit"><span class="chash">'+c.hash+'</span><span>'+tagHtml(c.msg)+'</span></div>';
  }).join('');
});

fetch('/api/status').then(function(r){return r.json()}).then(function(d){
  document.getElementById('sblock').textContent=(d.current_state||'').split('\\n').slice(0,50).join('\\n');
});

fetch('/api/analyses').then(function(r){return r.json()}).then(function(es){
  document.getElementById('analyses').innerHTML=es.map(function(e){
    return '<div class="ae"><div class="adate">'+e.date+'</div><div class="aprev">'+e.preview.slice(0,120)+'...</div></div>';
  }).join('')||'<div style="color:var(--dim);font-size:11px">нет записей</div>';
});

function genPost(){
  var btn=document.getElementById('gbtn');
  var out=document.getElementById('tgout');
  var extra=document.getElementById('extra').value;
  btn.disabled=true;
  btn.innerHTML='<span class="loader"></span>генерация...';
  out.style.display='block';
  out.innerHTML='<span style="color:var(--dim);font-family:var(--mono);font-size:11px">Claude генерирует...</span>';
  fetch('/api/generate-post',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:ptype,extra:extra})})
  .then(function(r){return r.json()})
  .then(function(d){
    if(d.error){out.innerHTML='<span class="errmsg">ERR: '+d.error+'</span>';}
    else{out.innerHTML='<button class="cpbtn" onclick="navigator.clipboard.writeText(document.getElementById(\'tgout\').innerText.replace(\'COPY\\'+'\\n\',\\'\\'))">COPY</button>'+d.post;}
    btn.disabled=false;btn.innerHTML='ГЕНЕРИРОВАТЬ ПОСТ';
  }).catch(function(e){
    out.innerHTML='<span class="errmsg">'+e.message+'</span>';
    btn.disabled=false;btn.innerHTML='ГЕНЕРИРОВАТЬ ПОСТ';
  });
}
setInterval(function(){
  fetch('/api/tasks').then(function(r){return r.json()}).then(function(d){allSprints=d.sprints||[];renderTasks();});
  fetch('/api/commits').then(function(r){return r.json()}).then(function(cs){
    document.getElementById('commits').innerHTML=cs.map(function(c){return '<div class="commit"><span class="chash">'+c.hash+'</span><span>'+tagHtml(c.msg)+'</span></div>';}).join('');
  });
},60000);
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

if __name__ == "__main__":
    print("=" * 45)
    print("  OKO MTF DASHBOARD")
    print("  http://localhost:7771")
    print("=" * 45)
    app.run(host="127.0.0.1", port=7771, debug=False)
