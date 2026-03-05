"""
Лёгкий aiohttp-дашборд для мониторинга симулированных сделок.
Запускается как фоновая задача внутри event loop бота.

Эндпоинты:
  GET /           — HTML-дашборд (авто-обновление каждые 30 сек)
  GET /api/stats  — полная статистика в JSON
"""
import json
import logging
from datetime import datetime, timezone

from aiohttp import web

from core.performance_engine import PerformanceEngine

logger = logging.getLogger(__name__)

_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crypto Bot Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #c9d1d9; }
  header { background: #161b22; padding: 16px 24px; border-bottom: 1px solid #30363d;
           display: flex; justify-content: space-between; align-items: center; }
  header h1 { font-size: 1.25rem; color: #58a6ff; }
  #updated { font-size: 0.8rem; color: #8b949e; }
  main { padding: 24px; max-width: 1200px; margin: 0 auto; }
  section { margin-bottom: 32px; }
  h2 { font-size: 1rem; color: #8b949e; text-transform: uppercase;
       letter-spacing: .08em; margin-bottom: 12px; border-bottom: 1px solid #21262d; padding-bottom: 6px; }
  .cards { display: flex; flex-wrap: wrap; gap: 12px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
          padding: 16px 20px; min-width: 140px; flex: 1; }
  .card .label { font-size: .75rem; color: #8b949e; margin-bottom: 6px; }
  .card .value { font-size: 1.5rem; font-weight: 700; }
  .green { color: #3fb950; } .red { color: #f85149; } .blue { color: #58a6ff; }
  .yellow { color: #d29922; }
  table { width: 100%; border-collapse: collapse; font-size: .85rem; }
  th { text-align: left; padding: 8px 10px; background: #161b22;
       color: #8b949e; border-bottom: 1px solid #30363d; }
  td { padding: 7px 10px; border-bottom: 1px solid #21262d; }
  tr:hover td { background: #1c2128; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 20px;
           font-size: .75rem; font-weight: 600; }
  .badge-tp { background: #1a3a1f; color: #3fb950; }
  .badge-sl { background: #3a1a1a; color: #f85149; }
  .badge-exp { background: #2d2a1a; color: #d29922; }
  .badge-open { background: #1a2a3a; color: #58a6ff; }
  #loader { text-align: center; padding: 60px; color: #8b949e; font-size: 1.1rem; }
  .note { color: #8b949e; font-size: .85rem; font-style: italic; padding: 12px 0; }
</style>
</head>
<body>
<header>
  <h1>&#x1F4CA; Crypto Bot — Trade Dashboard</h1>
  <span id="updated">загрузка...</span>
</header>
<main id="app"><div id="loader">&#x23F3; Загрузка данных...</div></main>

<script>
const fmt = (v, dec=2) => v == null ? '—' : (+v).toFixed(dec);
const fmtPct = v => v == null ? '—' : (v > 0 ? '+' : '') + fmt(v, 2) + '%';
const badge = s => {
  const map = {TP:'badge-tp',SL:'badge-sl',EXPIRED:'badge-exp',OPEN:'badge-open'};
  return `<span class="badge ${map[s]||''}">${s}</span>`;
};
const color = (v, inv=false) => {
  if (v == null) return '';
  const pos = inv ? v < 0 : v > 0;
  return pos ? 'green' : (v === 0 ? '' : 'red');
};

async function load() {
  try {
    const r = await fetch('/api/stats');
    const d = await r.json();
    render(d);
    document.getElementById('updated').textContent =
      'Обновлено: ' + new Date().toLocaleTimeString('ru');
  } catch(e) {
    document.getElementById('updated').textContent = 'Ошибка загрузки: ' + e.message;
  }
}

function render(d) {
  const s = d.summary || {};
  const html = `
    <section>
      <h2>Сводка</h2>
      <div class="cards">
        <div class="card"><div class="label">Всего сделок</div>
          <div class="value blue">${s.total ?? '—'}</div></div>
        <div class="card"><div class="label">Открытых</div>
          <div class="value blue">${s.open_count ?? '—'}</div></div>
        <div class="card"><div class="label">Win Rate</div>
          <div class="value ${s.win_rate >= 50 ? 'green' : 'red'}">${s.win_rate != null ? s.win_rate + '%' : '—'}</div></div>
        <div class="card"><div class="label">TP / SL</div>
          <div class="value"><span class="green">${s.tp_count ?? 0}</span> / <span class="red">${s.sl_count ?? 0}</span></div></div>
        <div class="card"><div class="label">Avg Profit %</div>
          <div class="value ${color(s.avg_profit_pct)}">${fmtPct(s.avg_profit_pct)}</div></div>
        <div class="card"><div class="label">Avg R</div>
          <div class="value ${color(s.avg_r)}">${fmt(s.avg_r, 2)}</div></div>
        <div class="card"><div class="label">Avg R (wins)</div>
          <div class="value green">${fmt(s.avg_r_win, 2)}</div></div>
        <div class="card"><div class="label">Avg R (losses)</div>
          <div class="value red">${fmt(s.avg_r_loss, 2)}</div></div>
        <div class="card"><div class="label">Истекло</div>
          <div class="value yellow">${s.expired_count ?? 0}</div></div>
      </div>
    </section>

    <section>
      <h2>По типу сигнала</h2>
      ${tableByGroup(d.by_signal_type, 'signal_type')}
    </section>

    <section>
      <h2>По направлению</h2>
      ${tableByGroup(d.by_direction, 'direction')}
    </section>

    <section>
      <h2>По режиму рынка</h2>
      ${regimeSection(d.by_regime)}
    </section>

    <section>
      <h2>Открытые позиции (${(d.open_trades||[]).length})</h2>
      ${openTradesTable(d.open_trades)}
    </section>

    <section>
      <h2>Последние закрытые сделки</h2>
      ${recentTable(d.recent_closed)}
    </section>
  `;
  document.getElementById('app').innerHTML = html;
}

function tableByGroup(rows, labelKey) {
  if (!rows || !rows.length) return '<p class="note">Нет данных</p>';
  return `<table><thead><tr>
    <th>${labelKey}</th><th>Всего</th><th>Win Rate</th><th>TP</th><th>SL</th>
    <th>Avg Profit%</th><th>Avg R</th>
  </tr></thead><tbody>` +
  rows.map(r => `<tr>
    <td>${r[labelKey] || '—'}</td>
    <td>${r.total}</td>
    <td class="${r.win_rate >= 50 ? 'green' : 'red'}">${r.win_rate != null ? r.win_rate + '%' : '—'}</td>
    <td class="green">${r.wins}</td>
    <td class="red">${r.losses}</td>
    <td class="${color(r.avg_profit_pct)}">${fmtPct(r.avg_profit_pct)}</td>
    <td class="${color(r.avg_r)}">${fmt(r.avg_r,2)}</td>
  </tr>`).join('') + '</tbody></table>';
}

function regimeSection(rows) {
  const allUnknown = !rows || rows.every(r => r.regime === 'unknown');
  if (allUnknown) return '<p class="note">Режим рынка пока не заполняется. Подключите MarketRegimeClassifier в trade_simulator.py — и данные появятся здесь автоматически.</p>';
  return tableByGroup(rows, 'regime');
}

function openTradesTable(rows) {
  if (!rows || !rows.length) return '<p class="note">Нет открытых позиций</p>';
  return `<table><thead><tr>
    <th>#</th><th>Символ</th><th>Направление</th><th>Сигнал</th>
    <th>Вход</th><th>SL</th><th>TP</th><th>Уверенность</th><th>Открыта</th>
  </tr></thead><tbody>` +
  rows.map(r => `<tr>
    <td>${r.id}</td>
    <td>${r.symbol}</td>
    <td class="${r.direction==='LONG'?'green':'red'}">${r.direction}</td>
    <td>${r.signal_type||'—'}</td>
    <td>${fmt(r.entry_price,4)}</td>
    <td class="red">${fmt(r.stop_loss,4)}</td>
    <td class="green">${fmt(r.take_profit,4)}</td>
    <td>${r.confidence != null ? fmt(r.confidence*100,1)+'%' : '—'}</td>
    <td>${r.created_at ? r.created_at.substring(0,16) : '—'}</td>
  </tr>`).join('') + '</tbody></table>';
}

function recentTable(rows) {
  if (!rows || !rows.length) return '<p class="note">Нет закрытых сделок</p>';
  return `<table><thead><tr>
    <th>#</th><th>Символ</th><th>Dir</th><th>Сигнал</th><th>Статус</th>
    <th>Profit%</th><th>R</th><th>Длит (мин)</th><th>Закрыта</th>
  </tr></thead><tbody>` +
  rows.map(r => `<tr>
    <td>${r.id}</td>
    <td>${r.symbol}</td>
    <td class="${r.direction==='LONG'?'green':'red'}">${r.direction}</td>
    <td>${r.signal_type||'—'}</td>
    <td>${badge(r.status)}</td>
    <td class="${color(r.profit_pct)}">${fmtPct(r.profit_pct)}</td>
    <td class="${color(r.R_multiple)}">${fmt(r.R_multiple,2)}</td>
    <td>${r.duration_minutes != null ? Math.round(r.duration_minutes) : '—'}</td>
    <td>${r.closed_at ? r.closed_at.substring(0,16) : '—'}</td>
  </tr>`).join('') + '</tbody></table>';
}

load();
setInterval(load, 30000);
</script>
</body>
</html>
"""


async def _handle_index(request: web.Request) -> web.Response:
    return web.Response(text=_HTML, content_type="text/html", charset="utf-8")


async def _handle_stats(request: web.Request) -> web.Response:
    engine: PerformanceEngine = request.app["engine"]
    try:
        data = engine.full_stats()
        return web.Response(
            text=json.dumps(data, ensure_ascii=False, default=str),
            content_type="application/json",
            charset="utf-8",
        )
    except Exception as e:
        logger.exception("dashboard /api/stats error: %s", e)
        return web.Response(status=500, text=str(e))


async def start_dashboard(db_path: str = "subscriptions.db", host: str = "0.0.0.0", port: int = 8000) -> None:
    """Запускает aiohttp-сервер. Вызывать через asyncio.create_task()."""
    app = web.Application()
    app["engine"] = PerformanceEngine(db_path=db_path)
    app.router.add_get("/", _handle_index)
    app.router.add_get("/api/stats", _handle_stats)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    try:
        await site.start()
        logger.info("Dashboard запущен: http://%s:%s", host, port)
        # держим сервер живым (его отменит CancelledError при shutdown бота)
        while True:
            import asyncio
            await asyncio.sleep(3600)
    except Exception as e:
        logger.exception("Dashboard error: %s", e)
    finally:
        await runner.cleanup()
