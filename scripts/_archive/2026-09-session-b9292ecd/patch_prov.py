import ast, os
os.chdir(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
p = "core/waves/wave_progress.py"; s = open(p, encoding="utf-8").read()
old = '''    if best is None:
        return None
    li = best["idx"][-1]'''
assert old in s
s = s.replace(old, '''    if best is None:
        return None
    # 🔑 провизорные точки (Егор 14.09, XLM: «волна 2», хотя цена давно выше конца первой). Свинг масштаба 60 подтверждается
    # через 60 баров, и счёт застревает. Если после последней точки был откат ≥ 0.236 прошлой волны и цена ушла ЗА эту точку —
    # откат становится предварительной точкой; если отката не было — последняя точка ещё не конец, её экстремум обновляется.
    best["prov"] = []
    for _ in range(2):
        li = best["idx"][-1]; lp = best["px"][-1]; kk = best["k"]
        if li >= t - 1 or kk >= 4:
            break
        last_top = (kk % 2 == 0) == best["down"]
        seg_h, seg_l = hh[li + 1:], ll[li + 1:]
        prev_len = abs(best["px"][-1] - best["px"][-2])
        if last_top:
            jx = li + 1 + int(seg_l.argmin()); after = hh[jx + 1:]
            if after.size and after.max() > lp and (lp - ll[jx]) >= 0.236 * prev_len:
                best["idx"].append(jx); best["px"].append(float(ll[jx])); best["times"].append(d1.index[jx]); best["k"] += 1; best["prov"].append(best["k"])
                continue
            if seg_h.max() > lp:
                j2 = li + 1 + int(seg_h.argmax()); best["idx"][-1] = j2; best["px"][-1] = float(hh[j2]); best["times"][-1] = d1.index[j2]
                best["prov"].append(kk)
        else:
            jx = li + 1 + int(seg_h.argmax()); after = ll[jx + 1:]
            if after.size and after.min() < lp and (hh[jx] - lp) >= 0.236 * prev_len:
                best["idx"].append(jx); best["px"].append(float(hh[jx])); best["times"].append(d1.index[jx]); best["k"] += 1; best["prov"].append(best["k"])
                continue
            if seg_l.min() < lp:
                j2 = li + 1 + int(seg_l.argmin()); best["idx"][-1] = j2; best["px"][-1] = float(ll[j2]); best["times"][-1] = d1.index[j2]
                best["prov"].append(kk)
        break
    g_, pxs = best["g"], best["px"]
    if best["k"] >= 2 and not (g_ * (pxs[2] - pxs[0]) > 0):                  # провизорная 2 зашла за 0 — счёт недействителен
        return None
    li = best["idx"][-1]''')
old = '''    T.append(f"{sym}: завершённой пятёрки нет — идёт ход {word} от {px[0]:.6g} ({times[0]:%d.%m %H:%M} UTC). "
             f"Счёт (1h, свинг 60): " + " → ".join(f"{i} = {px[i]:.6g}" for i in range(k + 1)) + f". Сейчас — {names[k]}, цена {price:.6g}.")'''
assert old in s
s = s.replace(old, '''    prov = set(cnt.get("prov") or [])
    T.append(f"{sym}: завершённой пятёрки нет — идёт ход {word} от {px[0]:.6g} ({times[0]:%d.%m %H:%M} UTC). "
             f"Счёт (1h, свинг 60): " + " → ".join(f"{i} = {px[i]:.6g}{'*' if i in prov else ''}" for i in range(k + 1)) + f". Сейчас — {names[k]}, цена {price:.6g}.")
    if prov:
        T.append("* — предварительная точка: свинг масштаба 60 ещё не подтверждён (нужно 60 часов без обновления), счёт может сдвинуться.")''')
ast.parse(s); open(p, "w", encoding="utf-8").write(s); print("ok")
