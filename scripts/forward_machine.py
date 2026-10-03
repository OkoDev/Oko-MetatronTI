# -*- coding: utf-8 -*-
"""ФОРВАРД-МАШИНА (12.07, желание №2 / Сфера 11 Post-Trade Feedback макро-рука).

Судья полигона и радара по ЧЕСТНОМУ % net (ЗАКОН №1: net = profit_pct − costs_pct,
НЕ R). Еженедельный вердикт по каждому источнику + разрез по нишам (direction/regime) —
ищем «жив в нише X» (так выжил atr_S2). Ведёт REAL-MONEY гейт: сколько чистых VST-сделок
накоплено к порогу 30 и положителен ли net → кандидат на реальные деньги.

Не автоторговля, не автовеса — ДИАГНОСТИКА для человека (decision-support > автоторговля).
Персист в forward_verdicts (тренд по неделям), отчёт в TG SYSTEM.

data-era ≥ 2026-07-11 (честная линейка: sl_touch + costs_pct). Исключает ledger_mismatch.
pm2 cron: 08:00 UTC воскресенье. Тест: python scripts/forward_machine.py --once
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import argparse
import sqlite3
import time
import datetime as dt

DB = "subscriptions.db"
DATA_ERA = "2026-07-11"
MIN_N = 20               # ниже — «накапливаем», вердикт не выносим
GATE_N = 30             # порог чистых VST-сделок на реальные деньги (нижняя граница 30-50)
NET_ALIVE = 0.10        # avg net% > → ЖИВ · [−0.10, +0.10] грань · < −0.10 льёт


def _verdict(n: int, net: float) -> str:
    if n < MIN_N:
        return f"⏳ мало (n={n})"
    if net > NET_ALIVE:
        return "✅ ЖИВ"
    if net < -NET_ALIVE:
        return "🔴 льёт"
    return "⚪ грань"


def _cohort(c, where: str, params: tuple, group: str):
    """→ [(key, n, wr, net_avg, mfe_avg), ...] по net desc."""
    rows = c.execute(f"""
        SELECT {group} AS k, COUNT(*) n,
               ROUND(100.0*SUM(profit_pct>0)/COUNT(*), 0) wr,
               ROUND(AVG(profit_pct - COALESCE(costs_pct,0)), 3) net,
               ROUND(AVG(captured_R_pct), 0) mfe
        FROM simulated_trades
        WHERE status IN ('SL','TP','TSL') AND profit_pct IS NOT NULL
          AND created_at >= ?
          AND (features_json IS NULL OR features_json NOT LIKE '%ledger_mismatch%')
          {where}
        GROUP BY {group} HAVING n >= 3 ORDER BY net DESC""", (DATA_ERA,) + params).fetchall()
    return rows


def run(once: bool = False) -> None:
    # N16 29.09: своя база (один писатель); simulated_trades — из базы бота только на чтение
    from core.infra import sat_store
    c = sat_store.connect("forward", attach={"bot": sat_store.BOT_DB})
    c.execute("""CREATE TABLE IF NOT EXISTS forward_verdicts
        (ts INTEGER, cohort TEXT, exec_mode TEXT, n INTEGER, wr REAL, net REAL, verdict TEXT)""")
    # 03.10: КАЖДЫЙ вердикт обязан называть СЛОЙ, к которому относится (скилл research-verdict §0).
    # Журнал сделок смешивает L1–L5, поэтому его вердикт — всегда 'L1-L5 (журнал)', а не «о механике».
    # Отключение источника требует отдельной строки со слоем L1 (стенд scripts/signal_info.py).
    for _col, _type in (("layer", "TEXT"), ("delta_vs_control", "REAL"), ("script", "TEXT")):
        try:
            c.execute(f"ALTER TABLE forward_verdicts ADD COLUMN {_col} {_type}")
        except Exception:
            pass  # колонка уже есть
    LAYER_MIXED = "L1-L5 (журнал)"   # что именно мерит форвард-машина
    now = int(time.time())
    _days = (dt.date.today() - dt.date.fromisoformat(DATA_ERA)).days
    _warm = " ⚠️ данные молодые, вердикты крепнут" if _days < 14 else ""
    out = [f"🧭 <b>ФОРВАРД-МАШИНА</b> · era {DATA_ERA} ({_days}д){_warm} · net%=profit−costs\n"]

    # ── VST: реальные деньги (истина) — по signal_type+direction ──
    vst = _cohort(c, "AND execution_mode='VST'", (), "signal_type || ' ' || direction")
    out.append("💰 <b>VST (реальные деньги)</b>")
    if vst:
        for k, n, wr, net, mfe in vst:
            out.append(f"  {_verdict(n, net)} <code>{k}</code> n={n} WR{wr:.0f}% net={net:+.2f}%")
        # запись трендовых точек
        for k, n, wr, net, _ in vst:
            c.execute("INSERT INTO forward_verdicts (ts,cohort,exec_mode,n,wr,net,verdict,layer,script) "
                      "VALUES (?,?,?,?,?,?,?,?,?)",
                      (now, k, "VST", n, wr, net, _verdict(n, net), LAYER_MIXED, "forward_machine.py"))
    else:
        out.append("  — нет закрытых VST в data-era")

    # ── SIM полигон: research — по signal_type ──
    out.append("\n🧪 <b>SIM полигон</b> (net, MFE-захват)")
    sim = _cohort(c, "AND execution_mode!='VST'", (), "signal_type")
    for k, n, wr, net, mfe in sim:
        mfe_s = f" cap{mfe:.0f}%" if mfe is not None else ""
        out.append(f"  {_verdict(n, net)} <code>{k}</code> n={n} WR{wr:.0f}% net={net:+.2f}%{mfe_s}")
        c.execute("INSERT INTO forward_verdicts (ts,cohort,exec_mode,n,wr,net,verdict,layer,script) "
                  "VALUES (?,?,?,?,?,?,?,?,?)",
                  (now, k, "SIM", n, wr, net, _verdict(n, net), LAYER_MIXED, "forward_machine.py"))

    # ── НИШИ: для источников с n≥MIN_N ищем лучший разрез (direction/regime) ──
    niche_lines = []
    for k, n, wr, net, mfe in sim:
        if n < MIN_N:
            continue
        for grp, lbl in (("direction", "dir"), ("regime", "rej")):
            sub = _cohort(c, f"AND execution_mode!='VST' AND signal_type=?", (k,), grp)
            good = [s for s in sub if s[1] >= 10 and s[3] is not None and s[3] > net + 0.15]
            for gk, gn, gwr, gnet, _ in good:
                niche_lines.append(f"  🎯 <code>{k}</code> в {lbl}=<b>{gk}</b>: "
                                   f"net={gnet:+.2f}% (vs общий {net:+.2f}%) n={gn}")
    if niche_lines:
        out.append("\n🔍 <b>Ниши</b> (источник живёт в подмножестве):")
        out.extend(niche_lines[:8])

    # ── REAL-MONEY гейт: чистые VST к порогу 30 + положителен ли net ──
    out.append("\n🚦 <b>Гейт реальных денег</b> (VST clean → 30)")
    gate = c.execute("""SELECT signal_type, COUNT(*) n,
               ROUND(AVG(profit_pct - COALESCE(costs_pct,0)), 3) net
        FROM simulated_trades WHERE status IN ('SL','TP','TSL') AND execution_mode='VST'
          AND created_at >= ? AND (features_json IS NULL OR features_json NOT LIKE '%ledger_mismatch%')
        GROUP BY signal_type ORDER BY n DESC""", (DATA_ERA,)).fetchall()
    if gate:
        for st, n, net in gate:
            pct = min(100, int(100 * n / GATE_N))
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            status = ("🟢 готов" if n >= GATE_N and net > NET_ALIVE else
                      "🔴 льёт" if net < -NET_ALIVE else "⏳ рано")
            out.append(f"  {bar} {n}/{GATE_N} <code>{st}</code> net={net:+.2f}% {status}")
    else:
        out.append("  — нет VST-сделок")

    text = "\n".join(out) + "\n\n#SYSTEM"
    print(text.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""))
    c.commit()
    c.close()
    try:
        from oko_feed.alerts import send_tg
        send_tg(text, channel="system")
    except Exception as e:
        print(f"[FORWARD] tg err: {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.parse_args()
    run(once=True)
