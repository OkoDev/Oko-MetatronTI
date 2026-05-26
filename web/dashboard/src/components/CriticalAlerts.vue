<template>
  <section class="critical-alerts" v-if="alerts.length">
    <div v-for="(alert, idx) in alerts" :key="idx" :class="['alert-banner', alert.type]">
      <span class="alert-icon">{{ alert.icon }}</span>
      {{ alert.text }}
      <a v-if="alert.link" :href="alert.link" target="_blank" rel="noopener" class="alert-link">{{ alert.linkText }}</a>
      <span class="alert-detail">{{ alert.detail }}</span>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: {
    type: Object,
    default: () => ({})
  }
})

const exchangeHealth = computed(() => props.data.exchange_health ?? 'HEALTHY')
const exchangeLatency = computed(() => props.data.exchange_latency_ms ?? null)
const status = computed(() => props.data.status ?? {})
const scanHealth = computed(() => status.value.scan_health ?? 'unknown')
const monitoredPairs = computed(() => status.value.monitored_pairs ?? 0)
const isMonitoring = computed(() => status.value.is_monitoring ?? false)

const alerts = computed(() => {
  const list = []

  // BingX group (mutually exclusive)
  // D-076 (26.05): ссылка на cryptohopper external status — отличает наши баги от проблем биржи
  const bingxStatusUrl = 'https://status.cryptohopper.com/exchange.html?detail=bingx'
  if (exchangeHealth.value === 'DOWN') {
    list.push({
      type: 'red',
      icon: '⛔',
      text: 'BingX недоступен',
      detail: 'бот не открывает live ордера',
      link: bingxStatusUrl,
      linkText: 'проверить статус BingX'
    })
  } else if (
    exchangeHealth.value === 'DEGRADED' ||
    (exchangeLatency.value !== null && exchangeLatency.value > 3000)
  ) {
    const lat = exchangeLatency.value !== null ? exchangeLatency.value : '?'
    list.push({
      type: 'amber',
      icon: '⚠',
      text: 'BingX лагает',
      detail: `latency=${lat}ms`,
      link: bingxStatusUrl,
      linkText: 'проверить статус BingX'
    })
  }

  // Scan group (mutually exclusive)
  if (scanHealth.value === 'DEAD') {
    list.push({
      type: 'red',
      icon: '💀',
      text: 'Scan loop мёртв',
      detail: 'подозрение на cascade D-053 — рестарт нужен'
    })
  } else if (scanHealth.value === 'delayed') {
    list.push({
      type: 'amber',
      icon: '⏳',
      text: 'Scan loop задержка',
      detail: 'age > 6 мин'
    })
  }

  // Pairs group (can coexist)
  if (monitoredPairs.value === 0 && isMonitoring.value) {
    list.push({
      type: 'amber',
      icon: '📵',
      text: 'monitored_pairs = 0',
      detail: 'бот стартует или recovery'
    })
  }

  return list
})
</script>

<style scoped>
.alert-link {
  color: inherit;
  text-decoration: underline;
  margin-left: 6px;
  font-weight: 400;
  font-size: .82rem;
  opacity: 0.9;
}
.alert-link:hover { opacity: 1; }
</style>
