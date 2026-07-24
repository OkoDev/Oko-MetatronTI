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


def _weekly_pivot(ser: list[tuple[str, float]]) -> dict | None:
    """Недельный floor-пивот из ДНЕВНОГО ряда доминации (H/L/C прошлой ISO-недели = агрегат
    дневных close). Егор читает «под недельным пивотом» — считаем тот же уровень автономно
    (без 1h TW). Формула OKO: S1/R1 со сдвигом 2.003/1.997 (сдвиг за свип)."""
    from datetime import date as _date
    weeks: dict = {}
    order: list = []
    for d, v in ser:
        try:
            y, m, dd = map(int, d.split("-"))
            k = _date(y, m, dd).isocalendar()[:2]
        except Exception:
            continue
        if k not in weeks:
            weeks[k] = []
            order.append(k)
        weeks[k].append(v)
    if len(order) < 2:
        return None
    prev = weeks[order[-2]]                       # прошлая ЗАВЕРШЁННАЯ неделя
    H, L, C = max(prev), min(prev), prev[-1]
    pp = (H + L + C) / 3
    return {"PP": pp, "R1": pp * 1.997 - L, "R2": pp + (H - L),
            "S1": pp * 2.003 - H, "S2": pp - (H - L)}


def _struct(vals: list[float]) -> dict:
    """Структура USDT.D через порт OKO-SM (ряд close → df, swings на close). Возвращает
    trend + ближайшее сопротивление/поддержку (swing) — «OB/полка» доминации без 1h."""
    try:
        import pandas as _pd
        from core.smc.oko_sm_engine import run_structure, current_leg
        df = _pd.DataFrame({"open": vals, "high": vals, "low": vals, "close": vals})
        df["time"] = range(len(df))
        st = run_structure(df)
        leg = current_leg(st)
        return {"trend": (leg or {}).get("trend"),
                "res": st.trail_up, "sup": st.trail_dn,
                "swing_top": st.top_y, "swing_btm": st.btm_y}
    except Exception as _e:
        return {"trend": None, "res": None, "sup": None}


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
    # ── STRUCTURE-AWARE (23.07, Егор «слепой MA20 vs структура»): недельный пивот + WT-кросс ──
    wpp = _weekly_pivot(ser)
    struct = _struct(vals)
    wt_up = wt1[-1] > wt1[-2]                           # моментум WT вверх/вниз
    below_pp = wpp is not None and cur < wpp["PP"]      # под недельным пивотом = крышка сверху
    ppd = (wpp["PP"] - cur) if wpp else None            # дистанция до недельного PP, пп
    pp_s = (f" · нед.PP {wpp['PP']:.3f}% ({'ПОД' if below_pp else 'НАД'}, {ppd:+.3f}пп)" if wpp else "")
    st_s = f" · структура USDT.D {struct.get('trend') or '—'}"
    status = (f"USDT.D {cur:.3f}% · MA20 {ma:.3f}% ({'RISK-OFF' if risk_off else 'risk-on'}) · "
              f"WT {wt1[-1]:+.0f}/{wt2[-1]:+.0f} ({'▲' if wt_up else '▼'}) · "
              f"streak +{streak_up}/-{streak_dn}{pp_s}{st_s}")
    print(f"[USDTD-WATCH] {status}")

    # ОТБОЙ у недельного (кейс Егора): USDT.D толкнулся вверх, но ПОД нед.PP и WT крестит/катит
    # вниз → доминация отбивается → risk-on ДЕРЖИТСЯ → лонги продолжаются.
    reject_up = (below_pp and streak_up >= 2 and abs(ppd) < NEAR_PP
                 and (cross_dn or not wt_up))
    # ПРОБОЙ вверх: USDT.D НАД нед.PP + WT вверх → risk-off ПОДТВЕРЖДАЕТСЯ (шорт-среда atr_S2).
    breakout_up = (not below_pp) and wt_up and (cross_up or streak_up >= STREAK_N)
    # РАННИЙ WT-кросс вверх из OS (опережал MA20-флип 6/6) — но ТОЛЬКО если не под явным отбоем.
    early_up = cross_up and from_os and wt_up and not below_pp
    # зеркало вниз: пробой поддержки / WT-кросс вниз из OB → risk-on/бык
    reject_dn = (not below_pp) and struct.get("sup") and streak_dn >= 2 and wt_up  # отбой от поддержки вверх=USDT.D растёт? нет
    early_dn = cross_dn and from_ob and (not wt_up)

    if breakout_up or early_up:
        why = ("USDT.D НАД недельным пивотом + WT▲ — пробой, risk-off подтверждается"
               if breakout_up else "WT-кросс ВВЕРХ из OS (опережал MA20-флип 6/6, +1..9д)")
        msg = (f"🟠 <b>USDT.D → RISK-OFF (структурно)</b>\n\n"
               f"→ шорт-среда atr_S2 просыпается\n{why}\n\n{status}\n\n#USDTD #REGIME")
        if test:
            return msg
        if _cooldown_ok("usdtd_watch:UP"):
            send_tg(msg, channel="action")
            return "UP"
    if reject_up or early_dn:
        why = ("USDT.D ОТБИЛСЯ от недельного пивота, WT▼ — доминация падает, risk-on держится"
               if reject_up else "WT-кросс ВНИЗ из OB — доминация разворачивается вниз")
        msg = (f"🟢 <b>USDT.D → RISK-ON держится (структурно)</b>\n\n"
               f"→ деньги остаются в альтах: среда ЛОНГОВ\n{why}\n\n{status}\n\n#USDTD #REGIME")
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
