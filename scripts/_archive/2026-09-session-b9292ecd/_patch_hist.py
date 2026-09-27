p = 'eq_levels_lab.py'; s = open(p, encoding='utf-8').read()
rep = []
rep.append(('''RETEST = os.environ.get("RETEST") == "1"   # 18.09, скрин MSTR «перезашёл от уровня»: вход на РЕТЕСТЕ пробитого уровня
OUT = Path("G:/oko_lab/out/eq_levels" + ("_rt" if RETEST else "")); OUT.mkdir(parents=True, exist_ok=True)''',
'''RETEST = os.environ.get("RETEST") == "1"   # 18.09, скрин MSTR «перезашёл от уровня»: вход на РЕТЕСТЕ пробитого уровня
HIST = os.environ.get("HIST") == "1"       # 19.09 (Егор: «наши EQH/EQL — уровень в моменте, у автора исторический»):
                                           # окно 180 дней, хаи и низы в ОДНОМ кластере (уровень = область), флаг зеркальности,
                                           # сетапы школы уровней: пробой с закрепом · отбой · ретест · ЛОЖНЫЙ ПРОБОЙ
OUT = Path("G:/oko_lab/out/eq_levels" + ("_hist" if HIST else "_rt" if RETEST else "")); OUT.mkdir(parents=True, exist_ok=True)'''))
rep.append(('''WIN = 24 * 30               # окно уровней 30 дней''', '''WIN = 24 * (180 if HIST else 30)   # окно уровней'''))
rep.append(('''        if t % 4 == 0:                                  # уровни пересчитываем раз в 4 часа — свинги меняются редко
            # свинги, известные к бару t, из окна 30 дней
            kh = np.searchsorted(sh_conf, t, "right"); kl = np.searchsorted(sl_conf, t, "right")
            ph = [(hi[i], i) for i in sh[:kh] if i >= t - WIN]; pl = [(lo[i], i) for i in sl_[:kl] if i >= t - WIN]
            levels = [(L, k, li, "R") for L, k, li in clusters(ph)] + [(L, k, li, "S") for L, k, li in clusters(pl)]
        elif not RETEST:
            continue''',
'''        if t % 4 == 0:                                  # уровни пересчитываем раз в 4 часа — свинги меняются редко
            # свинги, известные к бару t, из окна
            kh = np.searchsorted(sh_conf, t, "right"); kl = np.searchsorted(sl_conf, t, "right")
            ph = [(hi[i], i) for i in sh[:kh] if i >= t - WIN]; pl = [(lo[i], i) for i in sl_[:kl] if i >= t - WIN]
            if HIST:
                # уровень = область: хаи и низы вместе; сторона уровня относительно цены — по положению; зеркальный —
                # если в кластере есть и хаи, и низы (уровень менял роль)
                pts = sorted([(p_, i, True) for p_, i in ph] + [(p_, i, False) for p_, i in pl])
                grp = []; cur = [pts[0]] if pts else []
                for q_ in pts[1:]:
                    if q_[0] <= cur[0][0] * (1 + 2 * TOL):
                        cur.append(q_)
                    else:
                        grp.append(cur); cur = [q_]
                if cur:
                    grp.append(cur)
                levels = []
                for c_ in grp:
                    L = float(np.mean([p_ for p_, _, _ in c_])); nt = sum(1 for _, _, top in c_ if top); nb = len(c_) - nt
                    levels.append((L, len(c_), max(i for _, i, _ in c_), "R" if L > cl[t] else "S", nt > 0 and nb > 0, t - min(i for _, i, _ in c_)))
            else:
                levels = [(L, k, li, "R", False, 0) for L, k, li in clusters(ph)] + [(L, k, li, "S", False, 0) for L, k, li in clusters(pl)]
        elif not (RETEST or HIST):
            continue'''))
rep.append(('''        for L, k, li, kind in levels:
            if k < 2:
                continue
            key = (round(L, 10), kind)
            if RETEST:''',
'''        for L, k, li, kind, mirror, age_h in levels:
            if k < 2:
                continue
            key = (round(L, 10), kind)
            if HIST:
                w = cl[t - 48:t]
                touched = (hi[t] >= L * (1 - TOL)) if kind == "R" else (lo[t] <= L * (1 + TOL))
                broke = (cl[t - 1] <= L and c > L) if kind == "R" else (cl[t - 1] >= L and c < L)
                bounce = touched and ((c < L * (1 - TOL)) if kind == "R" else (c > L * (1 + TOL))) and not broke
                # ложный пробой: прошлый бар ЗАКРЫЛСЯ за уровнем, текущий вернулся и закрылся по эту сторону
                false_b = ((cl[t - 1] > L and c < L * (1 - TOL)) if kind == "R" else (cl[t - 1] < L and c > L * (1 + TOL)))
                if kind == "R":
                    ab = np.where(w > L)[0]
                    rt = (len(ab) > 0 and (w[:ab[0]] < L).any() and not (w[ab[0]:] < L * (1 - TOL)).any()
                          and lo[t] <= L * (1 + TOL) and c > L * (1 + TOL) and lo[t - 1] > L * (1 + TOL))
                else:
                    ab = np.where(w < L)[0]
                    rt = (len(ab) > 0 and (w[:ab[0]] > L).any() and not (w[ab[0]:] > L * (1 + TOL)).any()
                          and hi[t] >= L * (1 - TOL) and c < L * (1 - TOL) and hi[t - 1] < L * (1 - TOL))
                conds = (("пробой", broke), ("отбой", bounce), ("ретест", rt), ("ложный пробой", false_b))
            elif RETEST:'''))
rep.append(('''                elif setup == "ретест":
                    ent_i = t + 1; long_ = kind == "R"          # от пробитого сопротивления — лонг, от пробитой поддержки — шорт
                else:
                    ent_i = t + 1; long_ = kind == "S"''',
'''                elif setup == "ретест":
                    ent_i = t + 1; long_ = kind == "R"          # от пробитого сопротивления — лонг, от пробитой поддержки — шорт
                elif setup == "ложный пробой":
                    ent_i = t + 1; long_ = kind == "S"          # ложный пробой поддержки → лонг, сопротивления → шорт
                else:
                    ent_i = t + 1; long_ = kind == "S"'''))
rep.append(('''                ahead = [Lx for Lx, kx, _, kd in levels if kx >= 2 and ((Lx > e + a_) if long_ else (Lx < e - a_))]''',
'''                ahead = [Lx for Lx, kx, _, kd, *_r in levels if kx >= 2 and ((Lx > e + a_) if long_ else (Lx < e - a_))]'''))
rep.append(('''                        rows.append({"sym": sym, "setup": setup, "side": "LONG" if long_ else "SHORT", "kind": kind, "level": L,
                                     "touches": k,''',
'''                        rows.append({"sym": sym, "setup": setup, "side": "LONG" if long_ else "SHORT", "kind": kind, "level": L,
                                     "touches": k, "mirror": bool(mirror), "age_d": age_h / 24,'''))
rep.append(('''            print(f"\\n=== {setup}, ATR×2, цель {tgt}: сторона × касания"); print(agg(z.groupby(["side", "касания"], observed=True)).to_string())''',
'''            print(f"\\n=== {setup}, ATR×2, цель {tgt}: сторона × касания"); print(agg(z.groupby(["side", "касания"], observed=True)).to_string())
            if "mirror" in z.columns:
                zz = z.assign(зерк=np.where(z.mirror, "зеркальный", "односторонний"), возраст=pd.cut(z.age_d, [-1, 14, 45, 90, 400], labels=["<2 нед", "2–6 нед", "6–13 нед", ">13 нед"]))
                print(f"=== {setup}, ATR×2, цель {tgt}: сторона × зеркальность"); print(agg(zz.groupby(["side", "зерк"])).to_string())
                print(f"=== {setup}, ATR×2, цель {tgt}: сторона × возраст уровня"); print(agg(zz.groupby(["side", "возраст"], observed=True)).to_string())'''))
for a, b in rep:
    assert a in s, a[:60]
    s = s.replace(a, b)
open(p, 'w', encoding='utf-8').write(s); print('patched', len(rep))
