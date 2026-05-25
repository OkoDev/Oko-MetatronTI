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

  async function pollStatusOnce() {
    try {
      const res = await fetch('/api/dashboard')
      if (!res.ok) return
      const data = await res.json()
      status.value = data.status || {}
      if (data.btc_regime !== undefined) status.value.btc_regime = data.btc_regime
    } catch {
      // silent
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
  async function primeFetch() {
    try {
      const [statsRes, equityRes] = await Promise.all([
        fetch('/api/stats'),
        fetch('/api/equity'),
      ])
      if (statsRes.ok) stats.value = await statsRes.json()
      if (equityRes.ok) {
        const e = await equityRes.json()
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
    // getters
    summary,
    criticalAlertData
  }
})
