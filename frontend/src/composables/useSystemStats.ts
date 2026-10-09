import { useSystemStore } from '@/stores'
import { storeToRefs } from 'pinia'
import { onMounted, onUnmounted } from 'vue'

export function useSystemStats(autoRefresh = true, refreshInterval = 30000) {
  const store = useSystemStore()
  const { stats, isLoading, isHealthy } = storeToRefs(store)

  let timer: ReturnType<typeof setInterval> | null = null

  const fetch = () => store.fetchStats()
  const checkHealth = () => store.checkHealth()

  onMounted(() => {
    fetch()
    checkHealth()
    if (autoRefresh) {
      timer = setInterval(() => {
        fetch()
        checkHealth()
      }, refreshInterval)
    }
  })

  onUnmounted(() => {
    if (timer) {
      clearInterval(timer)
    }
  })

  return {
    stats,
    isLoading,
    isHealthy,
    fetch,
    checkHealth
  }
}
