<script setup>
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import ClosedTradesTable from '@/components/ClosedTradesTable.vue'
import { useClosedTradesStore } from '@/stores/closedTradesStore'

const store = useClosedTradesStore()
const { rows, page, perPage, total, totalPages, loading, error } = storeToRefs(store)

onMounted(() => store.fetchPage(1))
</script>

<template>
  <section>
    <h2>История сделок</h2>
    <ClosedTradesTable
      :trades="rows"
      :page="page"
      :per-page="perPage"
      :total="total"
      :total-pages="totalPages"
      :loading="loading"
      :error="error"
      @prev="store.prevPage()"
      @next="store.nextPage()"
      @per-page-change="store.setPerPage($event)"
    />
  </section>
</template>
