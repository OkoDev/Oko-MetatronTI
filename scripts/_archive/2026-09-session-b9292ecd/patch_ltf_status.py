import ast, os
os.chdir(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
p = "core/waves/wave5_core.py"; s = open(p, encoding="utf-8").read()
a = s.index("def ltf_status(setup: Dict[str, Any], dl: pd.DataFrame, p: WaveParams = WaveParams()) -> Dict[str, Any]:")
b = s.index("            \"p5_ext\": p5e, \"stop\": sl, \"last_close\": last, \"w5_reached\": w5_hit, \"corr_reached\": corr_hit}", a)
b = s.index("\n", b) + 1
new = '''def ltf_status(setup: Dict[str, Any], dl: pd.DataFrame, p: WaveParams = WaveParams(), after=None,
               entry_w_h: float = 96.0, hold_h: float = 240.0, cost_pct: float = 0.10) -> Dict[str, Any]:
    """Статус по LTF-ряду (закрытые бары) ПО ПРАВИЛАМ БЭКТЕСТА (перепроверка тени 14.09):
    · триггер (первый кросс WT / первое закрытие за линией 2-4) ищется только на барах, открытых НЕ РАНЬШЕ `after`
      (закрытие 4h-бара детекции) и не позже вершины пятой + entry_w_h; вход — open следующего бара;
    · стоп фиксируется на входе: за экстремумом пятой, известным к бару триггера (не ползёт за новыми минимумами);
    · исход — по минимумам/максимумам (стоп раньше цели на одном баре), цель = конец волны 4, выход по времени hold_h.
    До 14.09 тень засчитывала триггеры ДО детекции (вход с опозданием 4-101 ч) и считала стоп от текущего минимума —
    стоп не мог сработать никогда."""
    long_ = setup["side"] == "LONG"
    lt = dl.index.values.astype("datetime64[ns]"); c = dl.close.values.astype(float)
    hi_, lo_, op_ = dl.high.values.astype(float), dl.low.values.astype(float), dl.open.values.astype(float)
    up_c, dn_c = _wt_cross(dl)
    t5 = np.datetime64(pd.Timestamp(setup["top_time"]).tz_localize(None).to_datetime64() if pd.Timestamp(setup["top_time"]).tzinfo else pd.Timestamp(setup["top_time"]).to_datetime64())
    jb = int(np.searchsorted(lt, t5))
    rt = pd.Timestamp(setup["line_ref_time"]); ref_t = np.datetime64((rt.tz_localize(None) if rt.tzinfo else rt).to_datetime64())
    ref_p, sh = float(setup["line_ref_price"]), float(setup["line_slope_h"])
    if after is not None:
        at = pd.Timestamp(after); at = at.tz_convert(None) if at.tzinfo else at
        ja = max(jb, int(np.searchsorted(lt, np.datetime64(at.to_datetime64()))))
    else:
        ja = jb
    jw = int(np.searchsorted(lt, t5 + np.timedelta64(int(entry_w_h * 60), "m")))

    def line_at(m):
        return ref_p + sh * ((lt[m] - ref_t) / np.timedelta64(60, "m"))
    broke = [m for m in range(ja, min(len(lt), jw)) if ((c[m] > line_at(m)) if long_ else (c[m] < line_at(m)))]
    cross = up_c if long_ else dn_c; crosses = [m for m in range(ja, min(len(lt), jw)) if cross[m]]
    if jb < len(lt):
        ext_now = float(lo_[jb:].min()) if long_ else float(hi_[jb:].max())
    else:
        ext_now = float(setup["p5"])
    p5e = min(float(setup["p5"]), ext_now) if long_ else max(float(setup["p5"]), ext_now)
    w5_hit = [k for k in ("w5_618", "w5_eq1", "w5_chan", "w5_1618") if ((p5e <= setup[k]) if long_ else (p5e >= setup[k]))]
    last = float(c[-1]) if len(c) else float("nan")
    corr_hit = [k for k in ("corr_382", "corr_500", "corr_618", "corr_w4") if ((last >= setup[k]) if long_ else (last <= setup[k]))]
    out = {"cross_first": pd.Timestamp(lt[crosses[0]]) if crosses else None, "line24_broken": bool(broke),
           "line24_first": pd.Timestamp(lt[broke[0]]) if broke else None, "line24_now": float(line_at(len(lt) - 1)) if len(lt) else None,
           "p5_ext": p5e, "last_close": last, "w5_reached": w5_hit, "corr_reached": corr_hit,
           "entry_window_over": bool(len(lt) and lt[-1] >= t5 + np.timedelta64(int(entry_w_h * 60), "m")),
           "trigger": None, "entry_time": None, "entry_price": None, "stop": p5e * (1 - p.buf) if long_ else p5e * (1 + p.buf),
           "outcome": None, "exit_time": None, "exit_price": None, "pnl_pct": None}
    trig = sorted([(m, "cross") for m in crosses[:1]] + [(m, "line24") for m in broke[:1]])
    if trig and trig[0][0] + 1 < len(lt):
        j, kind = trig[0]
        e = float(op_[j + 1])
        ext_e = float(lo_[jb:j + 1].min()) if long_ else float(hi_[jb:j + 1].max())
        p5_at = min(float(setup["p5"]), ext_e) if long_ else max(float(setup["p5"]), ext_e)
        sl = p5_at * (1 - p.buf) if long_ else p5_at * (1 + p.buf)
        tp = float(setup["p4_target"])
        out.update({"trigger": kind, "entry_time": pd.Timestamp(lt[j + 1]), "entry_price": e, "stop": sl})
        end_t = lt[j + 1] + np.timedelta64(int(hold_h * 60), "m")
        for k in range(j + 1, len(lt)):
            if (lo_[k] <= sl) if long_ else (hi_[k] >= sl):
                out.update({"outcome": "stop", "exit_time": pd.Timestamp(lt[k]), "exit_price": sl}); break
            if (hi_[k] >= tp) if long_ else (lo_[k] <= tp):
                out.update({"outcome": "target", "exit_time": pd.Timestamp(lt[k]), "exit_price": tp}); break
            if lt[k] >= end_t:
                out.update({"outcome": "time", "exit_time": pd.Timestamp(lt[k]), "exit_price": float(c[k])}); break
        if out["exit_price"] is not None:
            out["pnl_pct"] = round(((out["exit_price"] - e) / e * 100) * (1 if long_ else -1) - cost_pct, 2)
    return out
'''
s = s[:a] + new + s[b:]
ast.parse(s); open(p, "w", encoding="utf-8").write(s)

p = "scripts/wave5_shadow.py"; s = open(p, encoding="utf-8").read()
a = s.index("def transition(prev, ls, now, sym):"); b = s.index("def save_and_report(state, a):")
s = s[:a] + '''def transition(prev, ls, now, sym):
    """detected → entered → closed по правилам бэктеста (core.waves.wave5_core.ltf_status: триггер после детекции,
    вход open следующего бара, стоп фиксирован на входе, исход по экстремумам баров)."""
    st = prev.get("status", "detected")
    if st == "detected" and ls.get("entry_time") is not None:
        prev["status"] = "entered"; prev["entered_at"] = str(ls["entry_time"])[:16]; prev["entry_price"] = ls["entry_price"]
        prev["entry_trigger"] = ls["trigger"]; prev["stop"] = js(ls["stop"])
        print(f"  IN   {sym:<12} {prev['side']} вход по {ls['trigger']} {prev['entered_at']} @ {ls['entry_price']:.6g} · цель {prev['p4_target']:.6g} · стоп {ls['stop']:.6g}", flush=True)
    elif st == "detected" and ls.get("entry_window_over"):
        prev["status"] = "closed"; prev["closed_at"] = now; prev["outcome"] = "no_entry"
        print(f"  --   {sym:<12} окно входа истекло без триггера", flush=True)
    if prev.get("status") == "entered" and ls.get("outcome"):
        prev["status"] = "closed"; prev["closed_at"] = str(ls["exit_time"])[:16]; prev["outcome"] = ls["outcome"]
        prev["exit_price"] = js(ls["exit_price"]); prev["pnl_pct"] = ls["pnl_pct"]
        print(f"  OUT  {sym:<12} {ls['outcome']} {ls['pnl_pct']:+.2f}%", flush=True)
    for k in ("cross_first", "line24_broken", "line24_first", "line24_now", "p5_ext", "last_close"):
        prev[k] = js(ls[k])
    if prev.get("status") != "entered":
        prev["stop"] = js(ls["stop"])
    prev["w5_reached"] = ",".join(ls["w5_reached"]); prev["corr_reached"] = ",".join(ls["corr_reached"])
    prev["hours_from_top"] = round((NOW - pd.Timestamp(prev["top_time"], tz="UTC" if pd.Timestamp(prev["top_time"]).tzinfo is None else None)).total_seconds() / 3600, 1)


def detect_close(prev):
    """Момент, с которого разрешён вход: закрытие 4h-бара детекции (детекция идёт через ~3 мин после закрытия)."""
    return pd.Timestamp(prev["detected_at"], tz="UTC").floor("4h")


''' + s[b:]
s = s.replace("k = f\"{s}|{st['key']}\"; ls = ltf_status(st, dl, P); prev = state.get(k)",
              "k = f\"{s}|{st['key']}\"; prev = state.get(k); ls = ltf_status(st, dl, P, after=(detect_close(prev) if prev else NOW.floor('4h')), entry_w_h=ENTRY_W_H, hold_h=HOLD_H)")
s = s.replace("            ls = ltf_status(prev, dl, P); transition(prev, ls, now, s)",
              "            ls = ltf_status(prev, dl, P, after=detect_close(prev), entry_w_h=ENTRY_W_H, hold_h=HOLD_H); transition(prev, ls, now, s)")
ast.parse(s); open(p, "w", encoding="utf-8").write(s)
print("ok", s.count("ltf_status("))
