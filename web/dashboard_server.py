"""
Лёгкий aiohttp-дашборд для мониторинга симулированных сделок.
Запускается как фоновая задача внутри event loop бота.

Эндпоинты:
  GET /                     — HTML-дашборд (авто-обновление каждые 30 сек)
  GET /api/stats            — полная статистика в JSON
  GET /settings             — страница настроек бота
  GET /api/settings         — текущие настройки в JSON
  POST /api/settings        — сохранить и применить настройки
  GET /backtest             — страница бэктестинга
  GET /api/backtest/results — последние результаты бэктеста (JSON)
  GET /api/backtest/status  — статус запуска (running/idle)
  POST /api/backtest/run    — запустить бэктест в фоне
"""
import asyncio
import json
import logging
import os
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
  <div style="display:flex;align-items:center;gap:16px;">
    <a href="/backtest" style="color:#58a6ff;text-decoration:none;font-size:.85rem;">&#x1F4C8; Бэктест</a>
    <a href="/settings" style="color:#58a6ff;text-decoration:none;font-size:.85rem;">&#x2699;&#xFE0F; Настройки</a>
    <span id="updated">загрузка...</span>
  </div>
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

function tvUrl(sym) {
  const base = (sym||'').replace('/USDT:USDT','').replace('/USDT','').replace('/','');
  return `https://ru.tradingview.com/chart/?symbol=BINGX%3A${base}USDT.P&interval=15`;
}
function symLink(sym) {
  const label = (sym||'').replace(':USDT','');
  return `<a href="${tvUrl(sym)}" target="_blank" style="color:#58a6ff;text-decoration:none">${label}</a>`;
}

function openTradesTable(rows) {
  if (!rows || !rows.length) return '<p class="note">Нет открытых позиций</p>';
  return `<table><thead><tr>
    <th>#</th><th>Символ</th><th>Направление</th><th>Сигнал</th>
    <th>Вход</th><th>SL</th><th>TP</th><th>Уверенность</th><th>Открыта</th>
  </tr></thead><tbody>` +
  rows.map(r => `<tr>
    <td>${r.id}</td>
    <td>${symLink(r.symbol)}</td>
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
    <td>${symLink(r.symbol)}</td>
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


_SETTINGS_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Настройки — Crypto Bot</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #c9d1d9; }
  header { background: #161b22; padding: 16px 24px; border-bottom: 1px solid #30363d;
           display: flex; justify-content: space-between; align-items: center; }
  header h1 { font-size: 1.25rem; color: #58a6ff; }
  nav a { color: #58a6ff; text-decoration: none; font-size: .9rem; margin-left: 16px; }
  nav a:hover { text-decoration: underline; }
  main { padding: 24px; max-width: 760px; margin: 0 auto; }
  section { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
            padding: 20px 24px; margin-bottom: 24px; }
  h2 { font-size: .9rem; color: #8b949e; text-transform: uppercase;
       letter-spacing: .08em; margin-bottom: 16px; border-bottom: 1px solid #21262d; padding-bottom: 8px; }
  .field { display: flex; align-items: center; margin-bottom: 14px; gap: 12px; }
  .field label { flex: 0 0 220px; font-size: .88rem; color: #c9d1d9; }
  .field input[type=number] { width: 120px; background: #0d1117; border: 1px solid #30363d;
     color: #c9d1d9; border-radius: 6px; padding: 6px 10px; font-size: .9rem; }
  .field input:focus { outline: none; border-color: #58a6ff; }
  .hint { font-size: .75rem; color: #8b949e; }
  .btn { background: #238636; color: #fff; border: none; border-radius: 6px;
         padding: 9px 20px; font-size: .9rem; cursor: pointer; margin-top: 4px; }
  .btn:hover { background: #2ea043; }
  .btn:disabled { background: #21262d; color: #8b949e; cursor: not-allowed; }
  #msg { padding: 10px 14px; border-radius: 6px; font-size: .88rem; margin-top: 12px;
         display: none; }
  .msg-ok  { background: #1a3a1f; color: #3fb950; border: 1px solid #2ea043; }
  .msg-err { background: #3a1a1a; color: #f85149; border: 1px solid #f85149; }
  .info-row { display: flex; justify-content: space-between; padding: 6px 0;
              border-bottom: 1px solid #21262d; font-size: .88rem; }
  .info-row:last-child { border-bottom: none; }
  .info-key { color: #8b949e; }
  .info-val { color: #c9d1d9; font-weight: 600; }
  .formula { background: #0d1117; border: 1px solid #21262d; border-radius: 6px;
             padding: 10px 14px; font-family: monospace; font-size: .85rem; color: #58a6ff; margin: 8px 0; }
</style>
</head>
<body>
<header>
  <h1>&#x2699;&#xFE0F; Настройки бота</h1>
  <nav>
    <a href="/">&#x1F4CA; Дашборд</a>
    <a href="/backtest">&#x1F4C8; Бэктест</a>
  </nav>
</header>
<main>

  <section>
    <h2>&#x1F50D; Параметры анализа</h2>
    <form id="analysisForm">
      <div class="field">
        <label>Множитель аномалии объёма</label>
        <input type="number" id="volume_multiplier" name="volume_multiplier"
               min="1" max="100" step="0.5">
        <span class="hint">× среднего объёма за 20 свечей</span>
      </div>
      <div class="field">
        <label>Порог изменения цены, %</label>
        <input type="number" id="price_threshold" name="price_threshold"
               min="0.5" max="50" step="0.5">
        <span class="hint">минимальное движение цены для сигнала</span>
      </div>
      <div class="field">
        <label>Интервал проверки, сек</label>
        <input type="number" id="check_interval" name="check_interval"
               min="10" max="3600" step="10">
        <span class="hint">пауза между циклами мониторинга</span>
      </div>
      <div class="field">
        <label>Размер истории (свечей)</label>
        <input type="number" id="history_size" name="history_size"
               min="50" max="1000" step="50">
        <span class="hint">глубина OHLCV для индикаторов</span>
      </div>
      <button type="submit" class="btn" id="saveBtn">&#x1F4BE; Сохранить и применить</button>
      <div id="msg"></div>
    </form>
  </section>

  <section>
    <h2>&#x1F4C8; Параметры индикаторов</h2>
    <form id="indicatorsForm">
      <p style="font-size:.8rem;color:#8b949e;margin-bottom:14px;">WaveTrend</p>
      <div class="field">
        <label>ESA period (n1)</label>
        <input type="number" id="wt_n1" min="5" max="30" step="1">
        <span class="hint">период EMA для HLC3 (обычно 9-12)</span>
      </div>
      <div class="field">
        <label>Signal period (n2)</label>
        <input type="number" id="wt_n2" min="10" max="50" step="1">
        <span class="hint">период EMA для сигнальной линии (обычно 20-25)</span>
      </div>
      <div class="field">
        <label>Overbought (OB)</label>
        <input type="number" id="wt_ob" min="30" max="100" step="1">
        <span class="hint">порог перекупленности (обычно 53-60)</span>
      </div>
      <div class="field">
        <label>Oversold (OS)</label>
        <input type="number" id="wt_os" min="-100" max="-30" step="1">
        <span class="hint">порог перепроданности (обычно -53 до -60)</span>
      </div>
      <p style="font-size:.8rem;color:#8b949e;margin:14px 0 10px;">Trend / TSL</p>
      <div class="field">
        <label>ATR period</label>
        <input type="number" id="trend_atr" min="5" max="200" step="1">
        <span class="hint">период ATR для TSL-тренда (по умолчанию 43)</span>
      </div>
      <div class="field">
        <label>ATR factor</label>
        <input type="number" id="trend_factor" min="0.1" max="5" step="0.1">
        <span class="hint">множитель ATR (0.8-1.2)</span>
      </div>
      <button type="submit" class="btn" id="saveIndBtn">&#x1F4BE; Сохранить индикаторы</button>
      <div id="msgInd"></div>
    </form>
  </section>

  <section>
    <h2>&#x1F4B0; Управление капиталом (формула)</h2>
    <p style="font-size:.85rem;color:#8b949e;margin-bottom:10px;">
      Каждый Telegram-пользователь настраивает свои параметры командой <code>/settings</code> в боте.
    </p>
    <div class="formula">Position (USDT) = (Deposit × Risk%) ÷ SL% × Leverage</div>
    <p style="font-size:.8rem;color:#8b949e;">
      Пример: депозит $1000, риск 1%, SL 2%, плечо 10× → позиция = (1000 × 0.01) ÷ 0.02 × 10 = $5 000
    </p>
  </section>

  <section>
    <h2>&#x1F9E0; Текущие адаптивные веса сигналов</h2>
    <div id="weights"><span style="color:#8b949e">Загрузка...</span></div>
  </section>

</main>
<script>
async function loadSettings() {
  try {
    const r = await fetch('/api/settings');
    const d = await r.json();
    const a = d.analysis || {};
    document.getElementById('volume_multiplier').value = a.volume_multiplier ?? 5.0;
    document.getElementById('price_threshold').value   = a.price_threshold   ?? 7.0;
    document.getElementById('check_interval').value    = a.check_interval    ?? 60;
    document.getElementById('history_size').value      = a.history_size      ?? 200;

    const ind = d.indicators || {};
    const wt = ind.wavetrend || {};
    const tr = ind.trend || {};
    document.getElementById('wt_n1').value       = wt.n1           ?? 10;
    document.getElementById('wt_n2').value       = wt.n2           ?? 21;
    document.getElementById('wt_ob').value       = wt.ob_threshold ?? 60;
    document.getElementById('wt_os').value       = wt.os_threshold ?? -60;
    document.getElementById('trend_atr').value   = tr.atr_period   ?? 43;
    document.getElementById('trend_factor').value= tr.factor       ?? 1.0;

    const w = d.signal_weights || {};
    const keys = Object.keys(w);
    if (keys.length === 0) {
      document.getElementById('weights').innerHTML =
        '<span style="color:#8b949e">Нет данных по сигналам (нужно ≥20 сделок)</span>';
    } else {
      document.getElementById('weights').innerHTML = keys.map(k =>
        `<div class="info-row"><span class="info-key">${k}</span>
         <span class="info-val">${(w[k]*100).toFixed(1)}%</span></div>`
      ).join('');
    }
  } catch(e) {
    console.error(e);
  }
}

async function postSettings(body, btnId, msgId, btnLabel) {
  const btn = document.getElementById(btnId);
  const msg = document.getElementById(msgId);
  btn.disabled = true;
  btn.textContent = 'Сохранение...';
  try {
    const r = await fetch('/api/settings', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const d = await r.json();
    msg.style.display = 'block';
    if (d.ok) {
      msg.className = 'msg-ok';
      msg.textContent = 'Настройки сохранены и применены без перезапуска бота';
    } else {
      msg.className = 'msg-err';
      msg.textContent = 'Ошибка: ' + (d.error || 'неизвестная ошибка');
    }
  } catch(err) {
    msg.style.display = 'block';
    msg.className = 'msg-err';
    msg.textContent = 'Сетевая ошибка: ' + err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = btnLabel;
  }
}

document.getElementById('analysisForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  await postSettings({
    volume_multiplier: parseFloat(document.getElementById('volume_multiplier').value),
    price_threshold:   parseFloat(document.getElementById('price_threshold').value),
    check_interval:    parseInt(document.getElementById('check_interval').value),
    history_size:      parseInt(document.getElementById('history_size').value),
  }, 'saveBtn', 'msg', '&#x1F4BE; Сохранить и применить');
});

document.getElementById('indicatorsForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  await postSettings({
    indicators: {
      wavetrend: {
        n1:           parseInt(document.getElementById('wt_n1').value),
        n2:           parseInt(document.getElementById('wt_n2').value),
        ob_threshold: parseFloat(document.getElementById('wt_ob').value),
        os_threshold: parseFloat(document.getElementById('wt_os').value),
      },
      trend: {
        atr_period: parseInt(document.getElementById('trend_atr').value),
        factor:     parseFloat(document.getElementById('trend_factor').value),
      },
    },
  }, 'saveIndBtn', 'msgInd', '&#x1F4BE; Сохранить индикаторы');
});

loadSettings();
</script>
</body>
</html>
"""


_BACKTEST_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Бэктест — Crypto Bot</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #c9d1d9; }
  header { background: #161b22; padding: 16px 24px; border-bottom: 1px solid #30363d;
           display: flex; justify-content: space-between; align-items: center; }
  header h1 { font-size: 1.25rem; color: #58a6ff; }
  nav a { color: #58a6ff; text-decoration: none; font-size: .9rem; margin-left: 16px; }
  nav a:hover { text-decoration: underline; }
  main { padding: 24px; max-width: 1200px; margin: 0 auto; }
  section { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
            padding: 20px 24px; margin-bottom: 24px; }
  h2 { font-size: .9rem; color: #8b949e; text-transform: uppercase;
       letter-spacing: .08em; margin-bottom: 16px; border-bottom: 1px solid #21262d; padding-bottom: 8px; }
  .row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
  .chip { display: inline-flex; align-items: center; gap: 6px; background: #0d1117;
          border: 1px solid #30363d; border-radius: 20px; padding: 4px 12px; font-size: .82rem; cursor: pointer; }
  .chip input[type=checkbox] { accent-color: #58a6ff; }
  .chip.period { border-color: #d29922; }
  .btn { background: #238636; color: #fff; border: none; border-radius: 6px;
         padding: 9px 22px; font-size: .9rem; cursor: pointer; }
  .btn:hover { background: #2ea043; }
  .btn:disabled { background: #21262d; color: #8b949e; cursor: not-allowed; }
  .btn-stop { background: #da3633; }
  .btn-stop:hover { background: #f85149; }
  #statusBar { display: flex; align-items: center; gap: 12px; font-size: .88rem; margin-top: 12px; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: #8b949e; }
  .dot.running { background: #d29922; animation: pulse 1s infinite; }
  .dot.done { background: #3fb950; }
  .dot.error { background: #f85149; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
  #logBox { background: #0d1117; border: 1px solid #21262d; border-radius: 6px;
            padding: 12px; font-family: monospace; font-size: .78rem; color: #8b949e;
            max-height: 200px; overflow-y: auto; white-space: pre-wrap; display: none; }
  table { width: 100%; border-collapse: collapse; font-size: .85rem; }
  th { text-align: left; padding: 8px 10px; background: #161b22;
       color: #8b949e; border-bottom: 1px solid #30363d; }
  td { padding: 7px 10px; border-bottom: 1px solid #21262d; }
  tr:hover td { background: #1c2128; }
  .green { color: #3fb950; } .red { color: #f85149; } .blue { color: #58a6ff; }
  .yellow { color: #d29922; }
  .sep td { border-top: 1px solid #30363d; background: #0d1117 !important; height: 6px; }
  .note { color: #8b949e; font-size: .85rem; font-style: italic; padding: 12px 0; }
  .meta { font-size: .78rem; color: #8b949e; margin-top: 8px; }
  .cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
  .card { background: #0d1117; border: 1px solid #30363d; border-radius: 8px;
          padding: 14px 18px; min-width: 130px; flex: 1; }
  .card .label { font-size: .72rem; color: #8b949e; margin-bottom: 4px; }
  .card .value { font-size: 1.4rem; font-weight: 700; }
</style>
</head>
<body>
<header>
  <h1>&#x1F4C8; Бэктест стратегии</h1>
  <nav>
    <a href="/">&#x1F4CA; Дашборд</a>
    <a href="/settings">&#x2699;&#xFE0F; Настройки</a>
  </nav>
</header>
<main>

  <section>
    <h2>&#x1F9EA; Настройки запуска</h2>
    <p style="font-size:.82rem;color:#8b949e;margin-bottom:12px;">
      Таймфрейм: <b style="color:#c9d1d9">1h</b> &nbsp;|&nbsp;
      HTF фильтр: <b style="color:#3fb950">вкл (4h)</b> &nbsp;|&nbsp;
      Weekly PP: <b style="color:#3fb950">вкл</b> &nbsp;|&nbsp;
      TSL: <b style="color:#3fb950">вкл (+1R)</b>
    </p>

    <h2 style="margin-top:16px;">Символы</h2>
    <div class="row" id="symbolsRow"></div>

    <h2>Периоды</h2>
    <div class="row" id="periodsRow"></div>

    <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:4px;">
      <button class="btn" id="runBtn" onclick="runBacktest()">&#x25B6; Запустить бэктест</button>
      <button class="btn btn-stop" id="stopBtn" onclick="stopPoll()" style="display:none">&#x25A0; Стоп опроса</button>
      <label style="display:flex;align-items:center;gap:4px;font-size:0.85em;">
        ATR Period
        <input type="number" id="atrPeriod" value="14" min="5" max="200" step="1"
               style="width:60px;padding:4px;background:#1e2230;border:1px solid #3a4060;color:#e0e6ff;border-radius:4px;">
      </label>
      <label style="display:flex;align-items:center;gap:4px;font-size:0.85em;">
        ATR Factor
        <input type="number" id="atrFactor" value="1.5" min="0.5" max="5" step="0.1"
               style="width:60px;padding:4px;background:#1e2230;border:1px solid #3a4060;color:#e0e6ff;border-radius:4px;">
      </label>
      <span style="font-size:0.75em;color:#6b7fa3;">(Live bot: 43 / 1.0)</span>
    </div>

    <details style="margin-top:16px;">
      <summary style="cursor:pointer;color:#8b949e;font-size:0.85em;letter-spacing:.06em;text-transform:uppercase;">
        &#x2699;&#xFE0F; Конструктор стратегии
      </summary>
      <div style="margin-top:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;">

        <div>
          <div style="font-size:0.78em;color:#8b949e;margin-bottom:6px;">Сигналы</div>
          <label class="chip"><input type="checkbox" id="useWt" checked> WT crossover</label>
          <label class="chip"><input type="checkbox" id="useDivergence" checked> Дивергенции</label>
          <div style="margin-left:16px;margin-top:4px;">
            <label class="chip"><input type="checkbox" id="divRegular" checked> Regular</label>
            <label class="chip"><input type="checkbox" id="divHidden" checked> Hidden</label>
          </div>
          <label class="chip"><input type="checkbox" id="useAnomaly" checked> Аномалии объёма</label>
          <label class="chip"><input type="checkbox" id="useTrend" checked> Тренд (EMA/ADX)</label>
          <label class="chip"><input type="checkbox" id="useFvg"> FVG фильтр</label>
          <label class="chip"><input type="checkbox" id="useFvgBoost"> FVG буст</label>
          <label class="chip"><input type="checkbox" id="usePivotBoost"> Pivot буст</label>
          <label class="chip"><input type="checkbox" id="useReentry"> Перезаход после SL</label>
        </div>

        <div>
          <div style="font-size:0.78em;color:#8b949e;margin-bottom:6px;">Таймфреймы</div>
          <label style="display:flex;align-items:center;gap:6px;font-size:0.85em;margin-bottom:6px;">
            Сигнал
            <select id="btTimeframe" style="padding:4px;background:#1e2230;border:1px solid #3a4060;color:#e0e6ff;border-radius:4px;">
              <option value="15m">15m</option>
              <option value="1h" selected>1h</option>
              <option value="4h">4h</option>
            </select>
          </label>
          <label style="display:flex;align-items:center;gap:6px;font-size:0.85em;">
            FVG TF
            <select id="btFvgTf" style="padding:4px;background:#1e2230;border:1px solid #3a4060;color:#e0e6ff;border-radius:4px;">
              <option value="3m">3m</option>
              <option value="15m" selected>15m</option>
            </select>
          </label>
        </div>

        <div>
          <div style="font-size:0.78em;color:#8b949e;margin-bottom:6px;">Пороги WT</div>
          <label style="display:flex;align-items:center;gap:6px;font-size:0.85em;margin-bottom:6px;">
            OB
            <input type="number" id="btWtOb" value="60" min="40" max="90" step="1"
                   style="width:60px;padding:4px;background:#1e2230;border:1px solid #3a4060;color:#e0e6ff;border-radius:4px;">
          </label>
          <label style="display:flex;align-items:center;gap:6px;font-size:0.85em;">
            OS
            <input type="number" id="btWtOs" value="-60" min="-90" max="-40" step="1"
                   style="width:60px;padding:4px;background:#1e2230;border:1px solid #3a4060;color:#e0e6ff;border-radius:4px;">
          </label>
        </div>

        <div>
          <div style="font-size:0.78em;color:#8b949e;margin-bottom:6px;">Take Profit / TSL</div>
          <label class="chip"><input type="radio" name="tpType" value="fixed_2r" checked> Фиксированный R</label>
          <label class="chip"><input type="radio" name="tpType" value="next_pivot"> Следующий пивот</label>
          <label class="chip"><input type="radio" name="tpType" value="tsl_only"> Только TSL</label>
          <label style="display:flex;align-items:center;gap:6px;font-size:0.85em;margin-top:8px;">
            TP (R)
            <input type="number" id="btTpR" value="2" min="1" max="10" step="0.5"
                   style="width:55px;padding:4px;background:#1e2230;border:1px solid #3a4060;color:#e0e6ff;border-radius:4px;">
          </label>
          <label style="display:flex;align-items:center;gap:6px;font-size:0.85em;margin-top:6px;">
            TSL при (R)
            <input type="number" id="btTslActivation" value="1" min="0.5" max="5" step="0.5"
                   style="width:55px;padding:4px;background:#1e2230;border:1px solid #3a4060;color:#e0e6ff;border-radius:4px;">
          </label>
          <label style="display:flex;align-items:center;gap:6px;font-size:0.85em;margin-top:6px;">
            TSL lag (баров)
            <input type="number" id="btTslLag" value="0" min="0" max="10" step="1"
                   style="width:55px;padding:4px;background:#1e2230;border:1px solid #3a4060;color:#e0e6ff;border-radius:4px;">
          </label>
        </div>

      </div>
    </details>

    <div id="statusBar"><div class="dot" id="dot"></div><span id="statusText">Ожидание запуска</span></div>
    <div id="logBox"></div>
  </section>

  <section>
    <h2>&#x1F4CA; Результаты</h2>
    <div class="cards" id="summaryCards"></div>
    <div id="resultsContent"><p class="note">Нет данных. Запустите бэктест или ранее сохранённые результаты отсутствуют.</p></div>
    <p class="meta" id="generatedAt"></p>
  </section>

</main>
<script>
const DEFAULT_SYMBOLS = ["BTC/USDT","ETH/USDT","SOL/USDT","GRT/USDT","BLESS/USDT","XNY/USDT"];
const DEFAULT_PERIODS = ["Q1-2024","Q2-2024","Q3-2024","Q4-2024"];

// Render checkboxes
function renderChips(containerId, items, cls) {
  const c = document.getElementById(containerId);
  items.forEach(v => {
    const label = document.createElement('label');
    label.className = 'chip ' + (cls||'');
    label.innerHTML = `<input type="checkbox" value="${v}" checked> ${v}`;
    c.appendChild(label);
  });
}
renderChips('symbolsRow', DEFAULT_SYMBOLS, '');
renderChips('periodsRow', DEFAULT_PERIODS, 'period');

function getChecked(containerId) {
  return [...document.querySelectorAll(`#${containerId} input:checked`)].map(e => e.value);
}

const fmtR = v => v == null ? '—' : (v > 0 ? '+' : '') + (+v).toFixed(2);
const fmtPct = v => v == null ? '—' : (v > 0 ? '+' : '') + (+v).toFixed(1) + '%';
const colorCls = v => v > 0 ? 'green' : (v < 0 ? 'red' : '');

let pollTimer = null;

async function runBacktest() {
  const symbols = getChecked('symbolsRow');
  const periods  = getChecked('periodsRow');
  if (!symbols.length || !periods.length) {
    alert('Выберите хотя бы один символ и один период.');
    return;
  }
  document.getElementById('runBtn').disabled = true;
  document.getElementById('stopBtn').style.display = 'inline-block';
  setStatus('running', 'Запуск...');
  document.getElementById('logBox').style.display = 'block';
  document.getElementById('logBox').textContent = '';

  const atr_period = parseInt(document.getElementById('atrPeriod').value) || 14;
  const atr_factor = parseFloat(document.getElementById('atrFactor').value) || 1.5;
  const use_wt = document.getElementById('useWt').checked;
  const use_divergence = document.getElementById('useDivergence').checked;
  const div_regular = document.getElementById('divRegular').checked;
  const div_hidden = document.getElementById('divHidden').checked;
  const use_anomaly = document.getElementById('useAnomaly').checked;
  const use_trend = document.getElementById('useTrend').checked;
  const use_fvg = document.getElementById('useFvg').checked;
  const wt_ob = parseFloat(document.getElementById('btWtOb').value) || 60;
  const wt_os = parseFloat(document.getElementById('btWtOs').value) || -60;
  const tp_type = (document.querySelector('input[name="tpType"]:checked') || {value:'fixed_2r'}).value;
  try {
    await fetch('/api/backtest/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({symbols, periods, atr_period, atr_factor,
        use_wt, use_divergence, div_regular, div_hidden,
        use_anomaly, use_trend, use_fvg, wt_ob, wt_os, tp_type,
        tp_r: parseFloat(document.getElementById('btTpR')?.value) || 2.0,
        tsl_activation_r: parseFloat(document.getElementById('btTslActivation')?.value) || 1.0,
        tsl_lag_bars: parseInt(document.getElementById('btTslLag')?.value) || 0,
        use_reentry: document.getElementById('useReentry')?.checked || false,
        use_fvg_boost: document.getElementById('useFvgBoost')?.checked || false,
        use_pivot_boost: document.getElementById('usePivotBoost')?.checked || false,
        fvg_timeframe: document.getElementById('btFvgTf')?.value || '15m',
        timeframe: document.getElementById('btTimeframe')?.value || '1h',
      }),
    });
  } catch(e) {
    setStatus('error', 'Ошибка запроса: ' + e.message);
    document.getElementById('runBtn').disabled = false;
    return;
  }
  pollStatus();
}

function stopPoll() {
  if (pollTimer) clearTimeout(pollTimer);
  document.getElementById('stopBtn').style.display = 'none';
}

async function pollStatus() {
  try {
    const r = await fetch('/api/backtest/status');
    const d = await r.json();
    const log = document.getElementById('logBox');
    if (d.log && d.log.length) {
      log.textContent = d.log.join('\\n');
      log.scrollTop = log.scrollHeight;
    }
    if (d.running) {
      setStatus('running', 'Выполняется... (' + (d.progress||'') + ')');
      pollTimer = setTimeout(pollStatus, 2000);
    } else if (d.error) {
      setStatus('error', 'Ошибка: ' + d.error);
      document.getElementById('runBtn').disabled = false;
      document.getElementById('stopBtn').style.display = 'none';
    } else {
      setStatus('done', 'Готово');
      document.getElementById('runBtn').disabled = false;
      document.getElementById('stopBtn').style.display = 'none';
      loadResults();
    }
  } catch(e) {
    pollTimer = setTimeout(pollStatus, 3000);
  }
}

function setStatus(state, text) {
  const dot = document.getElementById('dot');
  dot.className = 'dot ' + state;
  document.getElementById('statusText').textContent = text;
}

async function loadResults() {
  try {
    const r = await fetch('/api/backtest/results');
    const d = await r.json();
    if (!d.results || !d.results.length) return;
    renderResults(d.results);
    if (d.generated_at) {
      document.getElementById('generatedAt').textContent =
        'Сгенерировано: ' + new Date(d.generated_at).toLocaleString('ru');
    }
  } catch(e) {}
}

function renderResults(rows) {
  // Summary cards
  const validRows = rows.filter(r => r.total_trades >= 5);
  if (validRows.length) {
    const avgWR = validRows.reduce((s,r)=>s+r.win_rate,0)/validRows.length;
    const avgR  = validRows.reduce((s,r)=>s+r.avg_r_multiple,0)/validRows.length;
    const best  = rows.reduce((a,b)=>b.total_return_pct>a.total_return_pct?b:a);
    document.getElementById('summaryCards').innerHTML = `
      <div class="card"><div class="label">Средний WR</div>
        <div class="value ${avgWR>=50?'green':'red'}">${avgWR.toFixed(1)}%</div></div>
      <div class="card"><div class="label">Средний AvgR</div>
        <div class="value ${colorCls(avgR)}">${fmtR(avgR)}</div></div>
      <div class="card"><div class="label">Лучшая пара</div>
        <div class="value blue" style="font-size:1rem">${best.symbol}</div></div>
      <div class="card"><div class="label">Лучший период</div>
        <div class="value blue" style="font-size:1rem">${best.period}</div></div>
      <div class="card"><div class="label">Лучший Return</div>
        <div class="value ${colorCls(best.total_return_pct)}">${fmtPct(best.total_return_pct)}</div></div>
    `;
  }

  // Group by symbol
  const symbols = [...new Set(rows.map(r=>r.symbol))];
  let html = `<table><thead><tr>
    <th>Символ</th><th>Период</th><th>Сделок</th><th>WR%</th>
    <th>AvgR</th><th>Sharpe</th><th>MaxDD%</th><th>Return%</th>
    <th>W/L</th>
  </tr></thead><tbody>`;

  symbols.forEach((sym, si) => {
    if (si > 0) html += '<tr class="sep"><td colspan="9"></td></tr>';
    rows.filter(r=>r.symbol===sym).forEach(r => {
      const wr = r.win_rate;
      html += `<tr>
        <td class="blue">${r.symbol}</td>
        <td>${r.period}</td>
        <td>${r.total_trades}</td>
        <td class="${wr>=50?'green':'red'}">${wr.toFixed(1)}%</td>
        <td class="${colorCls(r.avg_r_multiple)}">${fmtR(r.avg_r_multiple)}</td>
        <td class="${colorCls(r.sharpe_ratio)}">${(+r.sharpe_ratio).toFixed(2)}</td>
        <td class="${colorCls(-r.max_drawdown_pct)}">${(+r.max_drawdown_pct).toFixed(1)}%</td>
        <td class="${colorCls(r.total_return_pct)}">${fmtPct(r.total_return_pct)}</td>
        <td><span class="green">${r.wins}</span>/<span class="red">${r.losses}</span></td>
      </tr>`;
    });
  });

  html += '</tbody></table>';
  document.getElementById('resultsContent').innerHTML = html;
}

loadResults();
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


async def _handle_settings_page(request: web.Request) -> web.Response:
    return web.Response(text=_SETTINGS_HTML, content_type="text/html", charset="utf-8")


async def _handle_settings_get(request: web.Request) -> web.Response:
    """Возвращает текущие настройки: параметры анализа + адаптивные веса из БД."""
    cfg = request.app["config"]
    engine: PerformanceEngine = request.app["engine"]

    analysis = cfg.get("analysis", {})
    safe_analysis = {
        "volume_multiplier": analysis.get("volume_multiplier", 5.0),
        "price_threshold":   analysis.get("price_threshold", 7.0),
        "check_interval":    analysis.get("check_interval", 60),
        "history_size":      analysis.get("history_size", 200),
    }

    # Адаптивные веса: вычисляем на лету из PerformanceEngine
    signal_weights: dict = {}
    base = {
        "anomaly":        0.30,
        "wt_signal":      0.10,
        "mtf_alert":      0.25,
        "trend_signal":   0.10,
        "divergence":     0.05,
        "pivot_reversal": 0.20,
    }
    try:
        for row in engine.by_signal_type():
            sig = row.get("signal_type") or ""
            avg_r = float(row.get("avg_r") or 0.0)
            total = row.get("total", 0)
            if sig in base:
                if total >= 20:
                    factor = max(0.5, min(2.0, 1.0 + avg_r * 0.4))
                    signal_weights[sig] = round(base[sig] * factor, 4)
                else:
                    signal_weights[sig] = base[sig]
    except Exception:
        pass

    ind_cfg = analysis.get("indicators", {})
    wt_cfg  = ind_cfg.get("wavetrend", {})
    tr_cfg  = ind_cfg.get("trend", {})
    safe_indicators = {
        "wavetrend": {
            "n1":           wt_cfg.get("n1", 10),
            "n2":           wt_cfg.get("n2", 21),
            "ob_threshold": wt_cfg.get("ob_threshold", 60),
            "os_threshold": wt_cfg.get("os_threshold", -60),
        },
        "trend": {
            "atr_period": tr_cfg.get("atr_period", 43),
            "factor":     tr_cfg.get("factor", 1.0),
        },
    }

    data = {"analysis": safe_analysis, "indicators": safe_indicators, "signal_weights": signal_weights}
    return web.Response(
        text=json.dumps(data, ensure_ascii=False),
        content_type="application/json",
        charset="utf-8",
    )


async def _handle_settings_post(request: web.Request) -> web.Response:
    """Сохраняет параметры анализа в config.yaml и перезагружает конфиг (hot-reload)."""
    cfg = request.app["config"]
    try:
        body = await request.json()
    except Exception:
        return web.Response(
            status=400,
            text=json.dumps({"ok": False, "error": "invalid JSON"}),
            content_type="application/json",
        )

    # Если передан блок indicators — сохраняем только его
    ind_body = body.get("indicators")
    if ind_body is not None:
        try:
            wt  = ind_body.get("wavetrend", {})
            tr  = ind_body.get("trend", {})
            n1  = int(wt.get("n1", 10))
            n2  = int(wt.get("n2", 21))
            ob  = float(wt.get("ob_threshold", 60))
            os_ = float(wt.get("os_threshold", -60))
            atr = int(tr.get("atr_period", 43))
            fac = float(tr.get("factor", 1.0))
            errors = []
            if not (5 <= n1 <= 30):   errors.append("n1 должен быть 5-30")
            if not (10 <= n2 <= 50):  errors.append("n2 должен быть 10-50")
            if not (30 <= ob <= 100): errors.append("ob_threshold должен быть 30-100")
            if not (-100 <= os_ <= -30): errors.append("os_threshold должен быть -100 до -30")
            if not (5 <= atr <= 200): errors.append("atr_period должен быть 5-200")
            if not (0.1 <= fac <= 5): errors.append("factor должен быть 0.1-5")
        except (TypeError, ValueError) as e:
            errors = [f"Некорректный тип данных: {e}"]
        if errors:
            return web.Response(
                text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
                content_type="application/json", charset="utf-8",
            )
        ok = cfg.save_indicators(wt_n1=n1, wt_n2=n2, wt_ob=ob, wt_os=os_,
                                 trend_atr_period=atr, trend_factor=fac)
        return web.Response(
            text=json.dumps({"ok": ok, "error": None if ok else "ошибка записи файла"}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )

    errors = []
    vol      = body.get("volume_multiplier")
    thr      = body.get("price_threshold")
    interval = body.get("check_interval")
    history  = body.get("history_size")

    try:
        if vol is None or not (1.0 <= float(vol) <= 100.0):
            errors.append("volume_multiplier должен быть от 1 до 100")
        if thr is None or not (0.5 <= float(thr) <= 50.0):
            errors.append("price_threshold должен быть от 0.5 до 50")
        if interval is None or not (10 <= int(interval) <= 3600):
            errors.append("check_interval должен быть от 10 до 3600 сек")
        if history is None or not (50 <= int(history) <= 1000):
            errors.append("history_size должен быть от 50 до 1000")
    except (TypeError, ValueError) as e:
        errors.append(f"Некорректный тип данных: {e}")

    if errors:
        return web.Response(
            text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
            content_type="application/json",
            charset="utf-8",
        )

    ok = cfg.save_analysis(
        volume_multiplier=float(vol),
        price_threshold=float(thr),
        check_interval=int(interval),
        history_size=int(history),
    )
    return web.Response(
        text=json.dumps(
            {"ok": ok, "error": None if ok else "ошибка записи файла"},
            ensure_ascii=False,
        ),
        content_type="application/json",
        charset="utf-8",
    )


async def _handle_backtest_page(request: web.Request) -> web.Response:
    return web.Response(text=_BACKTEST_HTML, content_type="text/html", charset="utf-8")


async def _handle_backtest_results(request: web.Request) -> web.Response:
    """Возвращает последние сохранённые результаты из backtest_results.json."""
    path = "backtest_results.json"
    if not os.path.exists(path):
        return web.Response(
            text=json.dumps({"results": [], "generated_at": None}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return web.Response(
            text=json.dumps(data, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )
    except Exception as e:
        return web.Response(status=500, text=str(e))


async def _handle_backtest_status(request: web.Request) -> web.Response:
    """Возвращает текущий статус фонового бэктеста."""
    state = request.app["backtest_state"]
    total = state.get("total", 0)
    done = state.get("done", 0)
    progress = f"{done}/{total}" if total else ""
    return web.Response(
        text=json.dumps({
            "running": state["running"],
            "error": state.get("error"),
            "progress": progress,
            "log": state.get("log", [])[-60:],  # последние 60 строк
        }, ensure_ascii=False),
        content_type="application/json", charset="utf-8",
    )


async def _handle_backtest_run(request: web.Request) -> web.Response:
    """Запускает бэктест в фоне. POST /api/backtest/run."""
    state = request.app["backtest_state"]
    if state["running"]:
        return web.Response(
            text=json.dumps({"ok": False, "error": "Бэктест уже запущен"}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )
    try:
        body = await request.json()
    except Exception:
        body = {}

    symbols = body.get("symbols") or None
    period_names = body.get("periods") or None
    atr_period = int(body.get("atr_period", 14))
    atr_factor = float(body.get("atr_factor", 1.5))
    use_wt = bool(body.get("use_wt", True))
    use_divergence = bool(body.get("use_divergence", True))
    div_regular = bool(body.get("div_regular", True))
    div_hidden = bool(body.get("div_hidden", True))
    use_anomaly = bool(body.get("use_anomaly", True))
    use_trend = bool(body.get("use_trend", True))
    use_fvg = bool(body.get("use_fvg", False))
    use_fvg_boost = bool(body.get("use_fvg_boost", False))
    use_pivot_boost = bool(body.get("use_pivot_boost", False))
    fvg_timeframe = str(body.get("fvg_timeframe", "15m"))
    wt_ob = float(body.get("wt_ob", 60.0))
    wt_os = float(body.get("wt_os", -60.0))
    tp_type = str(body.get("tp_type", "fixed_2r"))
    tp_r = float(body.get("tp_r", 2.0))
    tsl_activation_r = float(body.get("tsl_activation_r", 1.0))
    tsl_lag_bars = int(body.get("tsl_lag_bars", 0))
    use_reentry = bool(body.get("use_reentry", False))
    timeframe = str(body.get("timeframe", "1h"))

    # Конвертируем period_names в (name, start, end) tuples
    from backtesting_engine import DEFAULT_PERIODS, DEFAULT_SYMBOLS, run_comprehensive_backtest
    all_periods_map = {p[0]: p for p in DEFAULT_PERIODS}
    if period_names:
        periods = [all_periods_map[n] for n in period_names if n in all_periods_map] or None
    else:
        periods = None
    if not symbols:
        symbols = DEFAULT_SYMBOLS

    state["running"] = True
    state["error"] = None
    state["log"] = []
    state["done"] = 0
    state["total"] = len(symbols) * len(periods or DEFAULT_PERIODS)

    def on_progress(msg: str) -> None:
        state["log"].append(msg)
        if msg.strip().startswith("сд=") or "ПРОПУСК" in msg:
            state["done"] = min(state["done"] + 1, state["total"])

    async def _run():
        try:
            await run_comprehensive_backtest(
                symbols=symbols, periods=periods, on_progress=on_progress,
                atr_period=atr_period, atr_factor=atr_factor,
                timeframe=timeframe,
                use_wt=use_wt, use_divergence=use_divergence,
                div_regular=div_regular, div_hidden=div_hidden,
                use_anomaly=use_anomaly, use_trend=use_trend,
                use_fvg=use_fvg, fvg_timeframe=fvg_timeframe,
                use_fvg_boost=use_fvg_boost,
                use_pivot_boost=use_pivot_boost,
                wt_ob=wt_ob, wt_os=wt_os,
                tp_type=tp_type, tp_r=tp_r,
                tsl_activation_r=tsl_activation_r,
                tsl_lag_bars=tsl_lag_bars,
                use_reentry=use_reentry,
            )
        except Exception as e:
            state["error"] = str(e)
            logger.exception("Backtest background error: %s", e)
        finally:
            state["running"] = False

    asyncio.create_task(_run())

    return web.Response(
        text=json.dumps({"ok": True}, ensure_ascii=False),
        content_type="application/json", charset="utf-8",
    )


async def start_dashboard(db_path: str = "subscriptions.db", host: str = "0.0.0.0", port: int = 8000, config=None) -> None:
    """Запускает aiohttp-сервер. Вызывать через asyncio.create_task()."""
    import asyncio
    if config is None:
        from core.config_loader import config as _cfg
        config = _cfg

    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

    app = web.Application()
    app["engine"] = PerformanceEngine(db_path=db_path)
    app["config"] = config
    app["backtest_state"] = {"running": False, "error": None, "log": [], "done": 0, "total": 0}
    app.router.add_get("/", _handle_index)
    app.router.add_get("/api/stats", _handle_stats)
    app.router.add_get("/settings", _handle_settings_page)
    app.router.add_get("/api/settings", _handle_settings_get)
    app.router.add_post("/api/settings", _handle_settings_post)
    app.router.add_get("/backtest", _handle_backtest_page)
    app.router.add_get("/api/backtest/results", _handle_backtest_results)
    app.router.add_get("/api/backtest/status", _handle_backtest_status)
    app.router.add_post("/api/backtest/run", _handle_backtest_run)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    try:
        await site.start()
        logger.info(
            "Dashboard запущен: http://%s:%s  |  Настройки: http://%s:%s/settings",
            host, port, host, port,
        )
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        logger.exception("Dashboard error: %s", e)
    finally:
        await runner.cleanup()
