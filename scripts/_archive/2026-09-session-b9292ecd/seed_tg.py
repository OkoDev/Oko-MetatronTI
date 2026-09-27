"""Разовая публикация активных сетапов тени в Oko_Waves (Егор 15.09: «сетапы выложить»): разбор → tg_notify с since
на начало 14.09 → state.json. Запускать между прогонами тени (при остановленной тени)."""
import json, sys
sys.path.insert(0, r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.argv = ["wave5_shadow.py"]
import pandas as pd
import scripts.wave5_shadow as sh
from core.waves import wave_tg

sh.NOW = pd.Timestamp.utcnow()
state = json.loads(sh.STATE.read_text(encoding="utf-8"))
cfg = wave_tg.tg_config(); cfg["since"] = "2026-09-14 00:00"
wave_tg.tg_config = lambda: cfg                      # отметка только для этого прогона; tg.json не трогаем
reports = sh.refresh_analyst(state)
print("разборов:", len(reports))
sh.tg_notify(state, reports)
sh.STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
for k, v in state.items():
    print(v["sym"], v["status"], "tg_new", v.get("tg_new"), "tg_in", v.get("tg_in"), "tg_last", v.get("tg_last"))
