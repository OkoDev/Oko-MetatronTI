import { ref, watch } from 'vue'

const STORAGE_KEY = 'oko-density'
const density = ref(localStorage.getItem(STORAGE_KEY) || 'comfort')

watch(density, (v) => {
  localStorage.setItem(STORAGE_KEY, v)
})

// Singleton — один и тот же ref для всего приложения.
export function useDensity() {
  function toggle() {
    density.value = density.value === 'comfort' ? 'compact' : 'comfort'
  }
  return { density, toggle }
}
