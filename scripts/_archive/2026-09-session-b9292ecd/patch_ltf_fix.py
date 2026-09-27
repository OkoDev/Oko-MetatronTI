import ast, os
os.chdir(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
p = "core/waves/wave_analyst.py"; s = open(p, encoding="utf-8").read()
old = '''        want_bull = not st["up"]
        evs = [e for e in sr.events if e.bull == want_bull and e.kind == "CHoCH" and bt[e.i] > st["t5x"]]
        ltf_state = {"choch_int": None, "choch_sw": None}'''
assert old in s
s = s.replace(old, '''        want_bull = not st["up"]
        # точный экстремум пятой на младшем ТФ внутри её 4h-бара; сломы «после пятой» — строго после него
        j5a = int(np.searchsorted(bt, st["t5x"])); j5b = int(np.searchsorted(bt, st["t5x"] + pd.Timedelta(hours=4)))
        j5 = j5a + int((bh[j5a:j5b].argmax() if not want_bull else bl[j5a:j5b].argmin())) if j5b > j5a else min(j5a, len(bt) - 1)
        evs = [e for e in sr.events if e.bull == want_bull and e.kind == "CHoCH" and e.i > j5]
        ltf_state = {"choch_int": None, "choch_sw": None}''')
old = '''                j5a = int(np.searchsorted(bt, st["t5x"])); j5b = int(np.searchsorted(bt, st["t5x"] + pd.Timedelta(hours=4)))
                j5 = j5a + int((bh[j5a:j5b].argmax() if not want_bull else bl[j5a:j5b].argmin())) if j5b > j5a else j5a
                ltf_state["t5"] = bt[j5]                     # точное время экстремума пятой на младшем ТФ'''
assert old in s
s = s.replace(old, '''                ltf_state["t5"] = bt[j5]                     # точное время экстремума пятой на младшем ТФ''')
old = '''                jb = back[0].i if back else len(bt) - 1        # откат B подтверждён встречным сломом → A закончена'''
assert old in s
s = s.replace(old, '''                jb = max(back[0].i if back else len(bt) - 1, j5)   # откат B подтверждён встречным сломом → A закончена''')
ast.parse(s); open(p, "w", encoding="utf-8").write(s); print("ok")
