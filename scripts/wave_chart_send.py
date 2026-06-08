#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""WAVE-CHART: стандартный сигнал-чарт бота (свечи+WT+volume+уровни) → TG-канал.

Использует core.ui.chart_builder.build_signal_chart (тот же рендер, что бот шлёт в
сигналах — уровни/пивоты + WaveTrend-панель + volume). Caption: волновая фаза + SMC.

Использование:
  python scripts/wave_chart_send.py SUI --tf 1h
  python scripts/wave_chart_send.py XLM --tf 15m --chat -1001549739381
"""
import sys, os, argparse, asyncio
sys.path.insert(0, r"e:/MTF BOT/CURSOR/crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv()
import ccxt, pandas as pd, requests
from core.ui.chart_builder import build_signal_chart
from core.smc.smc_engine import (zigzag_atr, detect_elliott_impulse,
                                  detect_structure_breaks, _zz_typed)

DEFAULT_CHAT = "-1001549739381"  # Oko - Alerts


def wave_smc_caption(sym, tf, ex):
    """Полный сигнал-вердикт: волна + OTE-зона + конфлюэнция + вход/SL/TP/RR + SMC."""
    try:
        from core.smc.smc_engine import _zz_typed, detect_equal_levels
        from core.indicators.indicators import calculate_pivot_points
        o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", tf, limit=150)
        df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
        price = df["close"].iloc[-1]
        # волна
        li = None
        for d in (3.0, 5.0):
            for imp in detect_elliott_impulse(zigzag_atr(df, 11, d)):
                if li is None or imp["waves"][-1][0] > li["waves"][-1][0]:
                    li = imp
        wave = (f"импульс {'ВНИЗ ↓' if li['direction']=='down' else 'ВВЕРХ ↑'}"
                f"{' ✓textbook' if li['textbook'] else ''}") if li else "коррекция/боковик"
        # SMC
        brks = detect_structure_breaks(df, length=5)
        smc = f"{brks[-1].kind} {brks[-1].direction}{'+V' if brks[-1].has_volume else ''}" if brks else "—"
        # OTE-зона последнего движения (Фибо)
        typed = _zz_typed(zigzag_atr(df, 11, 3.0))
        ote, direction = {}, None
        if len(typed) >= 2:
            (_ia, _pa, _ta), (_ib, _pb, _tb) = typed[-2], typed[-1]
            rng = _pb - _pa
            if abs(rng) / price > 0.003:
                for f in (0.618, 0.705, 0.786):
                    ote[f] = _pb - f * rng
                direction = "LONG" if _tb == "H" else "SHORT"  # откат после H = LONG-сетап
        # 4h-пивоты (для конфлюэнции)
        h4 = {}
        try:
            o4 = ex.fetch_ohlcv(f"{sym}/USDT:USDT", "4h", limit=3)
            d4 = pd.DataFrame(o4, columns=["ts", "h2", "h", "l", "c", "v"]); pr = d4.iloc[-2]
            h4 = calculate_pivot_points(float(pr["h"]), float(pr["l"]), float(pr["c"]))
        except Exception:
            pass
        # конфлюэнция Фибо × 4h-пивот (<0.5%)
        confl = []
        for f, flvl in ote.items():
            for pk, pv in h4.items():
                if abs(flvl - pv) / price < 0.005:
                    confl.append(f"{f}×4h-{pk} @{(flvl+pv)/2:.5f}")
        # MTF-OTE контекст: направление + OTE-зона по СТАРШИМ ТФ (основа сетапа)
        mtf = []
        _d_ote, _d_dir = {}, None  # daily OTE-уровни 0.618/0.705/0.786 (для вердикта «след. зона»)
        for _mtf in ("1d", "4h", "1h"):
            try:
                _om = ex.fetch_ohlcv(f"{sym}/USDT:USDT", _mtf, limit=150)
                _dm = pd.DataFrame(_om, columns=["ts", "open", "high", "low", "close", "volume"])
                _tm = _zz_typed(zigzag_atr(_dm, 11, 3.0))
                if len(_tm) >= 2:
                    (_a, _pa2, _ta2), (_b2, _pb2, _tb2) = _tm[-2], _tm[-1]
                    _dr = "LONG" if _tb2 == "H" else "SHORT"
                    _rg2 = _pb2 - _pa2
                    _olo, _ohi = _pb2 - 0.786 * _rg2, _pb2 - 0.618 * _rg2
                    _was = "✓был" if (_mtf in ("1d", "4h") and _dm["low"].min() <= min(_olo, _ohi)) else ""
                    mtf.append(f"{_mtf} {_dr}{_was}")
                    if _mtf == "1d":
                        _d_dir = _dr
                        for _ff in (0.618, 0.705, 0.786):
                            _d_ote[_ff] = _pb2 - _ff * _rg2
            except Exception:
                pass
        # MTF bias по СТАРШИМ ТФ (1d/4h) — определяет приоритетный сценарий
        _htf = [m for m in mtf if m.startswith("1d") or m.startswith("4h")]
        _nl = sum("LONG" in m for m in _htf); _ns = sum("SHORT" in m for m in _htf)
        _bias = "LONG" if _nl > _ns else ("SHORT" if _ns > _nl else "MIX")
        # SL = БЛИЖАЙШИЙ swing к цене (компактная инвалидация, не дальняя вершина/дно)
        _below = [p for _, p, t in typed if t == "L" and p < price]
        _above = [p for _, p, t in typed if t == "H" and p > price]
        _slL = (max(_below) * 0.998) if _below else price * 0.985
        _slS = (min(_above) * 1.002) if _above else price * 1.015
        # TP = ЗНАЧИМЫЕ цели: daily-пивоты + дневная Фибо (ДАЛЬШЕ интрадей-мелочи)
        _dp = {}
        _dhi = _dlo = None
        try:
            _o1 = ex.fetch_ohlcv(f"{sym}/USDT:USDT", "1d", limit=20)
            _d1 = pd.DataFrame(_o1, columns=["t", "o", "h", "l", "c", "v"]); _pp1 = _d1.iloc[-2]
            _dp = calculate_pivot_points(float(_pp1["h"]), float(_pp1["l"]), float(_pp1["c"]))
            _dhi, _dlo = float(_d1["h"].max()), float(_d1["l"].min())  # потолок/пол старшего ТФ
        except Exception:
            pass
        # ЦЕЛИ = 4h+daily пивоты + daily high/low (СУТЬ MTF: цель старшего ТФ = ДАЛЬНЯЯ)
        _allT = {**h4, **_dp}
        _upsT = sorted(v for v in list(_allT.values()) + ([_dhi] if _dhi else []) if v > price * 1.005)
        _dnsT = sorted((v for v in list(_allT.values()) + ([_dlo] if _dlo else []) if v < price * 0.995), reverse=True)
        _tpL = _upsT[0] if _upsT else price * 1.03            # TP1 = ближняя фиксация
        _tpLf = _upsT[-1] if _upsT else price * 1.10          # TP2 = ДАЛЬНЯЯ цель старшего ТФ
        _tpS = _dnsT[0] if _dnsT else price * 0.97
        _tpSf = _dnsT[-1] if _dnsT else price * 0.90
        # приоритетный сценарий = РАННЕР (дальняя цель старшего ТФ); контр-тренд = откат (ближняя)
        _tgtL = _tpLf if _bias != "SHORT" else _tpL
        _tgtS = _tpSf if _bias == "SHORT" else _tpS
        _rrL = abs(_tgtL - price) / abs(price - _slL) if price != _slL else 0
        _rrS = abs(_tgtS - price) / abs(_slS - price) if _slS != price else 0
        # вердикт (сценарное мышление: что делать + что если не прав → СЛЕД. daily OTE-зона)
        _fname = {0.618: "0.618", 0.705: "0.705", 0.786: "0.786"}
        if _bias == "LONG":
            # след. зона = ближайшая daily OTE НИЖЕ цены (более глубокий откат, обычно там OB)
            _deeper = [(f, l) for f, l in sorted(_d_ote.items(), reverse=True) if l < price * 0.998]
            if _deeper:
                _f0, _l0 = _deeper[0]
                _verdict = f"тренд ↑ → ПРИОРИТЕТ LONG. Ниже SL → след. daily OTE {_fname[_f0]} ≈ {_l0:.5f} (ищи OB)"
            else:
                _verdict = "тренд ↑ → ПРИОРИТЕТ LONG. Ниже SL: откат глубже целевой OTE, ждать"
        elif _bias == "SHORT":
            _higher = [(f, l) for f, l in sorted(_d_ote.items()) if l > price * 1.002]
            if _higher:
                _f0, _l0 = _higher[0]
                _verdict = f"тренд ↓ → ПРИОРИТЕТ SHORT. Выше SL → след. daily OTE {_fname[_f0]} ≈ {_l0:.5f}"
            else:
                _verdict = "тренд ↓ → ПРИОРИТЕТ SHORT. Выше SL: разворот, искать LONG"
        else:
            _verdict = "MTF разнобой → НЕ торопиться, ждать согласования старших ТФ"
        # 🧲 ЗОНЫ-МАГНИТЫ: HTF-FVG (1d/4h активные) × weekly/daily пивот = конфлюэнт спрос/предложение
        # (та же формула FVG что у магнитов бота build_smc_snapshot → TPSelector; здесь — для подписи)
        _zones = []
        try:
            from core.smc.smc_engine import detect_fvg as _dfz
            _ow = ex.fetch_ohlcv(f"{sym}/USDT:USDT", "1w", limit=3)
            _dw = pd.DataFrame(_ow, columns=["t", "o", "h", "l", "c", "v"]); _pw = _dw.iloc[-2]
            _wp = calculate_pivot_points(float(_pw["h"]), float(_pw["l"]), float(_pw["c"]))
            _piv_all = {**{f"W:{k}": v for k, v in _wp.items()}, **{f"D:{k}": v for k, v in _dp.items()}}
            for _htf in ("1d", "4h"):
                _oh = ex.fetch_ohlcv(f"{sym}/USDT:USDT", _htf, limit=200)
                _dh = pd.DataFrame(_oh, columns=["ts", "open", "high", "low", "close", "volume"])
                _dh.index = pd.to_datetime(_dh["ts"], unit="ms")
                for _fz in _dfz(_dh):
                    if _fz[5] is not None:          # mitigated — пропуск
                        continue
                    _ft, _fb, _fk = _fz[1], _fz[2], _fz[3]
                    _fmid = (_ft + _fb) / 2
                    if abs(_fmid - price) / price > 0.12:
                        continue
                    for _pn, _pv in _piv_all.items():
                        if min(_ft, _fb) <= _pv <= max(_ft, _fb) or abs(_fmid - _pv) / price < 0.008:
                            _side = "спрос" if _fk == "bull" else "предложение"
                            _zones.append((abs(_fmid - price),
                                           f"{_htf} {_fk}-FVG×{_pn} {min(_fb,_ft):.5f}–{max(_fb,_ft):.5f} ({_side})"))
                            break
            _zones.sort()
        except Exception:
            pass
        # ── сборка (быстрое чтение) ──
        _ar = lambda d: "📈" if "LONG" in d else "📉"
        L = [f"🌊 <b>{sym}</b> · {tf} · <code>{price:.5f}</code>"]
        if mtf:
            L.append("📊 MTF:  " + "   ".join(f"{m.split()[0]}{_ar(m)}{'✓' if '✓был' in m else ''}" for m in mtf))
        L.append(f"〰️ {wave}  ·  SMC: {smc} ({tf})")
        L.append("━━━━━━━━━━━━━━")
        _tagL = " ⭐ПРИОРИТЕТ" if _bias == "LONG" else (" ⚠️контр-тренд" if _bias == "SHORT" else "")
        _tagS = " ⭐ПРИОРИТЕТ" if _bias == "SHORT" else (" ⚠️контр-тренд" if _bias == "LONG" else "")
        # приоритет = раннер (TP1⟶TP2 дальняя цель), контр-тренд = откат (только ближняя TP)
        _ltp = (f"TP <code>{_tpL:.5f}</code> ⟶ <code>{_tpLf:.5f}</code>" if _bias != "SHORT"
                else f"TP <code>{_tpL:.5f}</code>")
        _stp = (f"TP <code>{_tpS:.5f}</code> ⟶ <code>{_tpSf:.5f}</code>" if _bias == "SHORT"
                else f"TP <code>{_tpS:.5f}</code>")
        L.append(f"🟢 <b>LONG</b>{_tagL}  →  {_ltp}")
        L.append(f"     SL <code>{_slL:.5f}</code>  ·  RR <b>1:{_rrL:.1f}</b>")
        L.append(f"🔴 <b>SHORT</b>{_tagS}  →  {_stp}")
        L.append(f"     SL <code>{_slS:.5f}</code>  ·  RR <b>1:{_rrS:.1f}</b>")
        L.append("━━━━━━━━━━━━━━")
        if ote:
            _iz = min(ote[0.786], ote[0.618]) <= price <= max(ote[0.786], ote[0.618])
            L.append(f"🌀 OTE {direction}: <code>{ote[0.618]:.5f}–{ote[0.786]:.5f}</code>{' ✅В ЗОНЕ' if _iz else ''}")
        if confl:
            L.append("⭐ Conf: " + " · ".join(confl[:2]))
        if _zones:
            L.append("🧲 Зоны: " + "  ·  ".join(z for _, z in _zones[:2]))
        L.append(f"📍 {_verdict}")
        return "\n".join(L)
    except Exception as e:
        return f"🌊 {sym} {tf} (caption err: {str(e)[:50]})"


def send_tg(png_bytes, caption, chat, token):
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    r = requests.post(url, data={"chat_id": chat, "caption": caption, "parse_mode": "HTML"},
                      files={"photo": ("chart.png", png_bytes)}, timeout=30)
    return r.json()


def send_media_group(media_list, caption, chat, token):
    """media_list = [(tf, png_bytes)]. Несколько чартов ОДНИМ постом (мульти-TF фрактал)."""
    import json
    url = f"https://api.telegram.org/bot{token}/sendMediaGroup"
    media, files = [], {}
    for i, (tf, png) in enumerate(media_list):
        files[f"file{i}"] = (f"{tf}.png", png)
        m = {"type": "photo", "media": f"attach://file{i}"}
        if i == 0:  # caption на первом фото = подпись всего альбома
            m["caption"] = caption; m["parse_mode"] = "HTML"
        media.append(m)
    r = requests.post(url, data={"chat_id": chat, "media": json.dumps(media)},
                      files=files, timeout=60)
    return r.json()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--tfs", default="5m,15m,1h",
                    help="ТФ через запятую (мульти-TF одним постом). Один ТФ = одиночный чарт.")
    ap.add_argument("--chat", default=DEFAULT_CHAT)
    a = ap.parse_args()
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("TELEGRAM_TOKEN не найден в .env"); return
    sym = a.symbol.upper()
    full = f"{sym}/USDT:USDT"
    tfs = [t.strip() for t in a.tfs.split(",") if t.strip()]
    ex = ccxt.bingx()
    # caption по СТАРШЕМУ ТФ (контекст) — последний в списке
    cap = wave_smc_caption(sym, tfs[-1], ex)
    cap = f"{cap}\n📊 мульти-TF: {' · '.join(tfs)}"
    # рендерим чарты на каждом ТФ
    media = []
    for tf in tfs:
        png = await build_signal_chart(full, tf, bot=None, wave_overlay=True)
        if png:
            media.append((tf, png))
        else:
            print(f"  {tf}: не построился (blacklist/нет данных)")
    if not media:
        print(f"ни один чарт не построился для {sym}"); return
    if len(media) == 1:
        resp = send_tg(media[0][1], cap, a.chat, token)
    else:
        resp = send_media_group(media, cap, a.chat, token)
    ok = resp.get("ok") if isinstance(resp, dict) else False
    print(f"TG: {'✅ отправлено '+str(len(media))+' чарт(ов)' if ok else '❌ '+str(resp)[:80]}")


if __name__ == "__main__":
    asyncio.run(main())
