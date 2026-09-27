import ast, os
os.chdir(r"E:\MTF BOT\CURSOR\crypto_volume_bot")

# ── core: трейл-исход параллельно основному
p = "core/waves/wave5_core.py"; s = open(p, encoding="utf-8").read()
old = '''        if out["exit_price"] is not None:
            out["pnl_pct"] = round(((out["exit_price"] - e) / e * 100) * (1 if long_ else -1) - cost_pct, 2)
    return out'''
assert old in s
s = s.replace(old, '''        if out["exit_price"] is not None:
            out["pnl_pct"] = round(((out["exit_price"] - e) / e * 100) * (1 if long_ else -1) - cost_pct, 2)
        # трейл параллельно (be_lab 14.09: единственное улучшение выхода, прошедшее замер — для входа line24):
        # после хода ≥ 1× стопа стоп = max(стоп, вход, минимум последних 24 ч) для лонга (зеркально для шорта)
        risk = abs(e - sl); bars24 = max(1, int(round(24 * 60 / max(1, (lt[1] - lt[0]) / np.timedelta64(1, "m"))))) if len(lt) > 1 else 96
        tsl = sl; armed = False; mfe = 0.0
        for k in range(j + 1, len(lt)):
            if (lo_[k] <= tsl) if long_ else (hi_[k] >= tsl):
                out.update({"outcome_trail": "trail" if armed else "stop", "exit_trail": tsl}); break
            if (hi_[k] >= tp) if long_ else (lo_[k] <= tp):
                out.update({"outcome_trail": "target", "exit_trail": tp}); break
            if lt[k] >= end_t:
                out.update({"outcome_trail": "time", "exit_trail": float(c[k])}); break
            mfe = max(mfe, (hi_[k] - e) if long_ else (e - lo_[k]))
            if mfe >= risk:
                armed = True
                seg = lo_[max(j + 1, k - bars24 + 1):k + 1] if long_ else hi_[max(j + 1, k - bars24 + 1):k + 1]
                tsl = max(tsl, e, float(seg.min())) if long_ else min(tsl, e, float(seg.max()))
        if out.get("exit_trail") is not None:
            out["pnl_trail"] = round(((out["exit_trail"] - e) / e * 100) * (1 if long_ else -1) - cost_pct, 2)
    return out''')
ast.parse(s); open(p, "w", encoding="utf-8").write(s)

# ── тень: ширина слива, кластер, трейл в записи
p = "scripts/wave5_shadow.py"; s = open(p, encoding="utf-8").read()
old = '''            dh = fetch(ex, bx, "4h", 1000)'''
assert old in s
s = s.replace(old, '''            dh = fetch(ex, bx, "4h", 1000)
            if len(dh) > 20:
                R72.append(float(dh.close.iloc[-1] / dh.close.iloc[-19] - 1))      # ход за 72 ч — для ширины слива''')
old = '''    for i, s in enumerate(syms, 1):'''
assert old in s
s = s.replace(old, '''    R72 = []
    for i, s in enumerate(syms, 1):''', 1)
old = '''        refresh_analyst(state)'''
assert old in s
s = s.replace(old, '''        mark_market(state, now, R72, len(syms))
        refresh_analyst(state)''', 1)
old = '''def refresh_analyst(state):'''
assert old in s
s = s.replace(old, '''def mark_market(state, now, r72, n_univ):
    """Рыночный момент для сетапов этого скана (замер 14.09, memory wave_3m_program):
    · breadth10/20 — доля монет вселенной с ходом за 72 ч < −10% / −20% (высокая 10-78% — лучше, экстремальная >78% — хуже);
    · cluster_3d — сколько РАЗНЫХ монет дали пятёрку той же стороны за ПРОШЛЫЕ 3 дня (без текущего дня);
      cluster_norm — приведено к вселенной замера (145 монет); mass_flush — cluster_norm ≥ 7 (Δ +1.8 п.п., но 20 дней в замере)."""
    arr = np.array(r72, float) if r72 else np.array([])
    b10 = round(float((arr < -0.10).mean()), 3) if arr.size else None
    b20 = round(float((arr < -0.20).mean()), 3) if arr.size else None
    for k, v in state.items():
        if v.get("detected_at") == now and v.get("breadth10") is None:
            v["breadth10"], v["breadth20"], v["universe_n"] = b10, b20, n_univ
    for k, v in state.items():
        if v.get("cluster_3d") is not None:
            continue
        d0 = pd.Timestamp(v["detected_at"], tz="UTC").floor("1D")
        others = {x["sym"] for x in state.values() if x["sym"] != v["sym"] and x.get("side") == v.get("side")
                  and d0 - pd.Timedelta(days=3) <= pd.Timestamp(x["detected_at"], tz="UTC") < d0}
        v["cluster_3d"] = len(others)
        un = v.get("universe_n") or n_univ
        v["cluster_norm"] = round(len(others) * 145 / max(un, 1), 1)
        v["mass_flush"] = bool(v["cluster_norm"] >= 7)


def refresh_analyst(state):''')
# transition: трейл-поля
old = '''        prev["exit_price"] = js(ls["exit_price"]); prev["pnl_pct"] = ls["pnl_pct"]'''
assert old in s
s = s.replace(old, '''        prev["exit_price"] = js(ls["exit_price"]); prev["pnl_pct"] = ls["pnl_pct"]
        prev["outcome_trail"] = ls.get("outcome_trail"); prev["pnl_trail"] = ls.get("pnl_trail")''')
s = s.replace('"entered_at", "entry_price", "p4_target", "p5_ext", "stop", "outcome", "pnl_pct", "zone_1d", "depth_1d",',
              '"entered_at", "entry_price", "p4_target", "p5_ext", "stop", "outcome", "pnl_pct", "outcome_trail", "pnl_trail", "cluster_3d", "cluster_norm", "mass_flush", "breadth10", "zone_1d", "depth_1d",')
if "import numpy as np" not in s:
    s = s.replace("import pandas as pd", "import numpy as np\nimport pandas as pd", 1)
ast.parse(s); open(p, "w", encoding="utf-8").write(s)

# ── /waves: бейджи рыночного момента и трейл
p = "web/structure_terminal.py"; s = open(p, encoding="utf-8").read()
old = '''                                             "analyst_png", "zone_1d", "depth_1d")},'''
assert old in s
s = s.replace(old, '''                                             "analyst_png", "zone_1d", "depth_1d", "cluster_3d", "cluster_norm", "mass_flush", "breadth10",
                                             "outcome_trail", "pnl_trail", "exit_price", "closed_at")},''')
old = ''' (r.zone_1d?'<div class=meta><span class=zone>пятая в дневной ноге: '+r.zone_1d+' ('+r.depth_1d+')</span></div>':'')+'''
assert old in s
s = s.replace(old, ''' '<div class=meta>'+(r.zone_1d?'<span class=zone>пятая в дневной ноге: '+r.zone_1d+' ('+r.depth_1d+')</span> ':'')+
  (r.cluster_3d!=null?'<span class=zone title="сколько разных монет дали пятёрку той же стороны за прошлые 3 дня; в скобках — приведено к 145 монетам замера">'+(r.mass_flush?'🌊 после массового слива':'кластер')+': '+r.cluster_3d+' ('+r.cluster_norm+')</span> ':'')+
  (r.breadth10!=null?'<span class=zone title="доля монет вселенной с ходом за 72 ч ниже −10% на момент детекции">ширина слива: '+Math.round(r.breadth10*100)+'%</span>':'')+'</div>'+''')
old = ''' '<div class=kv><span>линия 2-4</span><b>'+(r.line24_broken?'пробита':'нет')+'</b></div>'+(r.pnl_pct!=null?'<div class=kv><span>итог</span><b>'+r.pnl_pct+'%</b></div>':'')+'</div>'+'''
assert old in s
s = s.replace(old, ''' '<div class=kv><span>линия 2-4</span><b>'+(r.line24_broken?'пробита':'нет')+'</b></div>'+
 (r.pnl_pct!=null?'<div class=kv><span>итог ('+r.outcome+')</span><b class="'+(r.pnl_pct>=0?'up':'dn')+'">'+r.pnl_pct+'%</b></div>':'')+
 (r.pnl_trail!=null?'<div class=kv><span>итог с трейлом ('+r.outcome_trail+')</span><b class="'+(r.pnl_trail>=0?'up':'dn')+'">'+r.pnl_trail+'%</b></div>':'')+'</div>'+''')
ast.parse(s); open(p, "w", encoding="utf-8").write(s)
print("ok")
