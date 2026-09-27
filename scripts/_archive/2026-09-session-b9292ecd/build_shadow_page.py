import json, base64, os
SP = os.path.dirname(os.path.abspath(__file__))
REPO = r"E:\MTF BOT\CURSOR\crypto_volume_bot"
rows = json.load(open(os.path.join(SP, "shadow_now.json"), encoding="utf-8"))
imgs = {"SOLV": "SOLVUSDT_20260913", "RECALL": "RECALLUSDT_20260911", "TUT": "TUTUSDT_20260909",
        "CYBER": "CYBERUSDT_20260911", "IDOL": "IDOLUSDT_20260909"}
notes = {
 "SOLV": ("Пятёрка вверх +98% за 4 дня, WT 73 на вершине. Канал 0.86, чередование ✓, счёт ✓ — форма импульса чистая. Не ядро по двум причинам: фрактал ✗ (в первой волне ни одного младшего слома — она из одной свечи) и <b>шорт-ядро требует медвежьей дневной структуры</b>, а тут 1D бычья и дневной максимум пробит (памп в тренде). Вошёл по кроссу WT 15m через 5 ч после вершины.",
          "Уже +19.9% в сторону шорта, цель (конец w4 = 0.00375) ещё +13%. Стоп над экстремумом −1.5%. Это «фейд пампа» — ядро на 20 шортах в бэктесте говорило: без медвежьей 1D шорт не платит систематически, а тут заплатил сразу. Одна сделка — не довод, кладу в копилку."),
 "RECALL": ("Разметка, на мой глаз, верная: 0-1-2 (глубокая, 0.73) — 3 — 4 — 5. Фрактал ✓ (младшие сломы в w1 и w3), чередование ✓, счёт ✓. Не ядро по одному признаку: <b>канал 0.11</b> — пятая не дотянула до параллели через 3, усечённая пятая. Линия 2-4 пробита — достроенный вход есть.",
            "+4.5%, цель +10.2% (0.0433), стоп −7%. 1D медвежья, WT1D −48. По правилам ядра — самый «правильный» из четырёх лонгов: усечённая пятая при пробитой линии 2-4 — это скорее сила покупателя, чем слабость сетапа. Гипотеза для замера: усечение (канал 0.1–0.5) при line24 — отдельный класс."),
 "TUT": ("Обвал −82% за 4 дня: w1 и w3 — ножи, w4 крошечная (откат 0.18), <b>канал −0.25</b> — пятая не дошла даже до линии 2-4, это плато, не пятая. Формально 5 точек есть, по смыслу — импульс 1-2-3 и консолидация. Фрактал ✓, но сломы внутри ножа мало что значат.",
         "+1.3%, «цель» +57% — нереальна как цель коррекции после обвала (конец w4 = 0.030 при цене 0.019). Стоп −21% — геометрия сделки плохая. Отметил бы как <i>«разметка формальна, не торговать»</i>. Именно такие случаи должна отсекать проверка канала — и она отсекла (не ядро)."),
 "CYBER": ("Разметка чистая: 0 на пике 0.378, w2 глубокая (0.59), w4 плоская — чередование ✓, канал 0.95 (пятая точно на параллели — образцово), счёт ✓. Не ядро только из-за <b>фрактала ✗</b>: в w1 ноль младших сломов — первая волна из двух свечей. Пятая выполнила прогноз по фибо: 0.618×w1 и 1.0×w1 достигнуты. Та же монета, что на 1h показывала «WT −40 при пороге −45».",
           "+1.0%, цель +10.6% (0.324, конец w4), стоп −6.6%. 1D бычья, дневной свинг пробит. По форме — лучший из пяти; мешает только формальный фрактал в короткой первой волне. Кандидат в правило: если w1 короче N баров, фрактал считать по w3 (bos3 ≥ 1)."),
 "IDOL": ("Импульс −48%, фрактал ✓, счёт ✓, но <b>канал 1.89</b> — пятая улетела далеко за параллель (throw-over на ноже 12.09), и <b>чередование ✗</b> — w2 и w4 одной формы. Пятая выполнила все цели по фибо, включая 1.618×w1 — типичное удлинение пятой.",
          "+1.1%, но стоп всего −1.7% под экстремумом ножа — свип очень вероятен (стоп-лаб: тугие стопы свипают в 58–78%). Цель +48% нереалистична как конец w4. Удлинённая пятая после ножа — в бэктесте класс «обвал», платит кластерными днями, одиночно — лотерея."),
}

def b64(n):
    return base64.b64encode(open(os.path.join(REPO, "data", "wave5_shadow", "charts", n + ".png"), "rb").read()).decode()

def flag(k, v):
    return f'<span class="f {"ok" if v else "no"}">{k}{"✓" if v else "✗"}</span>'

cards = ""
for r in rows:
    s = r["sym"]; a, b = notes[s]
    flags = " ".join([flag("фрактал", r["fr"]), flag("канал", r["ch"] >= 0.5), flag("черед", r["alt"]), flag("счёт", r["cnt"])])
    pn = r["pnl"]; cls = "up" if pn >= 0 else "dn"
    cards += f'''
<section class="card" id="{s}">
 <header><h2>{s} <span class="side {r["side"].lower()}">{r["side"]}</span></h2>
  <div class="meta">вершина {r["top"]} UTC · {r["h"]} ч · импульс {r["imp"]}% · {flags} · канал {r["ch"]} · 1D {"бычья" if r["d_bull"] else "медвежья"}, WT1D {r["wt1d"]} · <b class="{"core" if r["core"] else "nocore"}">{"ЯДРО" if r["core"] else "не ядро"}</b></div></header>
 <figure><img src="data:image/png;base64,{b64(imgs[s])}" alt="{s} разметка 4h" loading="lazy"><figcaption>тень: разметка 4h, линия 2-4, канал, цель = конец волны 4, стоп за экстремум пятой, уровни фибо · клик — крупно</figcaption></figure>
 <div class="grid">
  <div class="kv"><span>вход</span><b>{r["trig"]} · {r["at"]} UTC · {r["e"]:g}</b></div>
  <div class="kv"><span>сейчас</span><b>{r["cur"]:g} · <em class="{cls}">{pn:+.1f}%</em></b></div>
  <div class="kv"><span>цель (конец w4)</span><b>{r["p4"]:g} · {r["tgt"]:+.1f}%</b></div>
  <div class="kv"><span>стоп</span><b>{r["stop"]:.6g} · {r["stp"]:+.1f}%</b></div>
  <div class="kv"><span>цели пятой достигнуты</span><b>{r["w5"] or "—"}</b></div>
  <div class="kv"><span>линия 2-4</span><b>{"пробита" if r["l24"] else "не пробита"}</b></div>
 </div>
 <p class="n"><b>Разметка.</b> {a}</p>
 <p class="n"><b>Сделка.</b> {b}</p>
 <p class="egor">Твоя оценка разметки (колонка <code>egor</code> в <code>data/wave5_shadow/shadow_signals.csv</code>): верно / степень не та / четвёртая не там / удлинение / не импульс</p>
</section>'''

tbl = "".join(
    f'<tr><td><a href="#{r["sym"]}">{r["sym"]}</a></td><td class="{r["side"].lower()}">{r["side"]}</td><td>{r["top"][5:]}</td>'
    f'<td>{r["imp"]}%</td><td>{"✓" if r["fr"] else "✗"}</td><td>{r["ch"]}</td><td>{"✓" if r["alt"] else "✗"}</td><td>{"✓" if r["cnt"] else "✗"}</td>'
    f'<td>{"✓" if r["core"] else "—"}</td><td>{r["trig"]}</td><td class="{"up" if r["pnl"] >= 0 else "dn"}">{r["pnl"]:+.1f}%</td>'
    f'<td>{r["tgt"]:+.1f}%</td><td>{r["stp"]:+.1f}%</td></tr>' for r in rows)

page = f'''<title>Тень ядра — живые сетапы</title>
<style>
:root{{--bg:#f4f5f8;--card:#fff;--tx:#1b2130;--mut:#5c6675;--ln:#dde2ea;--acc:#b8860b;--up:#1e8e7e;--dn:#d23f3c;--long:#2b5fd9;--short:#c0392b}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#0f1218;--card:#161b24;--tx:#dfe4ec;--mut:#8b94a6;--ln:#232a37;--acc:#f5c542;--up:#26a69a;--dn:#ef5350;--long:#8ab4f8;--short:#f4a4a4}}}}
:root[data-theme="dark"]{{--bg:#0f1218;--card:#161b24;--tx:#dfe4ec;--mut:#8b94a6;--ln:#232a37;--acc:#f5c542;--up:#26a69a;--dn:#ef5350;--long:#8ab4f8;--short:#f4a4a4}}
body{{background:var(--bg);color:var(--tx);font:14px/1.5 "Segoe UI",system-ui,sans-serif;margin:0;padding-block:24px 60px;padding-inline:16px}}
main{{max-width:1100px;margin:0 auto}}
h1{{font-size:24px;margin:0 0 4px;letter-spacing:-.01em}} .sub{{color:var(--mut);margin:0 0 18px;max-width:75ch}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:13px}} th,td{{padding:6px 8px;border-bottom:1px solid var(--ln);text-align:left;white-space:nowrap}} th{{color:var(--mut);font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:.04em}}
.tw{{overflow-x:auto;margin-bottom:26px;background:var(--card);border:1px solid var(--ln);border-radius:8px;padding:4px 8px}}
.card{{background:var(--card);border:1px solid var(--ln);border-radius:10px;padding:16px 18px;margin-bottom:22px}}
.card h2{{margin:0;font-size:20px;display:flex;gap:10px;align-items:center}} .side{{font-size:11px;padding:2px 8px;border-radius:4px;letter-spacing:.06em}} .side.long{{background:var(--long);color:#fff}} .side.short{{background:var(--short);color:#fff}}
.meta{{color:var(--mut);font-size:12.5px;margin:6px 0 12px}} .f{{padding:1px 6px;border-radius:3px;font-size:11.5px}} .f.ok{{background:rgba(38,166,154,.18);color:var(--up)}} .f.no{{background:rgba(239,83,80,.16);color:var(--dn)}}
.core{{color:var(--acc)}} .nocore{{color:var(--mut)}}
figure{{margin:0 0 12px}} figure img{{width:100%;max-width:100%;height:auto;border-radius:6px;border:1px solid var(--ln);cursor:zoom-in}} figcaption{{color:var(--mut);font-size:12px;margin-top:4px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px 16px;margin:0 0 12px}} .kv span{{display:block;color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.04em}} .kv b{{font-weight:600;font-variant-numeric:tabular-nums}}
.up{{color:var(--up);font-style:normal}} .dn{{color:var(--dn);font-style:normal}} td.long{{color:var(--long)}} td.short{{color:var(--short)}}
.n{{margin:6px 0;max-width:90ch}} .egor{{color:var(--mut);font-size:12.5px;border-top:1px dashed var(--ln);padding-top:8px;margin:10px 0 0}} code{{background:rgba(127,127,127,.15);padding:0 4px;border-radius:3px}}
.lb{{position:fixed;inset:0;background:rgba(0,0,0,.9);display:none;align-items:center;justify-content:center;z-index:9;cursor:zoom-out}} .lb img{{max-width:98vw;max-height:96vh}}
.note{{background:var(--card);border-left:3px solid var(--acc);padding:10px 14px;border-radius:6px;margin:0 0 22px;max-width:90ch}}
</style>
<main>
<h1>Тень ядра — живые сетапы</h1>
<p class="sub">Пять сетапов, найденных тенью (pm2 <code>wave5-shadow</code>) на закрытых барах 4h BingX, вселенная ≥2M оборота. Цены и PnL — на 14.09 06:30 UTC. Ни один не проходит полное ядро; это база, из которой ядро отбирает.</p>
<div class="note">⚠️ Честно про входы: тень запущена 14.09 01:05 UTC, четыре лонга к этому моменту уже имели кросс WT (11–12.09) — их <b>цена входа = закрытие на момент запуска</b>, не цена реального кросса. Только SOLV вошёл «по-настоящему» (кросс 13.09 20:30 → вход первым циклом). Со следующего сетапа входы будут по факту.</div>
<div class="tw"><table><thead><tr><th>монета</th><th>сторона</th><th>вершина</th><th>импульс</th><th>фрактал</th><th>канал</th><th>черед.</th><th>счёт</th><th>ядро</th><th>вход</th><th>PnL</th><th>до цели</th><th>до стопа</th></tr></thead><tbody>{tbl}</tbody></table></div>
{cards}
</main>
<div class="lb" id="lb"><img id="lbi" alt=""></div>
<script>
document.querySelectorAll('figure img').forEach(function(i){{i.onclick=function(){{document.getElementById('lbi').src=i.src;document.getElementById('lb').style.display='flex';}};}});
document.getElementById('lb').onclick=function(){{this.style.display='none';}};
</script>'''
out = os.path.join(SP, "shadow_setups.html")
open(out, "w", encoding="utf-8").write(page)
print(len(page) // 1024, "KB", out)
