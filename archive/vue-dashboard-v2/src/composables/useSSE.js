import { ref } from 'vue'

/**
 * Обёртка вокруг EventSource с auto-reconnect.
 *
 * @param {string} url — URL SSE endpoint
 * @param {Object<string, (data: any) => void>} handlers — карта { eventName: handler(parsed) }
 * @returns {{ isConnected: Ref<boolean>, lastError: Ref<string|null>, disconnect: () => void }}
 *
 * Использование:
 *   const { isConnected } = useSSE('/api/events?dashboard=1', {
 *     dashboard: payload => { dashboardStore.applyDashboard(payload) },
 *     stats:     payload => { dashboardStore.applyStats(payload) },
 *   })
 */
export function useSSE(url, handlers = {}) {
  const isConnected = ref(false)
  const lastError = ref(null)

  let es = null
  let reconnectTimer = null
  let reconnectDelay = 1000
  const MAX_RECONNECT_DELAY = 30000

  function connect() {
    if (es) return
    try {
      es = new EventSource(url)
    } catch (e) {
      lastError.value = e.message
      scheduleReconnect()
      return
    }

    es.onopen = () => {
      isConnected.value = true
      lastError.value = null
      reconnectDelay = 1000 // сброс backoff после успешного соединения
    }

    es.onerror = () => {
      isConnected.value = false
      lastError.value = 'SSE connection error'
      // EventSource сам пробует переподключиться, но если он закрылся — сделаем это вручную.
      if (es && es.readyState === EventSource.CLOSED) {
        cleanup()
        scheduleReconnect()
      }
    }

    for (const [eventName, handler] of Object.entries(handlers)) {
      es.addEventListener(eventName, (msgEvent) => {
        try {
          const parsed = JSON.parse(msgEvent.data)
          handler(parsed)
        } catch (e) {
          // Битый JSON — пропускаем, лог не нужен (в проде шумно)
        }
      })
    }
  }

  function cleanup() {
    if (es) {
      es.close()
      es = null
    }
    isConnected.value = false
  }

  function scheduleReconnect() {
    if (reconnectTimer) return
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY)
      connect()
    }, reconnectDelay)
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    cleanup()
  }

  // Caller отвечает за disconnect() — composable нейтрален к lifecycle
  // (используется и из Pinia stores, где onUnmounted не сработал бы).
  connect()

  return { isConnected, lastError, disconnect }
}
