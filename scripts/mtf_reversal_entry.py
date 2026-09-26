# -*- coding: utf-8 -*-
"""Вход в РАЗВОРОТ старшего ТФ по слому МЛАДШЕГО порядка (гипотеза Егора, 03.09.2026).

    «поиск входа на младшем для сетапа старшего порядка — для сокращения SL,
     входов в продолжение и сопровождения по направлению старшего»
    «входы в развороты старшего по сломам младшего порядка»

Механика:
  1. СТАРШИЙ (1h/4h): CHoCH эталона OKO-SM = смена характера, заявка на разворот.
     Уровень слома → точка ИНВАЛИДАЦИИ (за неё ставится стоп).
  2. МЛАДШИЙ (15m): в окне после CHoCH ждём слом В СТОРОНУ нового направления.
  3. Вход на баре ПОСЛЕ подтверждения слома младшего.
  4. Стоп — ЗА уровнем инвалидации СТАРШЕГО, один и тот же для всех вариантов.

🔴 Почему стоп общий. Закон проекта: «весь эдж в РАЗМЕРЕ стопа», а тугой стоп —
задокументированный корень живого убытка (ote_nested: медиана 0.61%, +1002R
брутто → −1630% после костов). Поэтому сокращение SL проверяется ЧЕСТНО: не
подтягиванием стопа, а лучшей ЦЕНОЙ входа при той же защите. Если вход на 15m
ближе к инвалидации — стоп в % цены меньше сам собой, и вопрос лишь в том,
окупает ли это потерю части хода.

Сравниваем при ОДНОМ уровне стопа:
  A `htf_now`  — вход сразу на закрытии бара CHoCH старшего (базовая линия);
  B `ltf_break`— вход по слому младшего в окне (гипотеза);
  C `random`   — случайный бар внутри того же окна (контроль, закон о контрольной группе).

Выходы — два, считаются для каждого варианта:
  · `fix`   — цель RR×риск;
  · `trail` — сопровождение ДО ОБРАТНОГО слома старшего (то самое «сопровождение
              по направлению старшего»), с той же защитой.

Причинность: бар старшего доступен только ПОСЛЕ закрытия; вход на младшем — строго
по времени позже. Проверяется сопоставлением timestamp, а не индексов.

Запуск: python scripts/mtf_reversal_entry.py [n_symbols] [htf] [ltf]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from research_harness import load, universe, COST_LIMIT  # noqa: E402

WINDOW_BARS = 32      # окно ожидания входа на младшем после CHoCH старшего
MAX_HOLD = 192        # предел удержания (баров младшего)
RR = 2.0              # цель для варианта `fix`
STOP_PAD = 0.25       # запас за уровень инвалидации, в ATR младшего
WARMUP = 400
LTF_STOP_LOOKBACK = 12   # баров младшего для локального экстремума под стоп


def _atr(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def _run(df: pd.DataFrame, swing_len=50, internal_len=5):
    from core.smc.oko_sm_engine import run_structure
    return run_structure(df.reset_index(drop=True), swing_len=swing_len,
                         internal_len=internal_len, record_legs=False)


def _simulate(dl, atr_l, entry_bar, up, stop_price, htf_rev_bar, mode):
    """Одна сделка. stop_price — общий уровень инвалидации старшего.
    htf_rev_bar — бар младшего, где старший сломался ОБРАТНО (для trail)."""
    n = len(dl)
    if entry_bar < WARMUP or entry_bar + 2 >= n:
        return None
    o, h, l, c = dl.open.values, dl.high.values, dl.low.values, dl.close.values
    e = float(o[entry_bar])
    d = 1.0 if up else -1.0
    sl = stop_price - d * STOP_PAD * atr_l[entry_bar]
    risk = (e - sl) * d
    if risk <= 0:
        return None                      # цена уже за инвалидацией — сетап мёртв
    tp = e + d * RR * risk
    limit = min(entry_bar + MAX_HOLD, n - 1)
    if mode == "trail" and htf_rev_bar is not None:
        limit = min(limit, htf_rev_bar)
    for j in range(entry_bar, limit + 1):
        if (l[j] <= sl) if up else (h[j] >= sl):
            return (sl - e) / e * 100 * d - COST_LIMIT, risk / e * 100
        if mode == "fix" and ((h[j] >= tp) if up else (l[j] <= tp)):
            return (tp - e) / e * 100 * d - COST_LIMIT, risk / e * 100
    x = float(c[limit])
    return (x - e) / e * 100 * d - COST_LIMIT, risk / e * 100


def build(sym: str, htf: str, ltf: str) -> list[dict]:
    dh, dl = load(sym, htf), load(sym, ltf)
    if len(dh) < 1200 or len(dl) < 6000:
        return []
    sh, sl_ = _run(dh), _run(dl)
    atr_l = _atr(dl.reset_index(drop=True))
    dlr = dl.reset_index(drop=True)
    th, tl = dh.index.values, dl.index.values

    # события старшего: CHoCH любого слоя = заявка на разворот
    htf_ev = [e for e in sh.events if e.kind == "CHoCH"]
    # сломы младшего, по бару
    ltf_by_bar: dict[int, list] = {}
    for e in sl_.events:
        ltf_by_bar.setdefault(e.i, []).append(e)

    out = []
    rng = np.random.default_rng(abs(hash(sym)) % (2 ** 32))
    for k, ev in enumerate(htf_ev):
        if ev.i + 1 >= len(th):
            continue
        # 🔴 причинность: бар старшего ЗАКРЫТ → берём время СЛЕДУЮЩЕГО бара старшего
        t_avail = th[ev.i + 1]
        start = int(np.searchsorted(tl, t_avail, side="left"))
        if start < WARMUP or start + WINDOW_BARS >= len(dlr):
            continue
        up = ev.bull
        stop_price = float(ev.level)          # уровень, сломанный старшим = инвалидация

        # бар младшего, где старший сломался ОБРАТНО (конец сопровождения)
        rev = None
        for nxt in htf_ev[k + 1:]:
            if nxt.bull != up:
                if nxt.i + 1 < len(th):
                    rev = int(np.searchsorted(tl, th[nxt.i + 1], side="left"))
                break

        # B: первый слом младшего В СТОРОНУ разворота внутри окна.
        # 🔴 Слои РАЗДЕЛЕНЫ (Егор, 03.09): микроструктура появилась вторым слоем
        # уже ПОСЛЕ прежних MTF-замеров — те мерились детектором, видевшим 1.3%
        # сломов. Поэтому «на 15m вложенность не работает» перемеряется, а не
        # принимается на веру: закон «находок нет = НЕТ ПРИЗНАКА».
        b_swing = b_micro = None
        for j in range(start, start + WINDOW_BARS):
            for e2 in ltf_by_bar.get(j, ()):
                if e2.bull != up:
                    continue
                if e2.internal and b_micro is None:
                    b_micro = j + 1
                if not e2.internal and b_swing is None:
                    b_swing = j + 1
            if b_swing is not None and b_micro is not None:
                break

        variants = {
            "A_htf_now": start,
            "B_ltf_swing": b_swing,
            "B_ltf_micro": b_micro,
            "C_random": int(rng.integers(start, start + WINDOW_BARS)),
        }
        lo_v, hi_v = dlr.low.values, dlr.high.values
        for name, bar in variants.items():
            if bar is None:
                continue
            # 🔴 ДВЕ школы стопа — главная ось гипотезы «сокращение SL».
            #  htf — за уровнем инвалидации СТАРШЕГО (защита сетапа целиком);
            #  ltf — за локальным экстремумом МЛАДШЕГО перед входом (компактный).
            # Ожидание подтверждения уводит цену ОТ уровня старшего, поэтому у
            # варианта htf стоп в % РАСТЁТ с задержкой входа — сократить его
            # может только структура младшего. Проверяем, а не предполагаем:
            # закон «тугой стоп + косты = убыток» проверен на ДРУГОЙ механике.
            k0 = max(0, bar - LTF_STOP_LOOKBACK)
            stops = {
                "htf": stop_price,
                "ltf": (float(lo_v[k0:bar].min()) if up else float(hi_v[k0:bar].max()))
                if bar > k0 else stop_price,
            }
            for smode, sp in stops.items():
                for mode in ("fix", "trail"):
                    r = _simulate(dlr, atr_l, bar, up, sp, rev, mode)
                    if r is None:
                        continue
                    pnl, stop_pct = r
                    out.append({"sym": sym, "variant": name, "mode": mode,
                                "stop_school": smode,
                                "side": "long" if up else "short",
                                "year": int(pd.Timestamp(tl[bar]).year),
                                "pnl": pnl, "stop_pct": stop_pct,
                                "delay": bar - start,
                                # 🔴 ключ сетапа: без него нельзя отличить «лучший
                                # ВХОД» от «другого НАБОРА сетапов». Вариант B
                                # существует только там, где младший подтвердил в
                                # окне — то есть уже на подмножестве.
                                "setup": f"{sym}#{k}",
                                "has_swing": b_swing is not None,
                                "has_micro": b_micro is not None})
    return out


def _line(tag: str, R: pd.DataFrame) -> None:
    if R.empty:
        print(f"{tag:26s} — пусто")
        return
    p = R.pnl.values
    frag = np.sort(p)[:-max(1, len(p) // 10)].sum()
    cov = (R.groupby("sym").pnl.sum() > 0).mean() * 100
    w, l_ = p[p > 0].sum(), -p[p < 0].sum()
    pf = w / l_ if l_ > 0 else float("inf")
    print(f"{tag:26s} n={len(p):6d} WR {(p > 0).mean()*100:4.1f}% PF {pf:5.2f} "
          f"ср {p.mean():+7.3f}% мед {np.median(p):+7.3f}% "
          f"стоп {R.stop_pct.median():5.2f}% безтоп10% {frag:+9.1f}% монет+ {cov:4.0f}%")


def main() -> None:
    n_sym = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    htf = sys.argv[2] if len(sys.argv) > 2 else "1h"
    ltf = sys.argv[3] if len(sys.argv) > 3 else "15m"
    syms = universe(ltf, n=n_sym)
    print(f"вселенная {len(syms)} монет · старший {htf} → младший {ltf} · косты {COST_LIMIT}%")
    print(f"окно входа {WINDOW_BARS} баров · стоп ЗА уровнем инвалидации старшего (+{STOP_PAD} ATR)\n")

    rows = []
    for i, s in enumerate(syms, 1):
        try:
            rows += build(s, htf, ltf)
        except Exception as e:  # noqa: BLE001
            print(f"  [{s}] {type(e).__name__}: {str(e)[:60]}")
        if i % 5 == 0:
            print(f"  ... {i}/{len(syms)} · {len(rows)}", flush=True)
    R = pd.DataFrame(rows)
    if R.empty:
        print("НОЛЬ сделок — это отказ, а не вывод.")
        return
    print(f"\nсобрано {len(R)} · монет {R.sym.nunique()}\n")

    VARS = ("A_htf_now", "B_ltf_swing", "B_ltf_micro", "C_random")
    for smode in ("htf", "ltf"):
        for mode in ("fix", "trail"):
            head = ("за инвалидацией СТАРШЕГО" if smode == "htf"
                    else f"за экстремумом МЛАДШЕГО ({LTF_STOP_LOOKBACK} баров)")
            tail = "цель 2R" if mode == "fix" else "сопровождение до ОБРАТНОГО слома старшего"
            print(f"{'='*118}\nСТОП: {head}   ·   ВЫХОД: {tail}\n{'='*118}")
            M = R[(R["mode"] == mode) & (R["stop_school"] == smode)]
            for v in VARS:
                _line(v, M[M.variant == v])
            print()

    print(f"{'='*118}\nЛУЧШАЯ КЛЕТКА — срезы (вердикт по общей строке запрещён)\n{'='*118}")
    best = None
    for smode in ("htf", "ltf"):
        for mode in ("fix", "trail"):
            for v in VARS:
                M = R[(R["mode"] == mode) & (R["stop_school"] == smode) & (R.variant == v)]
                if len(M) < 300:
                    continue
                p_ = M.pnl.values
                w, l_ = p_[p_ > 0].sum(), -p_[p_ < 0].sum()
                pf = w / l_ if l_ > 0 else 0.0
                if best is None or pf > best[0]:
                    best = (pf, smode, mode, v, M)
    if best is not None:
        pf, smode, mode, v, M = best
        print(f"лучшая: {v} · стоп {smode} · выход {mode} · PF {pf:.2f}\n")
        for sd in ("long", "short"):
            _line(f"  {sd}", M[M.side == sd])
        for y in sorted(M.year.unique()):
            _line(f"  {y}", M[M.year == y])

    # ── РЕШАЮЩАЯ ПРОВЕРКА: лучший ВХОД или другой НАБОР сетапов? ──────────
    # B существует лишь там, где младший подтвердил в окне. Значит сравнивать
    # с A «в лоб» нельзя: разница может быть отбором сетапов, а не входом.
    # Сравниваем A и B на ОДНОМ И ТОМ ЖЕ множестве сетапов.
    print(f"\n{'='*118}\nЛУЧШИЙ ВХОД или ДРУГОЙ НАБОР СЕТАПОВ? (одно множество)\n{'='*118}")
    for smode in ("htf", "ltf"):
        for mode in ("fix", "trail"):
            M = R[(R["mode"] == mode) & (R["stop_school"] == smode)]
            for flag, vb in (("has_swing", "B_ltf_swing"), ("has_micro", "B_ltf_micro")):
                sub = M[M[flag]]
                a = sub[sub.variant == "A_htf_now"]
                b = sub[sub.variant == vb]
                c = sub[sub.variant == "C_random"]
                if len(b) < 200:
                    continue
                print(f"— стоп {smode} · выход {mode} · сетапы, где есть {vb}:")
                _line(f"    A на этом же", a)
                _line(f"    {vb}", b)
                _line(f"    C_random", c)
                print()
    print(f"{'вариант':14s} {'стоп htf':>10s} {'стоп ltf':>10s} {'сокращение':>12s} {'задержка':>10s}")
    for v in VARS:
        sh_ = R[(R.variant == v) & (R.stop_school == "htf")].stop_pct.median()
        sl2 = R[(R.variant == v) & (R.stop_school == "ltf")].stop_pct.median()
        red = (1 - sl2 / sh_) * 100 if sh_ and sh_ > 0 else float("nan")
        d = R[R.variant == v].delay.median()
        print(f"{v:14s} {sh_:9.2f}% {sl2:9.2f}% {red:11.0f}% {d:9.0f} баров")


if __name__ == "__main__":
    main()
