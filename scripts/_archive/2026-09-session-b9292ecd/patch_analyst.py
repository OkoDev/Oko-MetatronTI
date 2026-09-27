p = r"E:\MTF BOT\CURSOR\crypto_volume_bot\core\waves\wave_analyst.py"
s = open(p, encoding="utf-8").read()

# ── точка 0 → экстремум ноги (Егор 14.09, RECALL: «нога не вся отрисована», шпиль 0.0577 вместо свинга 0.0526)
old = '''    st["t5x"] = dh.index[k]
    rep["structure"] = st'''
new = '''    st["t5x"] = dh.index[k]
    # точка 0 = крайний экстремум с момента, когда цена последний раз была за концом волны 1: подтверждённый свинг
    # может стоять ниже шпиля, с которого на деле началась нога (RECALL: свинг 0.0526, шпиль 0.0577)
    i0_, i1_ = st["wave_idx"][0], st["wave_idx"][1]; p1_ = float(st["wave_px"][1])
    beyond1 = np.where(lh[:i0_] < p1_)[0] if st["up"] is False else np.where(hh[:i0_] > p1_)[0]
    kb = int(beyond1[-1]) + 1 if len(beyond1) else max(0, i0_ - 60)
    if st["up"]:
        k0 = kb + int(lh[kb:i1_].argmin()); better = lh[k0] < st["wave_px"][0]; v0 = float(lh[k0])
    else:
        k0 = kb + int(hh[kb:i1_].argmax()); better = hh[k0] > st["wave_px"][0]; v0 = float(hh[k0])
    st["p0_detector"] = float(st["wave_px"][0])
    if better and k0 != i0_:
        st["wave_idx"] = [k0] + list(st["wave_idx"][1:]); st["wave_px"] = [v0] + list(st["wave_px"][1:])
        st["p0_moved"] = True
    rep["structure"] = st'''
assert old in s; s = s.replace(old, new)
old = '''    st["times"] = [dh.index[i] for i in st["wave_idx"]]
    # фактический экстремум'''
new = '''    # фактический экстремум'''
assert old in s; s = s.replace(old, new)
old = '''    rep["structure"] = st
    g = 1 if st["up"] else -1'''
new = '''    st["times"] = [dh.index[i] for i in st["wave_idx"]]
    rep["structure"] = st
    g = 1 if st["up"] else -1'''
assert old in s; s = s.replace(old, new)
old = '''    if s0:
        T.append(f"Правила ядра'''
new = '''    if st.get("p0_moved"):
        T.append(f"Точка 0 уточнена до экстремума ноги: детектор взял подтверждённый свинг {st['p0_detector']:.6g}, "
                 f"нога началась с {p0:.6g} — коррекции считаются от него.")
    if s0:
        T.append(f"Правила ядра'''
assert old in s; s = s.replace(old, new)

# ── конец дневной ноги по времени, время уровня сломов, касание зоны, прогноз
old = '''        ext = float(seg.low.min()) if want_top else float(seg.high.max())       # противоположный конец ноги'''
assert old in s
s = s.replace(old, old + '''
        ext_t = seg.low.idxmin() if want_top else seg.high.idxmax()''')
old = '''"origin_t": dd.index[o_i], "ext": ext, "depth": depth,'''
assert old in s; s = s.replace(old, '''"origin_t": dd.index[o_i], "ext": ext, "ext_t": ext_t, "depth": depth,''')
old = '''                e = ei[0]; ltf_state["choch_int"] = {"t": bt[e.i], "level": float(e.level)}'''
assert old in s
s = s.replace(old, '''                e = ei[0]; ltf_state["choch_int"] = {"t": bt[e.i], "level": float(e.level),
                                                     "t0": bt[e.level_i] if e.level_i is not None and e.level_i >= 0 else bt[e.i]}''')
old = '''                ltf_state["choch_sw"] = {"t": bt[es[0].i], "level": float(es[0].level)}'''
assert old in s
s = s.replace(old, '''                e2 = es[0]
                ltf_state["choch_sw"] = {"t": bt[e2.i], "level": float(e2.level),
                                         "t0": bt[e2.level_i] if e2.level_i is not None and e2.level_i >= 0 else bt[e2.i]}''')
old = '''                if A > 0:
                    sgn = 1 if want_bull else -1'''
assert old in s
s = s.replace(old, old + '''
                    z05 = a_top - sgn * 0.5 * A
                    tail = base.iloc[ka + 1:]
                    hit = tail.index[(tail.low <= z05) if want_bull else (tail.high >= z05)]
                    ltf_state["zone_touch_t"] = hit[0] if len(hit) else None''')
old = '''    rep["scenarios"].append({"name": "B · 4h-ход — волна 1 нового движения",'''
assert old in s
s = s.replace(old, '''    fork_mid = (corr["0.5"] + corr["0.618"]) / 2
    rep["forecast"] = {"fork": (corr["0.5"], corr["0.618"]),
                       "A": (leg["ext"], "A: старший ход — к экстремуму дневной ноги") if leg and leg["depth"] <= 1.0 else None,
                       "B": (fork_mid + g * 1.0 * rng, "B: волна 3 нового хода ≥ 1.0×w1")}
''' + old)

# ── render заново
s = s[:s.index("def render(")] + open(__file__.replace("patch_analyst.py", "render_new.py"), encoding="utf-8").read()
open(p, "w", encoding="utf-8").write(s)
import ast; ast.parse(s); print("ok")
