<template>
  <div>
    <div v-if="!positions.length" class="note">Нет открытых позиций на бирже.</div>
    <table v-else>
      <thead>
        <tr>
          <th>Символ</th>
          <th>Side</th>
          <th>TSL</th>
          <th>Размер</th>
          <th>Плечо</th>
          <th>Вход</th>
          <th>Mark</th>
          <th>Δ %</th>
          <th>P&amp;L</th>
          <th>SL</th>
          <th>TP</th>
          <th>Маржа</th>
          <th>Liq.</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="p in positions" :key="p.symbol + p.side">
          <td class="mono">{{ formatSymbol(p.symbol) }}</td>
          <td :class="sideClass(p.side)"><b>{{ p.side }}</b></td>
          <td>
            <span v-if="p.tsl_activated" class="badge badge-tsl" :title="p.tsl_tf ? `TSL активен на ${p.tsl_tf}` : 'TSL активен'">TSL</span>
            <span v-else style="color:#484f58">—</span>
          </td>
          <td class="mono">{{ fmt(p.size) }}</td>
          <td>{{ p.leverage }}x</td>
          <td class="mono">{{ fmt(p.entry_price, 5) }}</td>
          <td class="mono">{{ fmt(p.mark_price, 5) }}</td>
          <td :class="signClass(movePct(p))">{{ fmtPct(movePct(p)) }}</td>
          <td :class="signClass(p.unrealized_pnl)">{{ fmtUsd(p.unrealized_pnl) }}</td>
          <td class="mono red">{{ fmt(p.stop_loss, 5) }}</td>
          <td class="mono green">{{ fmt(p.take_profit, 5) }}</td>
          <td class="mono">{{ fmtUsd(p.margin, 0) }}</td>
          <td class="mono">{{ fmt(p.liquidation_price, 5) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
defineProps({
  positions: { type: Array, default: () => [] }
})

const dash = '—'

function formatSymbol(s) {
  if (!s) return dash
  return s.replace('-USDT', '/USDT').replace('-', '/')
}

function sideClass(side) {
  return side === 'LONG' ? 'green' : side === 'SHORT' ? 'red' : ''
}

function signClass(v) {
  if (v == null || isNaN(v)) return ''
  return v > 0 ? 'green' : v < 0 ? 'red' : ''
}

function fmt(v, dec) {
  if (v == null) return dash
  return dec != null ? Number(v).toPrecision(dec) : Number(v).toString()
}

function fmtUsd(v, dec = 2) {
  if (v == null) return dash
  const sign = v >= 0 ? '+' : ''
  return `${sign}$${Number(v).toFixed(dec)}`
}

function fmtPct(v) {
  if (v == null || isNaN(v)) return dash
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

// Расчёт ±% с учётом направления (для SHORT движение вниз = плюс)
function movePct(p) {
  if (!p.entry_price || !p.mark_price) return null
  const raw = (p.mark_price - p.entry_price) / p.entry_price * 100
  return p.side === 'SHORT' ? -raw : raw
}
</script>
