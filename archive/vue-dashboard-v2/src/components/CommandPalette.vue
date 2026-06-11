<template>
  <div v-if="open" @click.self="close()"
       style="position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:999;display:flex;align-items:flex-start;justify-content:center;padding-top:80px">
    <div style="background:#161b22;border:1px solid #30363d;border-radius:10px;width:min(640px,92vw);max-height:70vh;display:flex;flex-direction:column;overflow:hidden">
      <input ref="inputEl"
             v-model="query"
             placeholder="Поиск страниц / паттернов / сделок (Esc — закрыть)…"
             @keydown.escape="close()"
             @keydown.down.prevent="moveSelection(1)"
             @keydown.up.prevent="moveSelection(-1)"
             @keydown.enter.prevent="executeSelected()"
             style="background:transparent;border:none;border-bottom:1px solid #30363d;padding:14px 16px;color:#c9d1d9;font-size:1rem;outline:none" />
      <div style="overflow-y:auto;flex:1">
        <div v-if="!results.length" style="padding:20px;text-align:center;color:#8b949e;font-size:.88rem">
          Ничего не найдено
        </div>
        <div v-for="(item, idx) in results"
             :key="item.type + '-' + (item.path || item.title) + '-' + idx"
             :style="idx===selectedIdx ? {background:'#1c2128'} : {}"
             @click="execute(item)"
             @mouseenter="selectedIdx = idx"
             style="padding:8px 16px;cursor:pointer;display:flex;align-items:center;gap:10px;border-bottom:1px solid #21262d">
          <span style="font-size:1.1rem;width:24px;text-align:center">{{ item.icon }}</span>
          <div style="flex:1;min-width:0">
            <div style="color:#c9d1d9;font-size:.92rem;font-weight:500">{{ item.title }}</div>
            <div v-if="item.subtitle" style="color:#8b949e;font-size:.75rem;margin-top:2px">{{ item.subtitle }}</div>
          </div>
          <span style="color:#484f58;font-size:.7rem;text-transform:uppercase">{{ typeLabel(item.type) }}</span>
        </div>
      </div>
      <div style="padding:8px 14px;border-top:1px solid #21262d;color:#484f58;font-size:.72rem;display:flex;gap:12px;justify-content:space-between">
        <span>↑↓ — навигация · Enter — выбрать · Esc — закрыть</span>
        <span>{{ results.length }} рез.</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useDashboardStore } from '@/stores/dashboardStore'

const open = ref(false)
const query = ref('')
const selectedIdx = ref(0)
const inputEl = ref(null)

const patterns = ref([])
const patternsLoaded = ref(false)

const router = useRouter()
const dashboard = useDashboardStore()

const pageItems = [
  { type: 'page', icon: '📊', title: 'Сводка', path: '/' },
  { type: 'page', icon: '📂', title: 'Открытые позиции', path: '/open' },
  { type: 'page', icon: '📋', title: 'История сделок', path: '/history' },
  { type: 'page', icon: '📈', title: 'Аналитика', path: '/analytics' },
  { type: 'page', icon: '🚫', title: 'Drops', path: '/drops' },
  { type: 'page', icon: '🧩', title: 'Паттерны', path: '/patterns' },
  { type: 'page', icon: '🔬', title: 'Decision Trace', path: '/trades' },
]

const tradeItems = computed(() => {
  const opens = dashboard.stats?.open_trades ?? []
  return opens.map(t => ({
    type: 'trade',
    icon: '#',
    title: '#' + t.id + ' ' + (t.symbol?.replace('-USDT', '/USDT') ?? '—'),
    subtitle: `${t.direction} · ${t.signal_type ?? '—'} · R=${t.unrealized_r?.toFixed?.(2) ?? '—'}`,
    path: `/trades/${t.id}`
  }))
})

const patternItems = computed(() => {
  return patterns.value.map(p => ({
    type: 'pattern',
    icon: '🧩',
    title: p.id,
    subtitle: `${p.direction} · avgR=${p.test_avgR?.toFixed?.(2) ?? '—'} · WR=${p.test_WR?.toFixed?.(0) ?? '—'}%`,
    path: '/patterns'
  }))
})

const allItems = computed(() => [...pageItems, ...tradeItems.value, ...patternItems.value])

const results = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return allItems.value.slice(0, 50)
  return allItems.value.filter(item => {
    const inTitle = item.title.toLowerCase().includes(q)
    const inSubtitle = item.subtitle && item.subtitle.toLowerCase().includes(q)
    return inTitle || inSubtitle
  }).slice(0, 50)
})

watch(results, () => {
  selectedIdx.value = 0
})

function moveSelection(delta) {
  if (!results.value.length) return
  const len = results.value.length
  selectedIdx.value = (selectedIdx.value + delta + len) % len
}

function execute(item) {
  if (item.path) router.push(item.path)
  close()
}

function executeSelected() {
  const item = results.value[selectedIdx.value]
  if (item) execute(item)
}

function close() {
  open.value = false
}

function openPalette() {
  open.value = true
  query.value = ''
  selectedIdx.value = 0
  loadPatterns()
  nextTick(() => inputEl.value?.focus())
}

async function loadPatterns() {
  if (patternsLoaded.value) return
  try {
    const r = await fetch('/api/patterns')
    if (!r.ok) return
    const data = await r.json()
    patterns.value = data.patterns ?? []
    patternsLoaded.value = true
  } catch {}
}

function typeLabel(t) {
  return { page: 'СТР', trade: 'СДЕЛКА', pattern: 'ПАТТ' }[t] ?? t
}

// Глобальный шорткат Cmd+K / Ctrl+K с preventDefault (иначе Chrome ловит K в адресной строке).
function onKeydown(e) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    if (!open.value) openPalette()
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>
