"""
detector_visual.py — ВИЗУАЛЬНАЯ ПРОВЕРКА ДЕТЕКТОРОВ ГЛАЗАМИ.

Повод (Егор, 28.08.2026): «чувствую что каждую проверку будет необходимо
подтверждать визуально на графике моими глазами».

🔴 ЧЕТЫРЕ РЕДАКЦИИ, три первые — ошибка метода:
  1. рисовал свечи СВОИМ SVG → «всё не верно» + «у нас есть чарт билдер»;
  2. взял чарт-билдер, но КОНСТРУИРОВАЛ разметку вручную, решив что штатный
     `wave_overlay` даёт «кашу» → «чарт билдер уже всё умеет, не выдумывай»;
  3. убрал свою разметку СОВСЕМ, оставил голый overlay и цифры в подписи →
     «не вижу отрисовки Импульс/POC и C-01», «нужны ДВА графика, а не цифры
     и даты — так я ищу ещё дольше, по барам»;
  4. (эта) рисуем МОИ объекты, но ТОЛЬКО штатными механизмами чарт-билдера.

Механизмы `core/ui/chart_builder._render`, используются как есть:
    htf_fvg = [(label, top, bottom, kind, x_origin)]  → бокс зоны + midline 0.5
    okosm   = {leg, zone, levels, break}              → нога, зона, уровни, линия
    wave_overlay=True                                 → штатная разметка OKO-SM

    python scripts/detector_visual.py --symbol ARB/USDT --tf 15m
    http://localhost:8000/viz?symbol=ARB/USDT&tf=15m&cases=2
"""
from __future__ import annotations

import argparse
import base64
import html
import sys
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:      # noqa: BLE001
    pass

from research_harness import load                                   # noqa: E402
from core.ui import chart_builder as CB                             # noqa: E402
from detector_bench import smc_frame                                # noqa: E402


def pivots_for(df_1h: pd.DataFrame) -> tuple[dict, dict]:
    """
    🔴 ПИВОТЫ ПЕРЕДАЮТСЯ ЯВНО. В `_render` стоит
    `if daily_pivots is None: daily_pivots = _calc_daily_pivots(df)`, но функций
    `_calc_daily_pivots` / `_calc_weekly_pivots` в модуле НЕТ — вызов без пивотов
    падает с NameError (значит и `build_deep_chart` с дефолтами). Боевой путь
    `build_signal_chart` не задет: он считает их сам и передаёт.
    """
    try:
        return CB._calc_pivot_levels(df_1h)
    except Exception:                                               # noqa: BLE001
        return {}, {}


def png(df_win: pd.DataFrame, symbol: str, tf: str, *,
        htf_fvg=None, okosm=None, pivots=(None, None), wave=True,
        choch_length=None, choch_length_major=None) -> str | None:
    """
    Рендер ШТАТНЫМ chart_builder → data URI.

    🔴 `htf_fvg` работает ТОЛЬКО при `wave_overlay=True` — его блок лежит внутри
    `if wave_overlay:`. Без этого зона молча не рисуется, а график выглядит целым.
    `okosm` наоборот — верхний уровень, работает и без overlay.
    """
    d = df_win.copy()
    if "wt1" not in d.columns:
        d = CB._calculate_wt(d)
    dp, wp = pivots
    try:
        raw = CB._render(d, symbol, tf,
                         daily_pivots=dp if dp is not None else {},
                         weekly_pivots=wp if wp is not None else {},
                         wave_overlay=wave, htf_fvg=htf_fvg, okosm=okosm,
                         choch_length=choch_length,
                         choch_length_major=choch_length_major)
    except Exception as e:                                          # noqa: BLE001
        print(f"  рендер упал: {type(e).__name__}: {str(e)[:70]}")
        return None
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def utc(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M")


def coords_line(symbol, tf, ts_from, ts_to, ts_event, label="событие"):
    """Координаты окна: «ты строишь, я открываю актив, тф и смотрю глазами»."""
    return (f'<span class="c-sym">{html.escape(symbol)}</span>'
            f'<span class="c-tf">{html.escape(tf)}</span>'
            f'<span class="c-win">окно {utc(ts_from)} → {utc(ts_to)} UTC</span>'
            f'<span class="c-evt">{label}: <b>{utc(ts_event)} UTC</b></span>')


def card(src, caption, coords=""):
    if not src:
        return ""
    c = f'<p class="coords">{coords}</p>' if coords else ""
    return (f'<figure class="card"><img src="{src}" alt="график с разметкой" loading="lazy">'
            f'{c}<figcaption>{caption}</figcaption></figure>')


def panel(title, sub, question, cards, pair=False):
    cls = "grid pair" if pair else "grid"
    return (f'<section class="panel"><header class="ph"><h2>{html.escape(title)}</h2>'
            f'<p class="sub">{sub}</p><p class="q">'
            f'<span class="qlabel">смотреть на</span> {question}</p></header>'
            f'<div class="{cls}">{"".join(cards)}</div></section>')


def build(symbol: str, tf: str, bars: int, n_cases: int):
    df = load(symbol, tf).tail(bars)
    dfi = df.reset_index(drop=True)
    d = smc_frame(dfi)
    try:
        h1 = load(symbol, "1h").tail(600)
    except Exception:                                               # noqa: BLE001
        h1 = df
    PIV = pivots_for(h1)

    def ms(k):
        return int(pd.Timestamp(df.index[k]).value // 1_000_000)

    panels = []

    # ── FVG: МОЯ зона боксом через штатный htf_fvg ────────────────────────────
    # Егор подтвердил обе размеченные зоны как настоящие, но на графике их не было:
    # `wave_overlay` рисует только АКТУАЛЬНЫЕ (неперекрытые) FVG, а мои перекрыты.
    # Подпись говорила про одну зону, картинка показывала другую — рассогласование.
    from core.smc.smc_engine import detect_fvg
    ev = [e for e in detect_fvg(d) if 60 < int(e[4]) < len(dfi) - 6]
    cards = []
    for e in ev[-n_cases:]:
        i = int(e[4]); top, btm, kind = float(e[1]), float(e[2]), str(e[3])
        mit = int(e[5]) if len(e) > 5 else -1
        a = max(0, i - 45); b = min(len(dfi), i + 22)
        zone = [("bull" if kind.startswith("bull") else "bear", top, btm, "bull" if kind.startswith("bull") else "bear", i - a)]
        status = (f"🔴 ПЕРЕКРЫТ {utc(df.index[mit])}" if 0 <= mit < len(dfi)
                  else "🟢 не перекрыт, актуален")
        cards.append(card(
            png(df.iloc[a:b], symbol, tf, htf_fvg=zone, pivots=PIV, wave=True),
            f"{html.escape(kind)} · зона <b>{btm:.6g} – {top:.6g}</b> · {status}<br>"
            f"свечи разрыва: {utc(df.index[i-2])} / {utc(df.index[i-1])} / {utc(df.index[i])}",
            coords_line(symbol, tf, df.index[a], df.index[b - 1], df.index[i],
                        "третья свеча разрыва")))
    panels.append(panel(
        "FVG — разрыв цены",
        "детектор core/smc/smc_engine.py:540 · МОЯ зона нарисована боксом через "
        "штатный htf_fvg, рядом обычная разметка OKO-SM",
        "бокс с подписью FVG — зона, которую нашёл детектор. По канону ICT бычий FVG "
        "лежит между <b>High первой</b> и <b>Low третьей</b> свечи. 🔑 Перекрытые зоны "
        "штатный overlay не рисует как неактуальные — поэтому раньше их не было видно; "
        "теперь статус подписан явно.",
        cards))

    # ── ДВЕ СТРУКТУРЫ НА ОДНОМ ГРАФИКЕ (метод Егора len5/len50) ─────────────
    # 🔴 Я весь день разбирал это как БАГ («50 слепое, надо 5»). Егор поправил:
    # «если нарисовать оба length на одном тф графика, получится две структуры,
    # старшая и младшая». Это записано в [[method_egor_two_scale_entry]] дословно:
    # len50 = значимые сломы (направление, подтверждение, ДОБОР),
    # len5  = внутренняя структура (ТРИГГЕР входа). Работают ВМЕСТЕ.
    # Настоящий дефект не «50 вместо 5», а то, что матрица знает ТОЛЬКО ОДНУ длину.
    from core.smc.smc_engine import detect_structure_breaks
    cards = []
    for frac in (0.62, 0.9)[:n_cases]:
        c0 = int(len(dfi) * frac)
        # 🔴 ОКНО ПОД СТАРШУЮ СТРУКТУРУ. На 125 свечах len50 не находит НИЧЕГО:
        # замер даёт 0.66 слома в сутки, то есть один на ~140 баров 15m. Чтобы обе
        # структуры были видны, окно обязано вмещать несколько сломов старшей.
        a = max(0, c0 - 220); b = min(len(dfi), a + 340)
        sub = smc_frame(dfi.iloc[a:b].reset_index(drop=True))
        cnt = {}
        for L in (5, 50):
            try:
                cnt[L] = len(detect_structure_breaks(sub, length=L))
            except Exception:                                       # noqa: BLE001
                cnt[L] = 0
        cards.append(card(
            png(df.iloc[a:b], symbol, tf, pivots=PIV, wave=True,
                choch_length=5, choch_length_major=50),
            f"<b class='k warn'>толстые · len50</b> старшая структура — {cnt[50]} сломов "
            f"(направление и добор) &nbsp; "
            f"<b class='k ok'>тонкие · len5</b> младшая — {cnt[5]} сломов "
            f"(триггер входа)",
            coords_line(symbol, tf, df.index[a], df.index[b - 1], df.index[c0],
                        "центр окна")))
    panels.append(panel(
        "Две структуры на одном графике — len50 и len5",
        "метод Егора: len50 = значимые сломы (направление, подтверждение, добор) · "
        "len5 = внутренняя структура (триггер входа) · работают ВМЕСТЕ, "
        "это не «зрячий против слепого»",
        "толстые линии — <b>старшая</b> структура (len50), тонкие — <b>младшая</b> (len5). "
        "По методу вход даёт len5-слом, а len50-слом подтверждает ход и открывает добор. "
        "🔴 В матрице сейчас живёт ТОЛЬКО ОДНА длина (config.yaml:1527 = 50) — младшей "
        "структуры она не видит вовсе, то есть триггеров входа у неё нет.",
        cards))

    # ── импульс + POC: нога, зона входа и уровни штатным okosm ───────────────
    from core.smc.impulse_fib import _atr, find_impulses
    from poc_impulse_test import impulse_poc
    H, L, C, V = dfi.high.values, dfi.low.values, dfi.close.values, dfi.volume.values
    atr = _atr(dfi).values
    imps = [(x, y, u) for x, y, u in find_impulses(H, L, C, atr, len(dfi))
            if 60 < x and y < len(dfi) - 30]
    cards = []
    for i0, i1, up in imps[-n_cases:]:
        poc, conc = impulse_poc(H, L, V, i0, i1)
        a = max(0, i0 - 15); b = min(len(dfi), i1 + 45)
        amp = abs(C[i1] - C[i0]); sgn = 1.0 if up else -1.0
        fib = C[i1] - sgn * 0.382 * amp
        ok = {"leg": (ms(i0), float(C[i0]), ms(i1), float(C[i1])),
              "zone": (min(fib, C[i1]), max(fib, C[i1])),
              "levels": [(0.382, float(fib), True)]}
        if poc:
            ok["break"] = float(poc)
        cards.append(card(
            png(df.iloc[a:b], symbol, tf, okosm=ok, pivots=PIV, wave=False),
            f"{'рост' if up else 'падение'} · {i1-i0} баров · оранжевая линия = ход, "
            f"жёлтая полоса = до входа · вход 0.382 = <b>{fib:.6g}</b> · "
            f"розовый пунктир POC = <b>{poc:.6g}</b> · концентрация {conc:.1f}%",
            coords_line(symbol, tf, df.index[a], df.index[b - 1], df.index[i1],
                        "конец импульса")))
    panels.append(panel(
        "Импульс, вход 0.382 и POC профиля объёма",
        "детектор core/smc/impulse_fib.py · POC — профиль объёма НА ОТРЕЗКЕ импульса · "
        "нога и уровни нарисованы штатным okosm",
        "оранжевая линия — размеченный ход: обязана идти от начала к концу движения без "
        "крупных откатов внутри. Жёлтая полоса — от конца хода до нашего входа 0.382. "
        "Розовый пунктир — POC, цена с наибольшим проторгованным объёмом. "
        "Вопрос: тянется ли цена обратно к POC?",
        cards))
    return panels, len(df)


TPL = """<title>Проверка детекторов глазами</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{--bg:#f4f5f7;--panel:#fff;--ink:#12161c;--dim:#5a6472;--line:#dee2e9;
  --ok:#b8860b;--warn:#d97706;--accent:#b8860b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0d1015;--panel:#161b22;--ink:#e6eaf0;--dim:#8b95a4;--line:#242b35;
  --ok:#e3bd3a;--warn:#f59e0b;--accent:#e3bd3a}}
:root[data-theme="dark"]{--bg:#0d1015;--panel:#161b22;--ink:#e6eaf0;--dim:#8b95a4;
  --line:#242b35;--ok:#e3bd3a;--warn:#f59e0b;--accent:#e3bd3a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);padding:26px 18px 60px;
  font-family:"IBM Plex Sans",system-ui,sans-serif;line-height:1.55}
.wrap{max-width:1400px;margin:0 auto;display:flex;flex-direction:column;gap:20px}
header.top{display:flex;flex-direction:column;gap:8px;padding-bottom:14px;
  border-bottom:1px solid var(--line)}
h1{margin:0;font-size:1.5rem;font-weight:600;letter-spacing:-.01em;text-wrap:balance}
.meta{margin:0;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.75rem;
  color:var(--dim);letter-spacing:.02em}
.lede{margin:0;max-width:72ch;color:var(--dim);font-size:.93rem}
.lede b{color:var(--ink);font-weight:500}
.lede code{font-family:"IBM Plex Mono",monospace;font-size:.85em}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:18px;display:flex;flex-direction:column;gap:14px}
.ph{display:flex;flex-direction:column;gap:6px}
.ph h2{margin:0;font-size:1.05rem;font-weight:600}
.sub{margin:0;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.72rem;color:var(--dim)}
.q{margin:4px 0 0;font-size:.9rem;max-width:84ch;padding:10px 12px;
  border-left:2px solid var(--accent);
  background:color-mix(in srgb,var(--accent) 8%,transparent)}
.qlabel{font-family:"IBM Plex Mono",monospace;font-size:.65rem;text-transform:uppercase;
  letter-spacing:.09em;color:var(--dim);margin-right:8px}
.grid{display:flex;flex-direction:column;gap:18px}
/* C-01: пары «эталон | боевое» рядом — сравнивать глазами, а не по датам */
.grid.pair{display:grid;grid-template-columns:repeat(auto-fit,minmax(440px,1fr));gap:14px}
.card{margin:0;display:flex;flex-direction:column;gap:6px;min-width:0}
.card img{width:100%;height:auto;display:block;border-radius:6px;border:1px solid var(--line);
  cursor:zoom-in;transition:border-color .15s}
.card img:hover{border-color:var(--accent)}
/* увеличение по клику: график мелкий в сетке, детали не разглядеть */
#lb{position:fixed;inset:0;background:rgba(8,10,14,.94);display:none;z-index:99;
  align-items:center;justify-content:center;padding:16px;cursor:zoom-out}
#lb.on{display:flex}
#lb img{max-width:100%;max-height:100%;width:auto;border-radius:6px;cursor:zoom-out;
  border:1px solid var(--line)}
#lb .hint{position:fixed;top:12px;left:50%;transform:translateX(-50%);color:var(--dim);
  font-family:"IBM Plex Mono",monospace;font-size:.72rem}
figcaption{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.74rem;
  color:var(--dim);font-variant-numeric:tabular-nums;line-height:1.5}
figcaption b{color:var(--ink)}
.k{padding:1px 6px;border-radius:3px;border:1px solid currentColor;font-size:.68rem;
  margin-right:6px;font-weight:500}
.k.ok{color:var(--ok)} .k.warn{color:var(--warn)}
.coords{margin:0;display:flex;flex-wrap:wrap;gap:6px;align-items:center;
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.72rem;
  font-variant-numeric:tabular-nums}
.coords span{padding:2px 7px;border-radius:4px;border:1px solid var(--line);color:var(--dim)}
.c-sym{color:var(--ink)!important;font-weight:500}
.c-evt{border-color:var(--accent)!important;color:var(--ink)!important}
.c-evt b{color:var(--accent)}
.foot{color:var(--dim);font-size:.85rem;max-width:74ch}
.pick{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;margin:6px 0 2px}
.pick label{display:flex;flex-direction:column;gap:4px;font-size:.7rem;
  text-transform:uppercase;letter-spacing:.08em;color:var(--dim)}
.pick input,.pick select{font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:.85rem;padding:6px 9px;border-radius:6px;border:1px solid var(--line);
  background:var(--panel);color:var(--ink);min-width:110px}
.pick button{padding:7px 16px;border-radius:6px;border:1px solid var(--accent);
  background:var(--accent);color:var(--bg);font-weight:600;font-size:.85rem;cursor:pointer}
.pick button:hover{filter:brightness(1.08)}
.pick :is(input,select,button):focus-visible{outline:2px solid var(--accent);outline-offset:2px}
</style>
<div class="wrap">
<header class="top">
  <h1>Проверка детекторов глазами</h1>
  <p class="meta">__META__</p>
  __FORM__
  <p class="lede">Всё рисует <b>штатный <code>chart_builder</code></b> — своего рендера
  нет. Объекты детектора подаются его же механизмами: <code>htf_fvg</code> для зон,
  <code>okosm</code> для ноги, зоны и уровней, <code>wave_overlay</code> для обычной
  разметки OKO-SM. Под каждым графиком координаты окна — чтобы открыть тот же участок
  у себя и сверить.</p>
</header>
__PANELS__
<p class="foot">Окна — последние срабатывания детектора. Если разметка расходится
с тем, что видит глаз, дефект в детекторе.</p>
</div>
<div id="lb" role="dialog" aria-label="увеличенный график"><span class="hint">клик или Esc — закрыть</span><img alt=""></div>
<script>
(function(){
  var lb=document.getElementById('lb'), big=lb.querySelector('img');
  document.addEventListener('click',function(e){
    var t=e.target;
    if(t.tagName==='IMG'&&t.closest('.card')){big.src=t.src;lb.classList.add('on');}
    else if(lb.classList.contains('on')){lb.classList.remove('on');big.removeAttribute('src');}
  });
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'){lb.classList.remove('on');big.removeAttribute('src');}
  });
})();
</script>
"""


def _form(symbol: str, tf: str, cases: int) -> str:
    tfs = "".join(f'<option value="{t}"{" selected" if t == tf else ""}>{t}</option>'
                  for t in ("5m", "15m", "1h", "4h"))
    return (f'<form class="pick" method="get" action="/viz">'
            f'<label>актив<input name="symbol" value="{html.escape(symbol)}" '
            f'spellcheck="false"></label>'
            f'<label>ТФ<select name="tf">{tfs}</select></label>'
            f'<label>окон<input name="cases" type="number" min="1" max="4" '
            f'value="{cases}"></label>'
            f'<button type="submit">построить</button></form>')


def render_page(symbol: str = "ARB/USDT", tf: str = "15m",
                bars: int = 4000, cases: int = 2) -> str:
    """Готовая страница целиком — точка входа для дашборда (`/viz`)."""
    panels, _ = build(symbol, tf, bars, cases)
    meta = f"{symbol} · {tf} · рендер core/ui/chart_builder"
    return (TPL.replace("__PANELS__", "\n".join(panels))
               .replace("__META__", html.escape(meta))
               .replace("__FORM__", _form(symbol, tf, cases)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="ARB/USDT")
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--bars", type=int, default=4000)
    ap.add_argument("--cases", type=int, default=2)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    doc = render_page(a.symbol, a.tf, a.bars, a.cases)
    out = Path(a.out) if a.out else (ROOT / "cache" / "detector_visual.html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    print(f"страница → {out}  ({len(doc)//1024} КБ)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
