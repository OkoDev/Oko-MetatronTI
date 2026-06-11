import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { useSSE } from '@/composables/useSSE'

export const useDashboardStore = defineStore('dashboard', () => {
  // State
  const stats = ref({})
  const status = ref({})
  const equity = ref([])
  const confluence = ref({})
  const breakeven = ref({})
  const analytics = ref({})
  const signalWeights = ref({})
  const lastUpdate = ref(null)
  const isLive = ref(false)
  const sseError = ref(null)

  // Internal helpers
  let _sseHandle = null
  let _statusPollTimer = null

  // SSE handlers
  function applyDashboard(data) {
    if (data.stats) stats.value = data.stats
    if (data.equity) equity.value = data.equity
    if (data.confluence) confluence.value = data.confluence
    if (data.breakeven) breakeven.value = data.breakeven
    if (data.analytics) analytics.value = data.analytics
    if (data.signal_weights) signalWeights.value = data.signal_weights
    lastUpdate.value = new Date()
  }

  function applyStats(data) {
    if (data.summary) stats.value = { ...stats.value, summary: data.summary }
    if (data.rolling) stats.value = { ...stats.value, rolling: data.rolling }
    lastUpdate.value = new Date()
  }

  // Helper: fetch с timeout 5с — backend под нагрузкой может висеть.
  async function fetchWithTimeout(url, ms = 5000) {
    const ctrl = new AbortController()
    const id = setTimeout(() => ctrl.abort(), ms)
    try {
      return await fetch(url, { signal: ctrl.signal })
    } finally {
      clearTimeout(id)
    }
  }

  async function pollStatusOnce() {
    try {
      // 15с — endpoint вызывает engine.full_stats() (heavy), 5с не хватало.
      const res = await fetchWithTimeout('/api/dashboard', 15000)
      if (!res.ok) {
        console.warn('[dashboardStore] /api/dashboard HTTP', res.status)
        return
      }
      const data = await res.json()
      status.value = data.status || {}
      if (data.btc_regime !== undefined) status.value.btc_regime = data.btc_regime
    } catch (e) {
      console.warn('[dashboardStore] /api/dashboard fail:', e.name, e.message)
    }
  }

  function startStatusPolling() {
    if (_statusPollTimer) return
    pollStatusOnce()
    // 30s (было 10s) — status (scan_health/monitored_pairs) меняется не часто.
    _statusPollTimer = setInterval(pollStatusOnce, 30000)
  }

  // Первичный быстрый fetch, чтобы карточки не висели пустыми
  // 5-15с пока придёт первый тяжёлый SSE event:dashboard payload.
  // 15с timeout: /api/stats тяжёлый (full_stats на 15k+ сделок), 10с не хватало.
  async function primeFetch() {
    try {
      const [statsRes, equityRes] = await Promise.allSettled([
        fetchWithTimeout('/api/stats', 15000),
        fetchWithTimeout('/api/equity', 15000),
      ])
      if (statsRes.status === 'fulfilled' && statsRes.value.ok) {
        stats.value = await statsRes.value.json()
      }
      if (equityRes.status === 'fulfilled' && equityRes.value.ok) {
        const e = await equityRes.value.json()
        equity.value = Array.isArray(e) ? e : []
      }
      lastUpdate.value = new Date()
    } catch {
      // silent — SSE подхватит позже
    }
  }

  function stopStatusPolling() {
    if (_statusPollTimer) {
      clearInterval(_statusPollTimer)
      _statusPollTimer = null
    }
  }

  // Lazy fetch — вызывается только при раскрытии соответствующей секции.
  // Эти endpoints тяжёлые (SQL агрегация), не имеет смысла дёргать на каждый mount.
  async function fetchConfluence() {
    try {
      const r = await fetchWithTimeout('/api/stats/confluence', 10000)
      if (r.ok) confluence.value = await r.json()
    } catch { /* silent */ }
  }
  async function fetchBreakeven() {
    try {
      const r = await fetchWithTimeout('/api/stats/breakeven', 10000)
      if (r.ok) breakeven.value = await r.json()
    } catch { /* silent */ }
  }

  // Public actions
  function connect() {
    if (_sseHandle) return
    // Первичная быстрая загрузка — карточки получают данные за 200-500ms,
    // не ждут 5-15с первого SSE event:dashboard payload.
    primeFetch()
    // event:stats — лёгкий short payload (summary + rolling) каждые 5s.
    // event:dashboard (heavy 6-endpoint агрегация) ОТКЛЮЧЁН — backend не успевает
    // под нагрузкой scan_loop + ws_feed на 240 парах. Equity/analytics/confluence
    // обновятся при F5 reload через primeFetch, real-time не критичен.
    _sseHandle = useSSE('/api/events', {
      dashboard: applyDashboard,
      stats: applyStats
    })
    watch(_sseHandle.isConnected, (v) => { isLive.value = v }, { immediate: true })
    watch(_sseHandle.lastError, (v) => { sseError.value = v }, { immediate: true })
    startStatusPolling()
  }

  function disconnect() {
    if (_sseHandle) {
      _sseHandle.disconnect()
      _sseHandle = null
    }
    isLive.value = false
    stopStatusPolling()
  }

  // Getters
  const summary = computed(() => stats.value.summary ?? {})
  const criticalAlertData = computed(() => ({
    exchange_health: stats.value.exchange_health,
    exchange_latency_ms: stats.value.exchange_latency_ms,
    status: status.value
  }))

  return {
    // state
    stats,
    status,
    equity,
    confluence,
    breakeven,
    analytics,
    signalWeights,
    lastUpdate,
    isLive,
    sseError,
    // actions
    connect,
    disconnect,
    fetchConfluence,
    fetchBreakeven,
    // getters
    summary,
    criticalAlertData
  }
})
