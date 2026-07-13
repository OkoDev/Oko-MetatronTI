# -*- coding: utf-8 -*-
"""USDT.D РАЗВОРОТ-КАНДИДАТ — shadow-алерт (08.07, добро Егора «сделать!»).

Гейт atr_S2 (get_usdtd_risk_off) бинарный и запаздывающий: уровень vs MA20. Ранний маркер
разворота — мета-инсайт Егора 02-03.07: OKO-структура на САМОЙ доминации. Валидировано
исторически: дневной WT-кросс из OS на USDT.D опережает MA20-флип на 1-9 дней (6/6).

Сигналы (оба направления, decision-support — торговый гейт atr_S2 НЕ трогаем):
  🟠 ВВЕРХ  (→ risk-off близко, шорт-среда atr_S2): WT-кросс ВВЕРХ из OS(<-40)
            или ≥3 дней роста + дистанция до MA20 < 0.25пп (при risk-on).
  🟢 ВНИЗ   (→ risk-on/бык, среда лонгов Егора):    WT-кросс ВНИЗ из OB(>+40)
            или ≥3 дней падения + дистанция < 0.25пп (при risk-off).
Cooldown 24ч на направление. Ряд = usdtd_regime._series + live CG-замер (upsert
в usdtd_cg — тот же путь, что get_usdtd_risk_off). WT на чистом питоне (ряд ~300 точек).

Запуск: python scripts/usdtd_watch.py [--test]  (--test = метрики без TG/cooldown)
pm2:    pm2 start python --name usdtd-watch --no-autorestart --cron-restart "5 */4 * * *"
        -- scripts/usdtd_watch.py
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import sqlite3
import time
from datetime import datetime, timezone

from core.signals.usdtd_regime import _series, _fetch_cg_usdtd, _DB, _MA_LEN
from oko_feed.alerts import send_tg
from oko_feed.store import conn as feed_conn

OS_LEVEL, OB_LEVEL = -40.0, 40.0     # WT-зоны для доминации (параметр; валидация 6/6 была «из OS»)
STREAK_N = 3                         # дней подряд в одну сторону
NEAR_PP = 0.25                       # дистанция до MA20, пп
COOLDOWN = 24 * 3600


def _ema(vals: list[float], span: int) -> list[float]:
    a = 2.0 / (span + 1.0)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * a + out[-1] * (1 - a))
    return out


def _wt(closes: list[float]) -> tuple[list[float], list[float]]:
    """WaveTrend(10,21) на дневных close (ap=close: у ряда доминации нет high/low)."""
    esa = _ema(closes, 10)
    d = _ema([abs(c - e) for c, e in zip(closes, esa)], 10)
    ci = [(c - e) / (0.015 * dd) if dd > 1e-12 else 0.0 for c, e, dd in zip(closes, esa, d)]
    wt1 = _ema(ci, 21)
    wt2 = [wt1[0]] * 3 + [sum(wt1[i - 3:i + 1]) / 4 for i in range(3, len(wt1))]
    return wt1, wt2


def _cooldown_ok(key: str) -> bool:
    c = feed_conn()
    try:
        c.execute("CREATE TABLE IF NOT EXISTS alert_log (key TEXT PRIMARY KEY, ts INTEGER)")
        row = c.execute("SELECT ts FROM alert_log WHERE key=?", (key,)).fetchone()
        if row and time.time() - row[0] < COOLDOWN:
            return False
        c.execute("INSERT OR REPLACE INTO alert_log VALUES (?,?)", (key, int(time.time())))
        c.commit()
        return True
    finally:
        c.close()


def check(test: bool = False) -> str | None:
    conn = sqlite3.connect(_DB)
    try:
        val = _fetch_cg_usdtd()                        # live-замер → upsert (путь usdtd_regime)
        if val is not None:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            conn.execute("CREATE TABLE IF NOT EXISTS usdtd_cg (date TEXT PRIMARY KEY, value REAL)")
            conn.execute("INSERT OR REPLACE INTO usdtd_cg(date, value) VALUES (?, ?)", (today, val))
            conn.commit()
        ser = _series(conn)
    finally:
        conn.close()
    if len(ser) < _MA_LEN + 25:
        print("[USDTD-WATCH] ряда мало"); return None
    vals = [v for _, v in ser]
    cur = vals[-1]
    ma = sum(vals[-_MA_LEN:]) / _MA_LEN
    risk_off = cur > ma
    wt1, wt2 = _wt(vals)
    # кросс на последней точке: prev по одну сторону, now по другую
    cross_up = wt1[-2] <= wt2[-2] and wt1[-1] > wt2[-1]
    cross_dn = wt1[-2] >= wt2[-2] and wt1[-1] < wt2[-1]
    from_os = min(wt1[-2], wt1[-1]) < OS_LEVEL
    from_ob = max(wt1[-2], wt1[-1]) > OB_LEVEL
    streak_up = streak_dn = 0
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] > vals[i - 1] and streak_dn == 0:
            streak_up += 1
        elif vals[i] < vals[i - 1] and streak_up == 0:
            streak_dn += 1
        else:
            break
    dist = ma - cur                                    # >0 = ниже MA20 (risk-on), пп
    status = (f"USDT.D {cur:.3f}% · MA20 {ma:.3f}% ({'RISK-OFF' if risk_off else 'risk-on'}) · "
              f"WT {wt1[-1]:+.0f}/{wt2[-1]:+.0f} · streak +{streak_up}/-{streak_dn} · dist {dist:+.3f}пп")
    print(f"[USDTD-WATCH] {status}")

    up_wt = cross_up and from_os
    up_soft = (not risk_off) and streak_up >= STREAK_N and 0 < dist < NEAR_PP
    dn_wt = cross_dn and from_ob
    dn_soft = risk_off and streak_dn >= STREAK_N and 0 < -dist < NEAR_PP
    if up_wt or up_soft:
        why = " + ".join((["WT-кросс ВВЕРХ из OS (опережал MA20-флип 6/6, +1..9д)"] if up_wt else [])
                         + ([f"{streak_up} дней роста, до MA20 {dist:.2f}пп"] if up_soft else []))
        msg = (f"🟠 <b>USDT.D разворот-кандидат ВВЕРХ</b>\n\n"
               f"→ risk-off близко: шорт-среда atr_S2 просыпается\n{why}\n\n"
               f"{status}\n\n#USDTD #REGIME")
        if test:
            return msg
        if _cooldown_ok("usdtd_watch:UP"):
            send_tg(msg, channel="action")
            return "UP"
    if dn_wt or dn_soft:
        why = " + ".join((["WT-кросс ВНИЗ из OB"] if dn_wt else [])
                         + ([f"{streak_dn} дней падения, до MA20 {-dist:.2f}пп"] if dn_soft else []))
        msg = (f"🟢 <b>USDT.D разворот-кандидат ВНИЗ</b>\n\n"
               f"→ risk-on/бык: деньги выходят в альты (среда лонгов)\n{why}\n\n"
               f"{status}\n\n#USDTD #REGIME")
        if test:
            return msg
        if _cooldown_ok("usdtd_watch:DOWN"):
            send_tg(msg, channel="action")
            return "DOWN"
    return None


if __name__ == "__main__":
    r = check(test="--test" in sys.argv)
    if "--test" in sys.argv:
        print(r or "[USDTD-WATCH] условия алерта сейчас НЕ выполнены")
