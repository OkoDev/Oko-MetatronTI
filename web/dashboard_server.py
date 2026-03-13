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
  .badge-tp  { background: #1a3a1f; color: #3fb950; }
  .badge-sl  { background: #3a1a1a; color: #f85149; }
  .badge-tsl { background: #2a1a3a; color: #b87eff; }
  .badge-exp { background: #2d2a1a; color: #d29922; }
  .badge-open{ background: #1a2a3a; color: #58a6ff; }
  .purple { color: #b87eff; }
  #loader { text-align: center; padding: 60px; color: #8b949e; font-size: 1.1rem; }
  .note { color: #8b949e; font-size: .85rem; font-style: italic; padding: 12px 0; }
  .filter-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; align-items: center; }
  .filter-bar select, .filter-bar input { background: #161b22; border: 1px solid #30363d;
    color: #c9d1d9; border-radius: 6px; padding: 4px 8px; font-size: .8rem; cursor: pointer; }
  .filter-bar label { font-size: .8rem; color: #8b949e; }
  .filter-bar button { background: #21262d; border: 1px solid #30363d; color: #8b949e;
    border-radius: 6px; padding: 4px 10px; font-size: .8rem; cursor: pointer; }
  .filter-bar button:hover { color: #c9d1d9; border-color: #8b949e; }
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
  const map = {TP:'badge-tp', SL:'badge-sl', TSL:'badge-tsl', EXPIRED:'badge-exp', OPEN:'badge-open'};
  return `<span class="badge ${map[s]||''}">${s}</span>`;
};
const color = (v, inv=false) => {
  if (v == null) return '';
  const pos = inv ? v < 0 : v > 0;
  return pos ? 'green' : (v === 0 ? '' : 'red');
};

async function load() {
  try {
    const [r1, r2] = await Promise.all([fetch('/api/stats'), fetch('/api/stats/confluence')]);
    const d = await r1.json();
    const cf = await r2.json();
    render(d, cf);
    document.getElementById('updated').textContent =
      'Обновлено: ' + new Date().toLocaleTimeString('ru');
  } catch(e) {
    document.getElementById('updated').textContent = 'Ошибка загрузки: ' + e.message;
  }
}

function confluenceBreakdown(cf) {
  if (!cf) return '';
  const tbl = (rows, cols, headers) => {
    if (!rows || !rows.length) return '<p class="note">Нет данных</p>';
    const head = headers.map(h => `<th>${h}</th>`).join('');
    const body = rows.map(r => `<tr>${cols.map(c => {
      const v = r[c];
      if (c === 'wr') return `<td class="${v >= 45 ? 'green' : v >= 30 ? '' : 'red'}">${v ?? '—'}%</td>`;
      if (c === 'avg_r') return `<td class="${color(v)}">${v ?? '—'}</td>`;
      return `<td>${v ?? '—'}</td>`;
    }).join('')}</tr>`).join('');
    return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  };
  return `
  <section>
    <h2>Confluence — разбивка WR</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
      <div>
        <h3 style="font-size:.9rem;color:#8b949e;margin:0 0 6px">По направлению</h3>
        ${tbl(cf.by_direction, ['direction','total','wr','avg_r'], ['Направление','Сделок','WR%','avg R'])}
      </div>
      <div>
        <h3 style="font-size:.9rem;color:#8b949e;margin:0 0 6px">По strength</h3>
        ${tbl(cf.by_strength, ['range','total','wr','avg_r'], ['Strength','Сделок','WR%','avg R'])}
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div>
        <h3 style="font-size:.9rem;color:#8b949e;margin:0 0 6px">По факторам (новые сделки)</h3>
        ${cf.by_factor && cf.by_factor.length
          ? tbl(cf.by_factor, ['factor','total','wr','avg_r'], ['Фактор','Сделок','WR%','avg R'])
          : '<p class="note">Факторы будут накапливаться в новых сделках</p>'}
      </div>
      <div>
        <h3 style="font-size:.9rem;color:#8b949e;margin:0 0 6px">По TP источнику</h3>
        ${tbl(cf.by_tp_source, ['source','total','wr','avg_r'], ['TP source','Сделок','WR%','avg R'])}
      </div>
    </div>
  </section>`;
}

function render(d, cf) {
  const s = d.summary || {};

  // --- EV и Profit Factor ---
  const wr = (s.win_rate ?? 0) / 100;
  const rWin  = s.avg_r_win  ?? 0;
  const rLoss = s.avg_r_loss ?? 0;   // отрицательное число (напр. -0.80)
  const ev = wr * rWin + (1 - wr) * rLoss;
  const evRound = Math.round(ev * 100) / 100;
  const pfDenom = (1 - wr) * Math.abs(rLoss);
  const pf = pfDenom > 0 ? Math.round(wr * rWin / pfDenom * 100) / 100 : null;

  // --- Прогноз депозита (с реинвестированием) ---
  const cpdAll = s.closed_per_day ?? 0; // все сигналы бота (79+)

  // Макс. ожидаемая серия проигрышей: log(N) / log(1/lossRate)
  function maxLoseStreak(n, wr) {
    const lossRate = 1 - wr;
    if (lossRate <= 0) return 0;
    return Math.round(Math.log(n) / Math.log(1 / lossRate));
  }
  function maxDD(streak, riskPct) {
    return Math.round((1 - Math.pow(1 - riskPct / 100, streak)) * 1000) / 10;
  }

  const projRow = ev > 0 ? `
    <div class="card" style="min-width:380px;flex:2;border-color:#3fb95044" id="projCard">
      <div class="label" style="font-size:.85rem;color:#c9d1d9;font-weight:600">
        &#x1F4B0; Калькулятор роста депозита (compound)
        <span style="color:#555;font-size:.7rem"> EV = ${evRound > 0 ? '+' : ''}${evRound.toFixed(2)}R/сделку</span>
      </div>

      <div style="display:flex;gap:10px;align-items:center;margin:8px 0 10px;flex-wrap:wrap">
        <div><div class="label">Депозит $</div>
          <input id="projDeposit" type="number" value="100" min="10" max="1000000"
            style="width:90px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:4px;padding:4px 8px;font-size:.9rem"
            oninput="updateProj()"></div>
        <div><div class="label">Риск %/сделку</div>
          <input id="projRisk" type="number" value="1" min="0.05" max="10" step="0.05"
            style="width:70px;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:4px;padding:4px 8px;font-size:.9rem"
            oninput="updateProj()"></div>
        <div><div class="label">Режим</div>
          <select id="projMode" style="background:#0d1117;border:1px solid #30363d;color:#c9d1d9;border-radius:4px;padding:4px 8px;font-size:.85rem" onchange="updateProj()">
            <option value="manual3">Ручной · 3/день</option>
            <option value="manual5">Ручной · 5/день</option>
            <option value="manual10">Ручной · 10/день</option>
            <option value="auto" ${cpdAll > 0 ? '' : 'disabled'}>Авторежим · все (${cpdAll}/день)</option>
          </select></div>
      </div>

      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:4px">
        <div style="text-align:center">
          <div class="label">Рост за 30 дней</div>
          <div class="value green" style="font-size:1.6rem" id="projPct">...</div>
          <div class="label" id="projFin">...</div>
        </div>
        <div style="text-align:center">
          <div class="label">Макс. серия SL</div>
          <div class="value yellow" style="font-size:1.6rem" id="projStreak">...</div>
          <div class="label">подряд убыточных</div>
        </div>
        <div style="text-align:center">
          <div class="label">Макс. просадка</div>
          <div class="value red" style="font-size:1.6rem" id="projDD">...</div>
          <div class="label">при серии SL</div>
        </div>
      </div>

      <div style="margin-top:10px;font-size:.75rem;color:#555;border-top:1px solid #21262d;padding-top:6px">
        ⚠️ Compound-прогноз на основе симуляции. WR 33% при 2370 сделок → до 19 SL подряд статистически.
        Авторежим берёт <b>все</b> сигналы бота — нужен малый риск (0.1-0.3%) чтобы выдержать просадку.
      </div>
    </div>` : '';

  window._ev = ev;
  window._wr = wr;
  window._cpdAll = cpdAll;
  window.maxLoseStreak = maxLoseStreak;
  window.maxDD = maxDD;
  window.updateProj = function() {
    const dep  = parseFloat(document.getElementById('projDeposit')?.value || 100);
    const risk = parseFloat(document.getElementById('projRisk')?.value || 1);
    const mode = document.getElementById('projMode')?.value || 'manual3';
    const ev_  = window._ev;
    const wr_  = window._wr;
    const tpdMap = { manual3: 3, manual5: 5, manual10: 10, auto: window._cpdAll || 10 };
    const tpd = tpdMap[mode] || 3;
    const n = tpd * 30;

    if (ev_ <= 0) {
      document.getElementById('projPct').textContent = '—';
      document.getElementById('projFin').textContent = '—';
      return;
    }

    const finalDep = dep * Math.pow(1 + (risk / 100) * ev_, n);
    const gain = finalDep - dep;
    const pct = Math.round(gain / dep * 1000) / 10;
    document.getElementById('projPct').textContent = (gain > 0 ? '+' : '') + pct + '%';
    document.getElementById('projFin').textContent = '$' + Math.round(finalDep);

    // Просадка
    const streak = maxLoseStreak(n, wr_);
    const dd = maxDD(streak, risk);
    document.getElementById('projStreak').textContent = streak;
    document.getElementById('projDD').textContent = '-' + dd + '%';

    // Цвет просадки
    const ddEl = document.getElementById('projDD');
    if (ddEl) ddEl.className = 'value ' + (dd > 30 ? 'red' : dd > 15 ? 'yellow' : 'green') + ' ';
    ddEl.style.fontSize = '1.6rem';
    const pctEl = document.getElementById('projPct');
    if (pctEl) { pctEl.className = 'value green'; pctEl.style.fontSize = '1.6rem'; }
  };

  const html = `
    <section>
      <h2>Сводка</h2>
      <div class="cards">
        <div class="card"><div class="label">Всего / Открыто</div>
          <div class="value blue">${s.total ?? '—'} <span style="font-size:1rem;color:#58a6ff88">/ ${s.open_count ?? 0}</span></div>
          ${s.days_active ? `<div class="label" style="margin-top:4px">${s.days_active} дней · ${cpdAll} сделок/день</div>` : ''}</div>
        <div class="card"><div class="label">Win Rate</div>
          <div class="value ${wr >= 0.5 ? 'green' : 'red'}">${s.win_rate != null ? s.win_rate + '%' : '—'}</div>
          <div class="label" style="margin-top:4px">
            <span class="green">TP ${s.tp_count ?? 0}</span> ·
            <span class="purple">TSL ${s.tsl_count ?? 0}</span> ·
            <span class="red">SL ${s.sl_count ?? 0}</span>
          </div></div>
        <div class="card" style="border-color:${evRound > 0 ? '#3fb950' : '#f85149'}44">
          <div class="label">EV / сделку <span style="color:#444;font-size:.7rem" title="Expected Value = WR×R_win + (1-WR)×R_loss">ожидаемый R</span></div>
          <div class="value ${evRound > 0 ? 'green' : 'red'}">${evRound > 0 ? '+' : ''}${evRound.toFixed(2)}R</div>
          <div class="label" style="margin-top:4px">${evRound > 0 ? '✅ Система прибыльна' : '❌ Система убыточна'}</div></div>
        <div class="card"><div class="label">Profit Factor</div>
          <div class="value ${pf >= 1.5 ? 'green' : pf >= 1 ? 'yellow' : 'red'}">${pf != null ? pf.toFixed(2) : '—'}</div>
          <div class="label" style="margin-top:4px">${pf >= 1.5 ? '🔥 Отличный' : pf >= 1.2 ? '👍 Хороший' : pf >= 1 ? '⚡ Слабый' : '❌ < 1'}</div></div>
        <div class="card"><div class="label">Avg R (Win ↑ / Loss ↓)</div>
          <div class="value" style="font-size:1.2rem">
            <span class="green">+${fmt(rWin,2)}</span>
            <span style="color:#444;font-weight:400"> / </span>
            <span class="red">${fmt(rLoss,2)}</span>
          </div>
          <div class="label" style="margin-top:4px">Avg Profit: <span class="${color(s.avg_profit_pct)}">${fmtPct(s.avg_profit_pct)}</span></div></div>
        ${projRow}
      </div>
    </section>

    <section>
      <h2>По стратегии</h2>
      ${tableByGroup(d.by_strategy, 'strategy_name')}
    </section>

    <section>
      <h2>По типу сигнала</h2>
      ${tableByGroup(d.by_signal_type, 'signal_type')}
    </section>

    <section>
      <h2>По направлению</h2>
      ${tableByGroup(d.by_direction, 'direction')}
    </section>

    ${confluenceBreakdown(cf)}

    <section>
      <h2>По режиму рынка</h2>
      ${regimeSection(d.by_regime)}
    </section>

    <section>
      <h2>Открытые позиции (${(d.open_trades||[]).length})</h2>
      ${openTradesTable(d.open_trades)}
    </section>

    <section>
      <h2>Последние закрытые сделки (${(d.recent_closed||[]).length})</h2>
      ${recentTable(d.recent_closed)}
    </section>
  `;
  document.getElementById('app').innerHTML = html;
  // Инициализировать прогноз после рендера DOM
  setTimeout(() => { if (window.updateProj) window.updateProj(); }, 0);
}

function tableByGroup(rows, labelKey) {
  if (!rows || !rows.length) return '<p class="note">Нет данных</p>';
  return `<table><thead><tr>
    <th>${labelKey}</th><th>Всего</th><th>Win Rate</th>
    <th class="green">TP</th><th class="purple">TSL</th><th class="red">SL</th>
    <th>Avg Profit%</th><th>Avg R</th>
  </tr></thead><tbody>` +
  rows.map(r => `<tr>
    <td>${r[labelKey] || '—'}</td>
    <td>${r.total}</td>
    <td class="${r.win_rate >= 50 ? 'green' : 'red'}">${r.win_rate != null ? r.win_rate + '%' : '—'}</td>
    <td class="green">${r.tp_count ?? r.wins ?? 0}</td>
    <td class="purple">${r.tsl_count ?? 0}</td>
    <td class="red">${r.sl_count ?? r.losses ?? 0}</td>
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

function tslBadge(activated) {
  if (activated) return '<span class="badge badge-tsl" title="TSL активен — следит за трендом">TSL ✓</span>';
  return '<span style="color:#444;font-size:.75rem" title="TSL ещё не активирован">—</span>';
}

function tp1Cell(tp1_price, tp1_hit_at, entry) {
  if (!tp1_price) return '<span style="color:#444">—</span>';
  const pct = entry ? ((tp1_price - entry) / Math.abs(entry) * 100).toFixed(1) : '';
  const pctStr = pct ? ` <span style="color:#8b949e;font-size:.73rem">(+${pct}%)</span>` : '';
  if (tp1_hit_at) {
    const t = tp1_hit_at.substring(11,16);
    return `<span class="green" title="TP1 достигнут в ${t}">✓${fmt(tp1_price,4)}</span>${pctStr}`;
  }
  return `<span style="color:#8b949e">${fmt(tp1_price,4)}</span>${pctStr}`;
}

function openTradesTable(rows) {
  if (!rows || !rows.length) return '<p class="note">Нет открытых позиций</p>';
  return `<table><thead><tr>
    <th>#</th><th>Символ</th><th>Dir</th><th>Сигнал</th>
    <th>Вход</th><th>Сейчас</th><th>P&L%</th><th>R</th>
    <th>SL</th><th>TP (финал)</th><th>TP1</th><th>TSL</th>
    <th>Открыта</th><th>Закрыть</th>
  </tr></thead><tbody>` +
  rows.map(r => {
    const pnl = r.unrealized_pct;
    const pnlClass = pnl == null ? '' : pnl >= 0 ? 'green' : 'red';
    const pnlStr = pnl != null ? (pnl >= 0 ? '+' : '') + pnl.toFixed(2) + '%' : '—';
    const rStr = r.unrealized_r != null ? (r.unrealized_r >= 0 ? '+' : '') + r.unrealized_r.toFixed(2) + 'R' : '—';
    const rClass = r.unrealized_r == null ? '' : r.unrealized_r >= 0 ? 'green' : 'red';
    const curStr = r.current_price != null ? fmt(r.current_price, 4) : '<span style="color:#666">—</span>';
    // Подсветить строку если TSL активен
    const rowStyle = r.tsl_activated ? ' style="background:rgba(184,126,255,0.05)"' : '';
    return `<tr${rowStyle}>
      <td>${r.id}</td>
      <td>${symLink(r.symbol)}</td>
      <td class="${r.direction==='LONG'?'green':'red'}">${r.direction}</td>
      <td>${r.signal_type||'—'}</td>
      <td>${fmt(r.entry_price,4)}</td>
      <td>${curStr}</td>
      <td class="${pnlClass}">${pnlStr}</td>
      <td class="${rClass}">${rStr}</td>
      <td class="red">${fmt(r.stop_loss,4)}</td>
      <td class="green">${fmt(r.take_profit,4)}</td>
      <td>${tp1Cell(r.tp1_price, r.tp1_hit_at, r.entry_price)}</td>
      <td>${tslBadge(r.tsl_activated)}</td>
      <td>${r.created_at ? r.created_at.substring(0,16) : '—'}</td>
      <td><button onclick="closeTrade(${r.id},this)" style="background:#b22222;color:#fff;border:none;padding:3px 8px;border-radius:4px;cursor:pointer;font-size:12px">✕ Close</button></td>
    </tr>`;
  }).join('') + '</tbody></table>';
}

async function closeTrade(id, btn) {
  if (!confirm(`Закрыть сделку #${id} по текущей цене?`)) return;
  btn.disabled = true; btn.textContent = '...';
  try {
    const r = await fetch(`/api/trades/${id}/close`, {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
    if (!r.ok) {
      const msg = await r.text().catch(() => `HTTP ${r.status}`);
      alert(msg || `Ошибка ${r.status}`);
      btn.textContent = 'Err'; btn.disabled = false;
      return;
    }
    const d = await r.json();
    if (d.ok) { btn.textContent = '✓'; btn.style.background='#2a6'; load(); }
    else { btn.textContent = 'Err'; btn.disabled = false; }
  } catch(e) { btn.textContent = 'Err'; btn.disabled = false; }
}

let _recentRows = [];

function recentTable(rows) {
  // Сохраняем текущие фильтры перед перезаписью данных
  const savedFilters = {
    st:  document.getElementById('fStatus')?.value  || '',
    dir: document.getElementById('fDir')?.value     || '',
    sig: document.getElementById('fSig')?.value     || '',
    reg: document.getElementById('fRegime')?.value  || '',
  };
  _recentRows = rows || [];
  if (!_recentRows.length) return '<p class="note">Нет закрытых сделок</p>';
  // Фильтры восстанавливаются через setTimeout после рендера DOM
  setTimeout(() => {
    ['fStatus','fDir','fSig','fRegime'].forEach((id, i) => {
      const v = Object.values(savedFilters)[i];
      const el = document.getElementById(id);
      if (el && v) el.value = v;
    });
    applyFilters();
  }, 0);

  // Уникальные значения для фильтров
  const statuses  = [...new Set(_recentRows.map(r => r.status).filter(Boolean))].sort();
  const dirs      = [...new Set(_recentRows.map(r => r.direction).filter(Boolean))].sort();
  const sigTypes  = [...new Set(_recentRows.map(r => r.signal_type).filter(Boolean))].sort();

  const mkOpts = (vals, all='Все') =>
    `<option value="">${all}</option>` + vals.map(v => `<option value="${v}">${v}</option>`).join('');

  return `
  <div class="filter-bar">
    <label>Статус:</label>
    <select id="fStatus" onchange="applyFilters()">${mkOpts(statuses)}</select>
    <label>Направление:</label>
    <select id="fDir" onchange="applyFilters()">${mkOpts(dirs)}</select>
    <label>Сигнал:</label>
    <select id="fSig" onchange="applyFilters()">${mkOpts(sigTypes)}</select>
    <label>Режим:</label>
    <select id="fRegime" onchange="applyFilters()">
      <option value="">Все</option>
      <option value="TREND_UP">TREND_UP</option>
      <option value="TREND_DOWN">TREND_DOWN</option>
      <option value="RANGE">RANGE</option>
      <option value="HIGH_VOL">HIGH_VOL</option>
    </select>
    <button onclick="resetFilters()">✕ Сброс</button>
  </div>
  <div id="recentTableWrap">${renderRecentRows(_recentRows)}</div>`;
}

function renderRecentRows(rows) {
  if (!rows.length) return '<p class="note">Нет сделок по фильтру</p>';
  return `<table><thead><tr>
    <th>#</th><th>Символ</th><th>Dir</th><th>Сигнал</th><th>Режим</th><th>Статус</th>
    <th>Profit%</th><th>R</th><th>Max R</th><th>Cap%</th>
    <th>TP src</th><th>Длит(мин)</th><th>Закрыта</th>
  </tr></thead><tbody>` +
  rows.map(r => {
    const capPct = r.captured_R_pct != null ? fmt(r.captured_R_pct,0)+'%' : '—';
    const capClass = r.captured_R_pct != null ? (r.captured_R_pct >= 60 ? 'green' : r.captured_R_pct >= 30 ? 'yellow' : 'red') : '';
    const tpSrc = (r.tp_source||'').replace('pivot_','').split(':')[0] || '—';
    return `<tr>
      <td>${r.id}</td>
      <td>${symLink(r.symbol)}</td>
      <td class="${r.direction==='LONG'?'green':'red'}">${r.direction||'—'}</td>
      <td>${r.signal_type||'—'}</td>
      <td style="color:#8b949e;font-size:.8rem">${r.regime||'—'}</td>
      <td>${badge(r.status)}</td>
      <td class="${color(r.profit_pct)}">${fmtPct(r.profit_pct)}</td>
      <td class="${color(r.R_multiple)}">${fmt(r.R_multiple,2)}</td>
      <td class="yellow">${r.max_R_possible != null ? fmt(r.max_R_possible,2) : '—'}</td>
      <td class="${capClass}">${capPct}</td>
      <td style="color:#8b949e;font-size:.8rem">${tpSrc}</td>
      <td>${r.duration_minutes != null ? Math.round(r.duration_minutes) : '—'}</td>
      <td>${r.closed_at ? r.closed_at.substring(0,16) : '—'}</td>
    </tr>`;
  }).join('') + '</tbody></table>';
}

function applyFilters() {
  const st  = document.getElementById('fStatus')?.value  || '';
  const dir = document.getElementById('fDir')?.value     || '';
  const sig = document.getElementById('fSig')?.value     || '';
  const reg = document.getElementById('fRegime')?.value  || '';
  const filtered = _recentRows.filter(r =>
    (!st  || r.status     === st)  &&
    (!dir || r.direction  === dir) &&
    (!sig || r.signal_type=== sig) &&
    (!reg || r.regime     === reg)
  );
  const wrap = document.getElementById('recentTableWrap');
  if (wrap) wrap.innerHTML = renderRecentRows(filtered);
}

function resetFilters() {
  ['fStatus','fDir','fSig','fRegime'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  applyFilters();
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
  .btn-reset { background: transparent; color: #8b949e; border: 1px solid #30363d;
               border-radius: 6px; padding: 9px 16px; font-size: .9rem; cursor: pointer;
               margin-top: 4px; margin-left: 8px; }
  .btn-reset:hover { background: #21262d; color: #c9d1d9; border-color: #8b949e; }
  #msg { padding: 10px 14px; border-radius: 6px; font-size: .88rem; margin-top: 12px;
         display: none; }
  .msg-ok   { background: #1a3a1f; color: #3fb950; border: 1px solid #2ea043; }
  .msg-err  { background: #3a1a1a; color: #f85149; border: 1px solid #f85149; }
  .msg-warn { background: #2d2200; color: #d29922; border: 1px solid #9e6a03; }
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
        <span class="hint">× среднего объёма за 20 свечей &nbsp;<b>default: 5.0</b></span>
      </div>
      <div class="field">
        <label>Порог изменения цены, %</label>
        <input type="number" id="price_threshold" name="price_threshold"
               min="0.5" max="50" step="0.5">
        <span class="hint">минимальное движение цены для сигнала &nbsp;<b>default: 7.0</b></span>
      </div>
      <div class="field">
        <label>Интервал проверки, сек</label>
        <input type="number" id="check_interval" name="check_interval"
               min="10" max="3600" step="10">
        <span class="hint">пауза между циклами мониторинга &nbsp;<b>default: 60</b></span>
      </div>
      <div class="field">
        <label>Размер истории (свечей)</label>
        <input type="number" id="history_size" name="history_size"
               min="50" max="1000" step="50">
        <span class="hint">глубина OHLCV для индикаторов &nbsp;<b>default: 200</b></span>
      </div>
      <button type="submit" class="btn" id="saveBtn">&#x1F4BE; Сохранить и применить</button>
      <button type="button" class="btn-reset" onclick="resetForm('analysis')">&#x21BA; Сбросить</button>
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
        <span class="hint">период EMA для HLC3 (9-12) &nbsp;<b>default: 10</b></span>
      </div>
      <div class="field">
        <label>Signal period (n2)</label>
        <input type="number" id="wt_n2" min="10" max="50" step="1">
        <span class="hint">период сигнальной линии (20-25) &nbsp;<b>default: 21</b></span>
      </div>
      <div class="field">
        <label>Overbought (OB)</label>
        <input type="number" id="wt_ob" min="30" max="100" step="1">
        <span class="hint">перекупленность (53-60) &nbsp;<b>default: 58</b></span>
      </div>
      <div class="field">
        <label>Oversold (OS)</label>
        <input type="number" id="wt_os" min="-100" max="-30" step="1">
        <span class="hint">перепроданность (-53 до -60) &nbsp;<b>default: -58</b></span>
      </div>
      <p style="font-size:.8rem;color:#8b949e;margin:14px 0 10px;">Trend / TSL</p>
      <div class="field">
        <label>ATR period</label>
        <input type="number" id="trend_atr" min="5" max="200" step="1">
        <span class="hint">период ATR для TSL-тренда &nbsp;<b>default: 43</b></span>
      </div>
      <div class="field">
        <label>ATR factor</label>
        <input type="number" id="trend_factor" min="0.1" max="5" step="0.1">
        <span class="hint">множитель ATR (0.8–1.2) &nbsp;<b>default: 1.0</b></span>
      </div>
      <button type="submit" class="btn" id="saveIndBtn">&#x1F4BE; Сохранить индикаторы</button>
      <button type="button" class="btn-reset" onclick="resetForm('indicators')">&#x21BA; Сбросить</button>
      <div id="msgInd"></div>
    </form>
  </section>

  <section>
    <h2>&#x1F6E1;&#xFE0F; Качество сигналов</h2>
    <form id="qualityForm">
      <div class="field">
        <label>Пауза после SL (часы)</label>
        <input type="number" id="sl_cooldown_hours" min="1" max="48" step="1">
        <span class="hint">не мониторить пару N часов после SL &nbsp;<b>default: 4</b></span>
      </div>
      <div class="field">
        <label>Дедупликация сигналов (мин)</label>
        <input type="number" id="dedup_minutes" min="5" max="120" step="5">
        <span class="hint">подавлять повторные одинаковые сигналы &nbsp;<b>default: 30</b></span>
      </div>
      <div class="field">
        <label>Мин. объём пары (USD)</label>
        <input type="number" id="min_volume_usd" min="100000" max="100000000" step="100000">
        <span class="hint">пары ниже порога не мониторируются &nbsp;<b>default: 1 000 000</b></span>
      </div>
      <div class="field">
        <label>Мин. сила для TG-алерта</label>
        <input type="number" id="min_strength" min="20" max="100" step="1">
        <span class="hint">слабее — не отправляется в Telegram &nbsp;<b>default: 50</b></span>
      </div>
      <div class="field">
        <label>Мин. сила для симулятора</label>
        <input type="number" id="min_strength_register" min="10" max="100" step="1">
        <span class="hint">слабее — не пишется в БД (↓ = больше обучающих данных) &nbsp;<b>default: 40</b></span>
      </div>
      <button type="submit" class="btn" id="saveQualityBtn">&#x1F4BE; Сохранить качество</button>
      <button type="button" class="btn-reset" onclick="resetForm('quality')">&#x21BA; Сбросить</button>
      <div id="msgQuality"></div>
    </form>
  </section>

  <section>
    <h2>&#x1F4C9; TSL — Trailing Stop Loss</h2>
    <form id="tradingForm">
      <div class="field">
        <label>Использовать TSL</label>
        <input type="checkbox" id="use_tsl" style="width:18px;height:18px;cursor:pointer;">
        <span class="hint">следует за трендом, защищает прибыль &nbsp;<b>default: ✓ вкл</b></span>
      </div>
      <div class="field">
        <label>Активировать TSL после (R)</label>
        <input type="number" id="tsl_activation_r" min="0.1" max="5" step="0.1">
        <span class="hint">включается когда сделка достигла +N×R &nbsp;<b>default: 1.0</b></span>
      </div>
      <div class="field">
        <label>Буфер TSL (%)</label>
        <input type="number" id="tsl_buffer_pct" min="0" max="1" step="0.05">
        <span class="hint">дополнительный зазор от линии TSL &nbsp;<b>default: 0.1</b></span>
      </div>
      <button type="submit" class="btn" id="saveTradingBtn">&#x1F4BE; Сохранить TSL</button>
      <button type="button" class="btn-reset" onclick="resetForm('trading')">&#x21BA; Сбросить</button>
      <div id="msgTrading"></div>
    </form>
  </section>

  <section>
    <h2>&#x1F50D; Детектор аномалий объёма</h2>
    <form id="detectorsForm">
      <div class="field">
        <label>Порог volume ratio</label>
        <input type="number" id="volume_ratio_threshold" min="1.0" max="20.0" step="0.1">
        <span class="hint">объём / среднее за MA-период (ниже = больше сигналов) &nbsp;<b>default: 3.0</b></span>
      </div>
      <div class="field">
        <label>Период MA объёма (свечей)</label>
        <input type="number" id="volume_ma_period" min="5" max="100" step="1">
        <span class="hint">период скользящей средней объёма &nbsp;<b>default: 20</b></span>
      </div>
      <div class="field">
        <label>Мин. баров для расчёта</label>
        <input type="number" id="anom_min_bars" min="5" max="200" step="1">
        <span class="hint">минимум исторических свечей &nbsp;<b>default: 20</b></span>
      </div>
      <div class="field">
        <label>Множитель strength (по тренду)</label>
        <input type="number" id="strength_trend_multiplier" min="1" max="30" step="1">
        <span class="hint">ratio × N = сила сигнала по тренду &nbsp;<b>default: 12</b></span>
      </div>
      <div class="field">
        <label>Множитель strength (против тренда)</label>
        <input type="number" id="strength_counter_multiplier" min="1" max="30" step="1">
        <span class="hint">ratio × N = сила контртрендового сигнала &nbsp;<b>default: 8</b></span>
      </div>
      <button type="submit" class="btn" id="saveDetectorsBtn">&#x1F4BE; Сохранить детекторы</button>
      <button type="button" class="btn-reset" onclick="resetForm('detectors')">&#x21BA; Сбросить</button>
      <div id="msgDetectors"></div>
    </form>
  </section>

  <section>
    <h2>&#x1F4CB; Фильтры сигналов</h2>
    <form id="signalsConfigForm">
      <div class="field">
        <label>Мин. сигналов для рекомендации</label>
        <input type="number" id="min_signals" min="1" max="10" step="1">
        <span class="hint">не-топ пары: нужно минимум N сигналов &nbsp;<b>default: 2</b></span>
      </div>
      <div class="field">
        <label>Порог bypass (1 сигнал), strength</label>
        <input type="number" id="single_signal_min_strength" min="30" max="100" step="1">
        <span class="hint">1 сигнал с силой ≥ N пропускает min_signals &nbsp;<b>default: 70</b></span>
      </div>
      <div class="field">
        <label>Близость к пивоту, % (дивергенции)</label>
        <input type="number" id="pivot_proximity_pct" min="0.5" max="20.0" step="0.5">
        <span class="hint">допустимое расстояние до уровня (ниже = строже) &nbsp;<b>default: 4.0</b></span>
      </div>
      <div class="field">
        <label>BTC фильтр включён</label>
        <input type="checkbox" id="btc_filter_enabled" style="width:18px;height:18px;cursor:pointer;">
        <span class="hint">снять — отключить BTC-корреляционный фильтр (предупреждения и блокировки) &nbsp;<b>default: ✓</b></span>
      </div>
      <div class="field">
        <label>Контртренд порог (BTC фильтр)</label>
        <input type="number" id="counter_trend_strength_threshold" min="30" max="100" step="1">
        <span class="hint">сила < N при контртренде BTC → пропустить &nbsp;<b>default: 70</b></span>
      </div>
      <button type="submit" class="btn" id="saveSignalsConfigBtn">&#x1F4BE; Сохранить фильтры</button>
      <button type="button" class="btn-reset" onclick="resetForm('signals_config')">&#x21BA; Сбросить</button>
      <div id="msgSignalsConfig"></div>
    </form>
  </section>

  <section>
    <h2>&#x23F1;&#xFE0F; Интервалы мониторинга</h2>
    <form id="monitoringForm">
      <div class="field">
        <label>Дивергенции (каждые N циклов)</label>
        <input type="number" id="divergences_every_n_cycles" min="1" max="20" step="1">
        <span class="hint">N × check_interval сек между проверками дивергенций &nbsp;<b>default: 3</b></span>
      </div>
      <div class="field">
        <label>Фоновые проверки (каждые N циклов)</label>
        <input type="number" id="background_every_n_cycles" min="1" max="30" step="1">
        <span class="hint">MTF alerts, тренд, пивоты — каждые N×check_interval сек &nbsp;<b>default: 5</b></span>
      </div>
      <div class="field">
        <label>Каскадные дивергенции 4h→1h (циклы)</label>
        <input type="number" id="cascade_div_every_n_cycles" min="10" max="300" step="10">
        <span class="hint">обновляется редко (4h свеча) &nbsp;<b>default: 60</b></span>
      </div>
      <button type="submit" class="btn" id="saveMonitoringBtn">&#x1F4BE; Сохранить интервалы</button>
      <button type="button" class="btn-reset" onclick="resetForm('monitoring')">&#x21BA; Сбросить</button>
      <div id="msgMonitoring"></div>
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

  <section>
    <h2>&#x1F517; Confluence Scanner</h2>
    <form id="confluenceForm">
      <div class="field">
        <label style="display:flex;align-items:center;gap:8px;">
          <input type="checkbox" id="confluence_enabled" style="accent-color:#58a6ff;width:16px;height:16px;">
          Включён
        </label>
        <span class="hint">выключить без перезапуска бота &nbsp;<b>default: вкл</b></span>
      </div>
      <p style="font-size:.8rem;color:#8b949e;margin:14px 0 10px;">Окно поиска</p>
      <div class="field">
        <label>Lookback (баров 15m)</label>
        <input type="number" id="confluence_lookback" min="5" max="200" step="1">
        <span class="hint">глубина поиска (~7.5 ч при 30 барах) &nbsp;<b>default: 40</b></span>
      </div>
      <div class="field">
        <label>Мин. score (порог сигнала)</label>
        <input type="number" id="confluence_min_strength" min="40" max="100" step="5">
        <span class="hint">60 = минимум 3 из 5 факторов должны совпасть &nbsp;<b>default: 60</b></span>
      </div>
      <p style="font-size:.8rem;color:#8b949e;margin:14px 0 10px;">WaveTrend зоны</p>
      <div class="field">
        <label>WT OS порог (Long)</label>
        <input type="number" id="confluence_wt_os" min="-100" max="-20" step="1">
        <span class="hint">WT ниже порога = перепроданность → фактор LONG &nbsp;<b>default: -58</b></span>
      </div>
      <div class="field">
        <label>WT OB порог (Short)</label>
        <input type="number" id="confluence_wt_ob" min="20" max="100" step="1">
        <span class="hint">WT выше порога = перекупленность → фактор SHORT &nbsp;<b>default: 58</b></span>
      </div>
      <p style="font-size:.8rem;color:#8b949e;margin:14px 0 10px;">Пивоты и дивергенции</p>
      <div class="field">
        <label>Близость к пивоту (%)</label>
        <input type="number" id="confluence_pivot_pct" min="0.1" max="5.0" step="0.1">
        <span class="hint">цена считается "у пивота" если ближе чем N% &nbsp;<b>default: 0.5</b></span>
      </div>
      <div class="field">
        <label>Мин. баров между трогами</label>
        <input type="number" id="confluence_div_bars" min="1" max="20" step="1">
        <span class="hint">минимальное расстояние для дивергенции WT &nbsp;<b>default: 3</b></span>
      </div>
      <button type="submit" class="btn" id="saveConfluenceBtn">&#x1F4BE; Сохранить Confluence</button>
      <button type="button" class="btn-reset" onclick="resetForm('confluence')">&#x21BA; Сбросить</button>
      <div id="msgConfluence"></div>
    </form>
  </section>

</main>
<script>
// Значения по умолчанию — "защита от дурака"
const DEFAULTS = {
  analysis: {
    volume_multiplier: 5.0,
    price_threshold: 7.0,
    check_interval: 60,
    history_size: 200,
  },
  confluence: {
    enabled: true,
    lookback_bars: 40,
    min_strength: 60,
    wt_os_threshold: -58,
    wt_ob_threshold: 58,
    pivot_proximity_pct: 0.5,
    div_min_bars: 3,
  },
  indicators: {
    wt_n1: 10, wt_n2: 21, wt_ob: 58, wt_os: -58,
    trend_atr: 43, trend_factor: 1.0,
  },
  quality: {
    sl_cooldown_hours: 4,
    dedup_minutes: 30,
    min_volume_usd: 1000000,
    min_strength: 50,
    min_strength_register: 20,
    counter_trend_strength_threshold: 70,
  },
  trading: {
    use_tsl: true,
    tsl_activation_r: 1.0,
    tsl_buffer_pct: 0.1,
  },
  detectors: {
    volume_ratio_threshold: 3.0,
    volume_ma_period: 20,
    anom_min_bars: 20,
    strength_trend_multiplier: 12,
    strength_counter_multiplier: 8,
  },
  signals_config: {
    min_signals: 2,
    single_signal_min_strength: 70,
    pivot_proximity_pct: 4.0,
    btc_filter_enabled: true,
    counter_trend_strength_threshold: 70,
  },
  monitoring: {
    divergences_every_n_cycles: 3,
    background_every_n_cycles: 5,
    cascade_div_every_n_cycles: 60,
  },
};

function resetForm(section) {
  const d = DEFAULTS[section];
  if (!d) return;
  const msgMap = {
    analysis:'msg', indicators:'msgInd', quality:'msgQuality', trading:'msgTrading',
    detectors:'msgDetectors', signals_config:'msgSignalsConfig', monitoring:'msgMonitoring',
  };
  const msgEl = document.getElementById(msgMap[section]);

  if (section === 'analysis') {
    document.getElementById('volume_multiplier').value = d.volume_multiplier;
    document.getElementById('price_threshold').value   = d.price_threshold;
    document.getElementById('check_interval').value    = d.check_interval;
    document.getElementById('history_size').value      = d.history_size;
  } else if (section === 'indicators') {
    document.getElementById('wt_n1').value        = d.wt_n1;
    document.getElementById('wt_n2').value        = d.wt_n2;
    document.getElementById('wt_ob').value        = d.wt_ob;
    document.getElementById('wt_os').value        = d.wt_os;
    document.getElementById('trend_atr').value    = d.trend_atr;
    document.getElementById('trend_factor').value = d.trend_factor;
  } else if (section === 'quality') {
    document.getElementById('sl_cooldown_hours').value              = d.sl_cooldown_hours;
    document.getElementById('dedup_minutes').value                  = d.dedup_minutes;
    document.getElementById('min_volume_usd').value                 = d.min_volume_usd;
    document.getElementById('min_strength').value                   = d.min_strength;
    document.getElementById('min_strength_register').value          = d.min_strength_register;
  } else if (section === 'trading') {
    document.getElementById('use_tsl').checked        = d.use_tsl;
    document.getElementById('tsl_activation_r').value = d.tsl_activation_r;
    document.getElementById('tsl_buffer_pct').value   = d.tsl_buffer_pct;
  } else if (section === 'detectors') {
    document.getElementById('volume_ratio_threshold').value    = d.volume_ratio_threshold;
    document.getElementById('volume_ma_period').value          = d.volume_ma_period;
    document.getElementById('anom_min_bars').value             = d.anom_min_bars;
    document.getElementById('strength_trend_multiplier').value = d.strength_trend_multiplier;
    document.getElementById('strength_counter_multiplier').value = d.strength_counter_multiplier;
  } else if (section === 'signals_config') {
    document.getElementById('min_signals').value                      = d.min_signals;
    document.getElementById('single_signal_min_strength').value       = d.single_signal_min_strength;
    document.getElementById('pivot_proximity_pct').value              = d.pivot_proximity_pct;
    document.getElementById('btc_filter_enabled').checked             = d.btc_filter_enabled !== false;
    document.getElementById('counter_trend_strength_threshold').value = d.counter_trend_strength_threshold;
  } else if (section === 'monitoring') {
    document.getElementById('divergences_every_n_cycles').value = d.divergences_every_n_cycles;
    document.getElementById('background_every_n_cycles').value  = d.background_every_n_cycles;
    document.getElementById('cascade_div_every_n_cycles').value = d.cascade_div_every_n_cycles;
  } else if (section === 'confluence') {
    document.getElementById('confluence_enabled').checked        = d.enabled !== false;
    document.getElementById('confluence_lookback').value         = d.lookback_bars;
    document.getElementById('confluence_min_strength').value     = d.min_strength;
    document.getElementById('confluence_wt_os').value            = d.wt_os_threshold;
    document.getElementById('confluence_wt_ob').value            = d.wt_ob_threshold;
    document.getElementById('confluence_pivot_pct').value        = d.pivot_proximity_pct;
    document.getElementById('confluence_div_bars').value         = d.div_min_bars;
  }

  if (msgEl) {
    msgEl.style.display = 'block';
    msgEl.className = 'msg-warn';
    msgEl.textContent = 'Значения сброшены на defaults. Нажмите «Сохранить» для применения.';
  }
}

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

    const sq = d.signal_quality || {};
    document.getElementById('sl_cooldown_hours').value      = sq.sl_cooldown_hours     ?? 4;
    document.getElementById('dedup_minutes').value          = sq.dedup_minutes          ?? 30;
    document.getElementById('min_volume_usd').value         = sq.min_volume_usd         ?? 1000000;
    document.getElementById('min_strength').value           = sq.min_strength           ?? 50;
    document.getElementById('min_strength_register').value  = sq.min_strength_register  ?? 20;

    const det = (d.detectors || {}).anomaly || {};
    document.getElementById('volume_ratio_threshold').value    = det.volume_ratio_threshold    ?? 3.0;
    document.getElementById('volume_ma_period').value          = det.volume_ma_period          ?? 20;
    document.getElementById('anom_min_bars').value             = det.min_bars                  ?? 20;
    document.getElementById('strength_trend_multiplier').value = det.strength_trend_multiplier  ?? 12;
    document.getElementById('strength_counter_multiplier').value = det.strength_counter_multiplier ?? 8;

    const sc = d.signals_config || {};
    document.getElementById('min_signals').value                      = sc.min_signals              ?? 2;
    document.getElementById('single_signal_min_strength').value       = sc.single_signal_min_strength ?? 70;
    document.getElementById('pivot_proximity_pct').value              = sc.pivot_proximity_pct      ?? 4.0;
    document.getElementById('btc_filter_enabled').checked             = sc.btc_filter_enabled !== false;
    document.getElementById('counter_trend_strength_threshold').value = sc.counter_trend_strength_threshold ?? 70;

    const mon = d.monitoring_intervals || {};
    document.getElementById('divergences_every_n_cycles').value = mon.divergences_every_n_cycles ?? 3;
    document.getElementById('background_every_n_cycles').value  = mon.background_every_n_cycles  ?? 5;
    document.getElementById('cascade_div_every_n_cycles').value = mon.cascade_div_every_n_cycles ?? 60;

    const confl = d.confluence || {};
    document.getElementById('confluence_enabled').checked        = confl.enabled !== false;
    document.getElementById('confluence_lookback').value         = confl.lookback_bars        ?? 40;
    document.getElementById('confluence_min_strength').value     = confl.min_strength         ?? 60;
    document.getElementById('confluence_wt_os').value            = confl.wt_os_threshold      ?? -58;
    document.getElementById('confluence_wt_ob').value            = confl.wt_ob_threshold      ?? 58;
    document.getElementById('confluence_pivot_pct').value        = confl.pivot_proximity_pct  ?? 0.5;
    document.getElementById('confluence_div_bars').value         = confl.div_min_bars         ?? 3;

    const trd = d.trading || {};
    document.getElementById('use_tsl').checked         = trd.use_tsl !== false;
    document.getElementById('tsl_activation_r').value  = trd.tsl_activation_r ?? 1.0;
    document.getElementById('tsl_buffer_pct').value    = trd.tsl_buffer_pct   ?? 0.1;

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

document.getElementById('qualityForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  await postSettings({signal_quality: {
    sl_cooldown_hours:    parseInt(document.getElementById('sl_cooldown_hours').value),
    dedup_minutes:        parseInt(document.getElementById('dedup_minutes').value),
    min_volume_usd:       parseInt(document.getElementById('min_volume_usd').value),
    min_strength:         parseInt(document.getElementById('min_strength').value),
    min_strength_register:parseInt(document.getElementById('min_strength_register').value),
  }}, 'saveQualityBtn', 'msgQuality', '&#x1F4BE; Сохранить качество');
});

document.getElementById('tradingForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  await postSettings({trading: {
    use_tsl:          document.getElementById('use_tsl').checked,
    tsl_activation_r: parseFloat(document.getElementById('tsl_activation_r').value),
    tsl_buffer_pct:   parseFloat(document.getElementById('tsl_buffer_pct').value),
  }}, 'saveTradingBtn', 'msgTrading', '&#x1F4BE; Сохранить TSL');
});

document.getElementById('detectorsForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  await postSettings({detectors: {
    volume_ratio_threshold:      parseFloat(document.getElementById('volume_ratio_threshold').value),
    volume_ma_period:            parseInt(document.getElementById('volume_ma_period').value),
    min_bars:                    parseInt(document.getElementById('anom_min_bars').value),
    strength_trend_multiplier:   parseInt(document.getElementById('strength_trend_multiplier').value),
    strength_counter_multiplier: parseInt(document.getElementById('strength_counter_multiplier').value),
  }}, 'saveDetectorsBtn', 'msgDetectors', '&#x1F4BE; Сохранить детекторы');
});

document.getElementById('signalsConfigForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  await postSettings({signals_config: {
    min_signals:                parseInt(document.getElementById('min_signals').value),
    single_signal_min_strength: parseInt(document.getElementById('single_signal_min_strength').value),
    pivot_proximity_pct:        parseFloat(document.getElementById('pivot_proximity_pct').value),
    btc_filter_enabled:         document.getElementById('btc_filter_enabled').checked,
    counter_trend_strength_threshold: parseInt(document.getElementById('counter_trend_strength_threshold').value),
  }}, 'saveSignalsConfigBtn', 'msgSignalsConfig', '&#x1F4BE; Сохранить фильтры');
});

document.getElementById('monitoringForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  await postSettings({monitoring_intervals: {
    divergences_every_n_cycles: parseInt(document.getElementById('divergences_every_n_cycles').value),
    background_every_n_cycles:  parseInt(document.getElementById('background_every_n_cycles').value),
    cascade_div_every_n_cycles: parseInt(document.getElementById('cascade_div_every_n_cycles').value),
  }}, 'saveMonitoringBtn', 'msgMonitoring', '&#x1F4BE; Сохранить интервалы');
});

document.getElementById('confluenceForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  await postSettings({confluence: {
    enabled:              document.getElementById('confluence_enabled').checked,
    lookback_bars:        parseInt(document.getElementById('confluence_lookback').value),
    min_strength:         parseInt(document.getElementById('confluence_min_strength').value),
    wt_os_threshold:      parseFloat(document.getElementById('confluence_wt_os').value),
    pivot_proximity_pct:  parseFloat(document.getElementById('confluence_pivot_pct').value),
    div_min_bars:         parseInt(document.getElementById('confluence_div_bars').value),
    wt_ob_threshold:      parseFloat(document.getElementById('confluence_wt_ob').value),
  }}, 'saveConfluenceBtn', 'msgConfluence', '&#x1F4BE; Сохранить Confluence');
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


async def _handle_confluence_breakdown(request: web.Request) -> web.Response:
    engine: PerformanceEngine = request.app["engine"]
    try:
        data = engine.confluence_breakdown()
        return web.Response(
            text=json.dumps(data, ensure_ascii=False, default=str),
            content_type="application/json",
            charset="utf-8",
        )
    except Exception as e:
        return web.Response(text=json.dumps({"error": str(e)}), content_type="application/json", status=500)


def _current_price_from_cache(dc, symbol: str) -> float | None:
    """Берёт последнюю цену закрытия из кеша OHLCV (без API-запроса)."""
    try:
        cache = getattr(dc, "_ohlcv_cache", {})
        for tf in ("15m", "1m", "5m", "1h"):
            entry = cache.get((symbol, tf))
            if entry and "df" in entry and not entry["df"].empty:
                return float(entry["df"]["close"].iloc[-1])
    except Exception:
        pass
    return None


async def _handle_stats(request: web.Request) -> web.Response:
    engine: PerformanceEngine = request.app["engine"]
    dc = request.app.get("data_collector")
    try:
        data = engine.full_stats()
        # Обогащаем open_trades текущей ценой и нереализованным P&L
        for t in data.get("open_trades", []):
            cur = _current_price_from_cache(dc, t["symbol"]) if dc else None
            t["current_price"] = cur
            if cur is not None and t.get("entry_price") and t.get("stop_loss") and t.get("take_profit"):
                ep = t["entry_price"]
                sl = t["stop_loss"]
                tp = t["take_profit"]
                direction = t.get("direction", "LONG")
                if direction == "LONG":
                    pnl_pct = (cur - ep) / ep * 100
                    sl_dist = ep - sl
                else:
                    pnl_pct = (ep - cur) / ep * 100
                    sl_dist = sl - ep
                t["unrealized_pct"] = round(pnl_pct, 2)
                t["unrealized_r"] = round(pnl_pct / (abs(sl_dist) / ep * 100), 2) if sl_dist else None
            else:
                t["unrealized_pct"] = None
                t["unrealized_r"] = None
        return web.Response(
            text=json.dumps(data, ensure_ascii=False, default=str),
            content_type="application/json",
            charset="utf-8",
        )
    except Exception as e:
        logger.exception("dashboard /api/stats error: %s", e)
        return web.Response(status=500, text=str(e))


async def _handle_close_trade(request: web.Request) -> web.Response:
    """POST /api/trades/{trade_id}/close — ручное закрытие сделки."""
    ts = request.app.get("trade_simulator")
    dc = request.app.get("data_collector")
    if ts is None:
        return web.Response(status=503, text="TradeSimulator недоступен")
    try:
        trade_id = int(request.match_info["trade_id"])
        # Получаем текущую цену из кеша или из тела запроса
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        # Читаем символ из БД
        import sqlite3
        with sqlite3.connect(ts.db_path) as conn:
            row = conn.execute(
                "SELECT symbol, entry_price FROM simulated_trades WHERE id=? AND status='OPEN'",
                (trade_id,)
            ).fetchone()
        if not row:
            return web.Response(status=404, text="Сделка не найдена или уже закрыта")
        symbol, entry_price = row
        # Текущая цена: из кеша → из тела запроса → entry_price (нейтрально)
        cur_price = (_current_price_from_cache(dc, symbol) if dc else None) \
                    or body.get("price") or entry_price
        ok = ts.close_trade(trade_id, "EXPIRED", float(cur_price))
        if ok:
            logger.info("Dashboard: ручное закрытие сделки #%d %s @ %.5f", trade_id, symbol, cur_price)
            return web.Response(
                text=json.dumps({"ok": True, "trade_id": trade_id, "price": cur_price}, ensure_ascii=False),
                content_type="application/json",
            )
        return web.Response(status=500, text="Не удалось закрыть сделку")
    except Exception as e:
        logger.exception("_handle_close_trade: %s", e)
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

    safe_trading = {
        "use_tsl":          cfg.get("trading.use_tsl", True),
        "tsl_activation_r": cfg.get("trading.tsl_activation_r", 1.0),
        "tsl_buffer_pct":   cfg.get("trading.tsl_buffer_pct", 0.1),
    }
    safe_signal_quality = {
        "sl_cooldown_hours":    cfg.get("signal_quality.sl_cooldown_hours", 4),
        "dedup_minutes":        cfg.get("signal_quality.dedup_minutes", 30),
        "min_volume_usd":       cfg.get("signal_quality.min_volume_usd", 1_000_000),
        "min_strength":         cfg.get("signal_quality.min_strength", 50),
        "min_strength_register":cfg.get("signal_quality.min_strength_register", 20),
        "counter_trend_strength_threshold": cfg.get("signal_quality.counter_trend_strength_threshold", 70),
    }

    det_cfg = cfg.get("detectors", {}).get("anomaly", {}) or {}
    safe_detectors = {
        "anomaly": {
            "volume_ratio_threshold":      det_cfg.get("volume_ratio_threshold", 3.0),
            "volume_ma_period":            det_cfg.get("volume_ma_period", 20),
            "min_bars":                    det_cfg.get("min_bars", 20),
            "strength_trend_multiplier":   det_cfg.get("strength_trend_multiplier", 12),
            "strength_counter_multiplier": det_cfg.get("strength_counter_multiplier", 8),
        }
    }

    mon_cfg = cfg.get("monitoring", {}).get("check_intervals", {}) or {}
    safe_monitoring = {
        "divergences_every_n_cycles": mon_cfg.get("divergences_every_n_cycles", 3),
        "background_every_n_cycles":  mon_cfg.get("background_every_n_cycles", 5),
        "cascade_div_every_n_cycles": mon_cfg.get("cascade_div_every_n_cycles", 60),
    }

    sig_cfg = analysis.get("signals", {}) or {}
    safe_signals_config = {
        "min_signals":              sig_cfg.get("min_signals", 2),
        "single_signal_min_strength": sig_cfg.get("single_signal_min_strength", 70),
        "pivot_proximity_pct":      cfg.get("analysis.divergence.pivot_proximity_pct", 4.0),
        "btc_filter_enabled":       cfg.get("signal_quality.btc_filter_enabled", True),
        "counter_trend_strength_threshold": cfg.get("signal_quality.counter_trend_strength_threshold", 70),
    }

    confl_cfg = analysis.get("confluence", {}) or {}
    safe_confluence = {
        "enabled":              confl_cfg.get("enabled", True),
        "lookback_bars":        confl_cfg.get("lookback_bars", 40),
        "min_strength":         confl_cfg.get("min_strength", 60),
        "wt_os_threshold":      confl_cfg.get("wt_os_threshold", -58),
        "wt_ob_threshold":      confl_cfg.get("wt_ob_threshold", 58),
        "pivot_proximity_pct":  confl_cfg.get("pivot_proximity_pct", 0.5),
        "div_min_bars":         confl_cfg.get("div_min_bars", 3),
    }

    data = {
        "analysis": safe_analysis,
        "indicators": safe_indicators,
        "signal_weights": signal_weights,
        "trading": safe_trading,
        "signal_quality": safe_signal_quality,
        "detectors": safe_detectors,
        "monitoring_intervals": safe_monitoring,
        "signals_config": safe_signals_config,
        "confluence": safe_confluence,
    }
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

    # --- Блок trading (TSL) ---
    trading_body = body.get("trading")
    if trading_body is not None:
        try:
            use_tsl   = bool(trading_body.get("use_tsl", True))
            act_r     = float(trading_body.get("tsl_activation_r", 1.0))
            buf       = float(trading_body.get("tsl_buffer_pct", 0.1))
            errors: list = []
            if not (0.1 <= act_r <= 5.0): errors.append("tsl_activation_r: 0.1–5.0")
            if not (0.0 <= buf <= 1.0):   errors.append("tsl_buffer_pct: 0.0–1.0")
        except (TypeError, ValueError) as e:
            errors = [f"Некорректный тип данных: {e}"]
        if errors:
            return web.Response(
                text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
                content_type="application/json", charset="utf-8",
            )
        ok = cfg.save_trading(use_tsl=use_tsl, tsl_activation_r=act_r, tsl_buffer_pct=buf)
        return web.Response(
            text=json.dumps({"ok": ok, "error": None if ok else "ошибка записи файла"}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )

    # --- Блок signal_quality ---
    sq_body = body.get("signal_quality")
    if sq_body is not None:
        try:
            sl_h  = int(sq_body.get("sl_cooldown_hours", 4))
            ded   = int(sq_body.get("dedup_minutes", 30))
            vol   = int(sq_body.get("min_volume_usd", 1_000_000))
            ms    = int(sq_body.get("min_strength", 50))
            msr   = int(sq_body.get("min_strength_register", 20))
            errors = []
            if not (1 <= sl_h <= 48):         errors.append("sl_cooldown_hours: 1–48")
            if not (5 <= ded <= 120):          errors.append("dedup_minutes: 5–120")
            if not (100_000 <= vol <= 100_000_000): errors.append("min_volume_usd: 100К–100М")
            if not (20 <= ms <= 100):          errors.append("min_strength: 20–100")
            if not (10 <= msr <= ms):          errors.append(f"min_strength_register: 10–{ms}")
        except (TypeError, ValueError) as e:
            errors = [f"Некорректный тип данных: {e}"]
        if errors:
            return web.Response(
                text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
                content_type="application/json", charset="utf-8",
            )
        ok = cfg.save_signal_quality(
            sl_cooldown_hours=sl_h, dedup_minutes=ded, min_volume_usd=vol,
            min_strength=ms, min_strength_register=msr,
        )
        return web.Response(
            text=json.dumps({"ok": ok, "error": None if ok else "ошибка записи файла"}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )

    # --- Блок detectors ---
    det_body = body.get("detectors")
    if det_body is not None:
        try:
            ratio_thr  = float(det_body.get("volume_ratio_threshold", 3.0))
            ma_period  = int(det_body.get("volume_ma_period", 20))
            min_bars   = int(det_body.get("min_bars", 20))
            str_trend  = int(det_body.get("strength_trend_multiplier", 12))
            str_ctr    = int(det_body.get("strength_counter_multiplier", 8))
            errors = []
            if not (1.0 <= ratio_thr <= 20.0): errors.append("volume_ratio_threshold: 1.0–20.0")
            if not (5 <= ma_period <= 100):     errors.append("volume_ma_period: 5–100")
            if not (5 <= min_bars <= 200):      errors.append("min_bars: 5–200")
            if not (1 <= str_trend <= 30):      errors.append("strength_trend_multiplier: 1–30")
            if not (1 <= str_ctr <= 30):        errors.append("strength_counter_multiplier: 1–30")
        except (TypeError, ValueError) as e:
            errors = [f"Некорректный тип данных: {e}"]
        if errors:
            return web.Response(
                text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
                content_type="application/json", charset="utf-8",
            )
        ok = cfg.save_detectors(
            volume_ratio_threshold=ratio_thr, volume_ma_period=ma_period,
            min_bars=min_bars, strength_trend_multiplier=str_trend,
            strength_counter_multiplier=str_ctr,
        )
        return web.Response(
            text=json.dumps({"ok": ok, "error": None if ok else "ошибка записи файла"}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )

    # --- Блок signals_config ---
    sc_body = body.get("signals_config")
    if sc_body is not None:
        try:
            min_sig    = int(sc_body.get("min_signals", 2))
            ss_min     = int(sc_body.get("single_signal_min_strength", 70))
            prox_pct   = float(sc_body.get("pivot_proximity_pct", 4.0))
            btc_en     = bool(sc_body.get("btc_filter_enabled", True))
            ct_thr     = int(sc_body.get("counter_trend_strength_threshold", 70))
            errors = []
            if not (1 <= min_sig <= 10):        errors.append("min_signals: 1–10")
            if not (30 <= ss_min <= 100):        errors.append("single_signal_min_strength: 30–100")
            if not (0.5 <= prox_pct <= 20.0):    errors.append("pivot_proximity_pct: 0.5–20.0")
            if not (30 <= ct_thr <= 100):        errors.append("counter_trend_strength_threshold: 30–100")
        except (TypeError, ValueError) as e:
            errors = [f"Некорректный тип данных: {e}"]
        if errors:
            return web.Response(
                text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
                content_type="application/json", charset="utf-8",
            )
        # Сохраняем в разные секции конфига
        with open(cfg.config_path, "r", encoding="utf-8") as f:
            import yaml as _yaml
            raw = _yaml.safe_load(f)
        raw.setdefault("analysis", {}).setdefault("signals", {})
        raw["analysis"]["signals"]["min_signals"] = min_sig
        raw["analysis"]["signals"]["single_signal_min_strength"] = ss_min
        raw.setdefault("analysis", {}).setdefault("divergence", {})
        raw["analysis"]["divergence"]["pivot_proximity_pct"] = round(prox_pct, 2)
        raw.setdefault("signal_quality", {})
        raw["signal_quality"]["btc_filter_enabled"] = btc_en
        raw["signal_quality"]["counter_trend_strength_threshold"] = ct_thr
        with open(cfg.config_path, "w", encoding="utf-8") as f:
            _yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        cfg.reload()
        return web.Response(
            text=json.dumps({"ok": True, "error": None}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )

    # --- Блок confluence ---
    conf_body = body.get("confluence")
    if conf_body is not None:
        try:
            enabled   = bool(conf_body.get("enabled", True))
            lookback  = int(conf_body.get("lookback_bars", 40))
            min_str   = int(conf_body.get("min_strength", 60))
            wt_os     = float(conf_body.get("wt_os_threshold", -58))
            wt_ob     = float(conf_body.get("wt_ob_threshold", 58))
            piv_pct   = float(conf_body.get("pivot_proximity_pct", 0.5))
            div_bars  = int(conf_body.get("div_min_bars", 3))
            errors = []
            if not (5 <= lookback <= 200):     errors.append("lookback_bars: 5–200")
            if not (40 <= min_str <= 100):     errors.append("min_strength: 40–100")
            if not (-100 <= wt_os <= -20):     errors.append("wt_os_threshold: -100 до -20")
            if not (20 <= wt_ob <= 100):       errors.append("wt_ob_threshold: 20–100")
            if not (0.1 <= piv_pct <= 5.0):   errors.append("pivot_proximity_pct: 0.1–5.0")
            if not (1 <= div_bars <= 20):      errors.append("div_min_bars: 1–20")
        except (TypeError, ValueError) as e:
            errors = [f"Некорректный тип данных: {e}"]
        if errors:
            return web.Response(
                text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
                content_type="application/json", charset="utf-8",
            )
        try:
            import yaml as _yaml
            with open(cfg.config_path, "r", encoding="utf-8") as f:
                raw = _yaml.safe_load(f)
            raw.setdefault("analysis", {}).setdefault("confluence", {})
            raw["analysis"]["confluence"].update({
                "enabled": enabled,
                "lookback_bars": lookback,
                "min_strength": min_str,
                "wt_os_threshold": wt_os,
                "wt_ob_threshold": wt_ob,
                "pivot_proximity_pct": round(piv_pct, 2),
                "div_min_bars": div_bars,
            })
            with open(cfg.config_path, "w", encoding="utf-8") as f:
                _yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            cfg.reload()
            ok = True
        except Exception as e:
            logger.exception("Ошибка сохранения confluence: %s", e)
            ok = False
        return web.Response(
            text=json.dumps({"ok": ok, "error": None if ok else "ошибка записи файла"}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )

    # --- Блок monitoring_intervals ---
    mon_body = body.get("monitoring_intervals")
    if mon_body is not None:
        try:
            div_n = int(mon_body.get("divergences_every_n_cycles", 3))
            bg_n  = int(mon_body.get("background_every_n_cycles", 5))
            cas_n = int(mon_body.get("cascade_div_every_n_cycles", 60))
            errors = []
            if not (1 <= div_n <= 20):   errors.append("divergences_every_n_cycles: 1–20")
            if not (1 <= bg_n <= 30):    errors.append("background_every_n_cycles: 1–30")
            if not (10 <= cas_n <= 300): errors.append("cascade_div_every_n_cycles: 10–300")
        except (TypeError, ValueError) as e:
            errors = [f"Некорректный тип данных: {e}"]
        if errors:
            return web.Response(
                text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
                content_type="application/json", charset="utf-8",
            )
        ok = cfg.save_monitoring(
            divergences_every_n_cycles=div_n,
            background_every_n_cycles=bg_n,
            cascade_div_every_n_cycles=cas_n,
        )
        return web.Response(
            text=json.dumps({"ok": ok, "error": None if ok else "ошибка записи файла"}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
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


async def start_dashboard(db_path: str = "subscriptions.db", host: str = "0.0.0.0", port: int = 8000,
                          config=None, data_collector=None, trade_simulator=None) -> None:
    """Запускает aiohttp-сервер. Вызывать через asyncio.create_task()."""
    import asyncio
    if config is None:
        from core.config_loader import config as _cfg
        config = _cfg

    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

    app = web.Application()
    app["engine"] = PerformanceEngine(db_path=db_path)
    app["config"] = config
    app["data_collector"] = data_collector   # для получения текущей цены
    app["trade_simulator"] = trade_simulator  # для ручного закрытия сделок
    app["backtest_state"] = {"running": False, "error": None, "log": [], "done": 0, "total": 0}
    app.router.add_get("/", _handle_index)
    app.router.add_get("/api/stats", _handle_stats)
    app.router.add_get("/api/stats/confluence", _handle_confluence_breakdown)
    app.router.add_post("/api/trades/{trade_id}/close", _handle_close_trade)
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
