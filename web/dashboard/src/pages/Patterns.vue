<template>
  <section>
    <h2>
      Паттерны ARCH-104
      <span style="font-size:.75rem;color:#8b949e;font-weight:400">
        ({{ data.count ?? 0 }} паттернов · v{{ data.version }} · {{ data.generated }})
      </span>
    </h2>

    <!-- Фильтры -->
    <div class="filter-bar" style="margin-bottom:16px;display:flex;align-items:center">
      <label>Направление:</label>
      <select v-model="filterDirection">
        <option value="">Все</option>
        <option value="LONG">LONG</option>
        <option value="SHORT">SHORT</option>
      </select>

      <label style="margin-left:14px">Search:</label>
      <input v-model="filterSearch" placeholder="id или anchor" style="min-width:180px" />

      <label style="margin-left:14px">Мин. test_avgR:</label>
      <input v-model.number="filterMinR" type="number" step="0.1" style="width:70px" />

      <span style="color:#8b949e;font-size:.85em;margin-left:auto">
        Показано: <b style="color:#c9d1d9">{{ filtered.length }}</b> / {{ all.length }}
      </span>
    </div>

    <!-- Состояния -->
    <div v-if="loading" class="note">⏳ Загрузка паттернов…</div>
    <div v-else-if="error" class="note red">Ошибка: {{ error }}</div>
    <div v-else-if="!filtered.length" class="note">Нет паттернов под текущие фильтры.</div>

    <!-- Heatmap (collapsible) -->
    <details v-if="!loading && !error && filtered.length" class="section-collapsible" style="margin-bottom:14px">
      <summary>Heatmap (215 × 4 режима)
        <span style="font-size:.75rem;color:#8b949e;font-weight:400">
          цвет по walkforward test_avgR · клетки RANGE/HIGH_VOL — TBD до live JOIN с features_json
        </span>
      </summary>
      <PatternHeatmap :patterns="filtered" />
    </details>

    <!-- Таблица -->
    <table v-else>
      <thead>
        <tr>
          <th class="sortable" :class="sortClass('priority')" @click="sortBy('priority')">Pri</th>
          <th class="sortable" :class="sortClass('id')" @click="sortBy('id')">ID</th>
          <th class="sortable" :class="sortClass('direction')" @click="sortBy('direction')">Напр.</th>
          <th>Anchor factors</th>
          <th class="sortable" :class="sortClass('test_n')" @click="sortBy('test_n')">n</th>
          <th class="sortable" :class="sortClass('test_WR')" @click="sortBy('test_WR')">WR%</th>
          <th class="sortable" :class="sortClass('test_avgR')" @click="sortBy('test_avgR')">avgR</th>
          <th class="sortable" :class="sortClass('mht_p_adj')" @click="sortBy('mht_p_adj')">MHT p</th>
          <th class="sortable" :class="sortClass('weight')" @click="sortBy('weight')">Вес</th>
          <th>SL src</th>
          <th>TP strat</th>
          <th class="sortable" :class="sortClass('time_exit_hours')" @click="sortBy('time_exit_hours')">Exit ч</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="p in sortedFiltered" :key="p.id">
          <td>{{ p.priority ?? '—' }}</td>
          <td class="mono"><b>{{ p.id }}</b></td>
          <td :class="dirClass(p.direction)"><b>{{ p.direction || '—' }}</b></td>
          <td>
            <template v-if="p.anchor_factors && p.anchor_factors.length">
              <span v-for="a in p.anchor_factors" :key="a"
                    style="display:inline-block;margin:1px 3px 1px 0;padding:1px 6px;border-radius:10px;background:#1a2a3a;color:#58a6ff;font-size:.72rem;font-family:monospace">
                {{ a }}
              </span>
            </template>
            <template v-else>—</template>
          </td>
          <td>{{ p.test_n ?? '—' }}</td>
          <td :class="wrClass(p.test_WR)">{{ fmt(p.test_WR, 1) }}%</td>
          <td :class="rClass(p.test_avgR)">{{ fmtR(p.test_avgR) }}</td>
          <td class="mono">{{ fmt(p.mht_p_adj, 4) }}</td>
          <td>{{ p.weight ?? '—' }}</td>
          <td><code v-if="p.sl_source">{{ p.sl_source }}</code><span v-else>—</span></td>
          <td><code v-if="p.tp_strategy">{{ p.tp_strategy }}</code><span v-else>—</span></td>
          <td>{{ p.time_exit_hours ?? '—' }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import PatternHeatmap from '@/components/PatternHeatmap.vue'

const loading = ref(true)
const error = ref(null)
const data = ref({ patterns: [] })

const filterDirection = ref('')
const filterSearch = ref('')
const filterMinR = ref(null)

onMounted(async () => {
  try {
    const resp = await fetch('/api/patterns')
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    data.value = await resp.json()
  } catch (e) {
    error.value = e.message || 'Ошибка загрузки'
  } finally {
    loading.value = false
  }
})

const all = computed(() => data.value.patterns ?? [])

const filtered = computed(() => {
  return all.value.filter(p => {
    if (filterDirection.value && p.direction !== filterDirection.value) return false

    if (filterSearch.value) {
      const term = filterSearch.value.toLowerCase()
      const idMatch = p.id?.toLowerCase().includes(term)
      const anchorMatch = p.anchor_factors?.some(a => a.toLowerCase().includes(term))
      if (!idMatch && !anchorMatch) return false
    }

    if (filterMinR.value != null && p.test_avgR != null) {
      if (p.test_avgR < filterMinR.value) return false
    }

    return true
  })
})

const sortKey = ref('priority')
const sortDesc = ref(false)

function sortBy(key) {
  if (sortKey.value === key) {
    sortDesc.value = !sortDesc.value
  } else {
    sortKey.value = key
    sortDesc.value = false
  }
}

function sortClass(col) {
  if (sortKey.value !== col) return ''
  return sortDesc.value ? 'sort-desc' : 'sort-asc'
}

const sortedFiltered = computed(() => {
  const arr = [...filtered.value]
  arr.sort((a, b) => {
    const aVal = a[sortKey.value]
    const bVal = b[sortKey.value]

    if (aVal == null && bVal == null) return 0
    if (aVal == null) return 1
    if (bVal == null) return -1

    if (typeof aVal === 'string') {
      return aVal.localeCompare(bVal)
    }
    return aVal - bVal
  })
  if (sortDesc.value) arr.reverse()
  return arr
})

function dirClass(dir) {
  if (dir === 'LONG') return 'green'
  if (dir === 'SHORT') return 'red'
  return ''
}

function wrClass(wr) {
  if (wr == null) return ''
  if (wr >= 70) return 'green'
  if (wr >= 50) return 'yellow'
  return 'red'
}

function rClass(avgR) {
  if (avgR == null) return ''
  return avgR > 0 ? 'green' : avgR < 0 ? 'red' : ''
}

function fmt(val, dec) {
  return val != null ? Number(val).toFixed(dec) : '—'
}

function fmtR(val) {
  if (val == null) return '—'
  const sign = val >= 0 ? '+' : ''
  return `${sign}${Number(val).toFixed(3)}R`
}
</script>
