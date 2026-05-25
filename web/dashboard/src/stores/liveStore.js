import { defineStore } from 'pinia'
import { ref } from 'vue'

// Lightweight стор для /api/live — баланс/позиции BingX.
// SSE-канал не покрывает live-данные биржи, оставляем polling 5s.
export const useLiveStore = defineStore('live', () => {
  const data = ref({})
  const error = ref(null)
  let _timer = null

  async function fetchOnce() {
    try {
      const r = await fetch('/api/live')
      if (!r.ok) {
        error.value = `HTTP ${r.status}`
        return
      }
      data.value = await r.json()
      error.value = null
    } catch (e) {
      error.value = e.message
    }
  }

  // 30s по умолчанию (было 5s): /api/live дёргает BingX REST,
  // частый polling добавляет ~12 req/мин на rate-limit поверх scan_loop + position_sync.
  function start(intervalMs = 30000) {
    if (_timer) return
    fetchOnce()
    _timer = setInterval(fetchOnce, intervalMs)
  }

  function stop() {
    if (_timer) {
      clearInterval(_timer)
      _timer = null
    }
  }

  return { data, error, start, stop }
})
