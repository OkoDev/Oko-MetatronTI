import ast, os, json
import pandas as pd
os.chdir(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
p = "core/waves/wave_tg.py"; s = open(p, encoding="utf-8").read()
old = '''def send_text(text: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
    import requests
    cfg = tg_config(); chat = chat_id or cfg.get("chat_id"); tok = _token()
    if not tok or not chat:
        return {"ok": False, "error": "нет TELEGRAM_TOKEN или chat_id"}
    rr = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", data={"chat_id": chat, "text": text, "parse_mode": "HTML",
                                                                               "disable_web_page_preview": True}, timeout=30)'''
assert old in s
s = s.replace(old, '''def send_text(text: str, chat_id: Optional[str] = None, reply_to: Optional[int] = None) -> Dict[str, Any]:
    import requests
    cfg = tg_config(); chat = chat_id or cfg.get("chat_id"); tok = _token()
    if not tok or not chat:
        return {"ok": False, "error": "нет TELEGRAM_TOKEN или chat_id"}
    data = {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_to:
        data.update({"reply_to_message_id": reply_to, "allow_sending_without_reply": True})
    rr = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", data=data, timeout=30)''')
ast.parse(s); open(p, "w", encoding="utf-8").write(s)

p = "scripts/wave5_shadow.py"; s = open(p, encoding="utf-8").read()
old = '''def watch(a):'''
s = s.replace(old, '''def tg_notify(state, reports=None):
    """📤 Канал Oko_Waves (core.waves.wave_tg, настройки data/wave5_shadow/tg.json): новый сетап — схема разбора;
    вход и выход — короткий ответ на пост сетапа. Постится только то, что появилось после `since` (без залпа по истории)."""
    from core.waves.wave_tg import tg_config, publish_report, send_text
    cfg = tg_config()
    if not cfg.get("enabled"):
        return
    since = cfg.get("since", "")
    for k, v in state.items():
        try:
            fresh = str(v.get("detected_at", "")) >= since
            if cfg.get("post_new", True) and fresh and not v.get("tg_new") and reports and k in reports:
                extra = f"Сетап тени: пятая {'вниз' if v['side'] == 'LONG' else 'вверх'} на 4h, импульс {v.get('imp_pct')}%, цель — конец 4-й {v['p4_target']:.6g}"
                res = publish_report(reports[k], ROOT / "data" / "wave_analyst", side=v["side"], extra=html_escape(extra))
                v["tg_new"] = (res.get("result") or {}).get("message_id") or -1
                print(f"  TG   {v['sym']}: сетап {'ок' if res.get('ok') else res}", flush=True)
            rid = v.get("tg_new") if isinstance(v.get("tg_new"), int) and v.get("tg_new", 0) > 0 else None
            if cfg.get("post_trades", True) and v.get("entered_at") and str(v["entered_at"]) >= since and not v.get("tg_in"):
                txt = (f"▶️ <b>{html_escape(v['sym'].split('/')[0])}</b> · {v['side']} · вход по {v.get('entry_trigger')} {v['entered_at']} UTC @ {v['entry_price']:.6g}\n"
                       f"цель {v['p4_target']:.6g} · стоп {v['stop']:.6g}")
                res = send_text(txt, reply_to=rid); v["tg_in"] = bool(res.get("ok"))
            if cfg.get("post_trades", True) and v.get("status") == "closed" and v.get("pnl_pct") is not None and str(v.get("closed_at", "")) >= since and not v.get("tg_out"):
                icon = {"target": "✅", "stop": "⛔", "time": "⏱"}.get(v.get("outcome"), "•")
                txt = (f"{icon} <b>{html_escape(v['sym'].split('/')[0])}</b> · {v['side']} · выход {v.get('outcome')} {v['closed_at']} UTC · {v['pnl_pct']:+.2f}%"
                       + (f"\nс трейлом: {v.get('outcome_trail')} {v['pnl_trail']:+.2f}%" if v.get("pnl_trail") is not None else ""))
                res = send_text(txt, reply_to=rid); v["tg_out"] = bool(res.get("ok"))
        except Exception as e_:
            print(f"  [TG] {v.get('sym')}: {type(e_).__name__} {e_}", flush=True)


def watch(a):''', 1)
old = '''    from core.waves.wave_analyst import report_for
    for k, prev in state.items():'''
assert old in s
s = s.replace(old, '''    from core.waves.wave_analyst import report_for
    reports = {}
    for k, prev in state.items():''')
old = '''            prev.update({"analyst_png": r["png"], "analyst_json": r["json"], "zone_1d": r["zone"], "depth_1d": r["depth"]})'''
assert old in s
s = s.replace(old, old + "\n            reports[k] = r")
old = '''            print(f"  [разбор] {prev['sym']}: {type(e_).__name__} {e_}", flush=True)
'''
assert old in s
s = s.replace(old, old + "    return reports\n", 1)
s = s.replace('''        refresh_analyst(state)
    save_and_report(state, a)''', '''        tg_notify(state, refresh_analyst(state))
    save_and_report(state, a)''', 1)
old = '''            print(f"  [skip] {s}: {type(e_).__name__} {e_}", flush=True)
    save_and_report(state, a)
'''
assert old in s
s = s.replace(old, '''            print(f"  [skip] {s}: {type(e_).__name__} {e_}", flush=True)
    if not a.asof:
        tg_notify(state)
    save_and_report(state, a)
''')
if "from html import escape as html_escape" not in s:
    s = s.replace("import numpy as np", "from html import escape as html_escape\nimport numpy as np", 1)
assert "html_escape" in s.split("def ")[0]
ast.parse(s); open(p, "w", encoding="utf-8").write(s)
cfg = {"enabled": True, "chat_id": "-1003971555028", "post_new": True, "post_trades": True,
       "since": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M")}
open("data/wave5_shadow/tg.json", "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=1))
print("ok", cfg)
