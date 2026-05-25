import { defineStore } from 'pinia'
import { ref } from 'vue'

// Закрытые сделки тянутся отдельно с пагинацией.
// Полный backfill не нужен — рисуем 50 на страницу.
export const useClosedTradesStore = defineStore('closedTrades', () => {
  const rows = ref([])
  const page = ref(1)
  const perPage = ref(50)
  const total = ref(0)
  const totalPages = ref(1)
  const loading = ref(false)
  const error = ref(null)

  async function fetchPage(p = page.value) {
    loading.value = true
    try {
      const r = await fetch(`/api/closed_trades?page=${p}&per_page=${perPage.value}`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      rows.value = data.rows ?? []
      page.value = data.page ?? p
      perPage.value = data.per_page ?? perPage.value
      total.value = data.total ?? 0
      totalPages.value = data.total_pages ?? 1
      error.value = null
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  function setPerPage(n) {
    perPage.value = Math.max(10, Math.min(200, Number(n) || 50))
    page.value = 1
    fetchPage(1)
  }

  function nextPage() {
    if (page.value < totalPages.value) fetchPage(page.value + 1)
  }
  function prevPage() {
    if (page.value > 1) fetchPage(page.value - 1)
  }

  return { rows, page, perPage, total, totalPages, loading, error, fetchPage, setPerPage, nextPage, prevPage }
})
