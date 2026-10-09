import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getSystemStats, getSystemHealth, getSystemConfig } from '@/api/system'
import type { PublicSystemConfig, SystemStats } from '@/types'
import { validateCatalog } from '@/utils/modelCatalog'

export const useSystemStore = defineStore('system', () => {
  const stats = ref<SystemStats | null>(null)
  const config = ref<PublicSystemConfig | null>(null)
  const configLoading = ref(false)
  const configError = ref('')
  const catalog = computed(() => config.value?.model_catalog ?? null)
  const catalogReady = computed(() => !!catalog.value && !configLoading.value && !configError.value)
  let configRequest: Promise<void> | null = null
  const isLoading = ref(false)
  const isHealthy = ref(false)
  const statsError = ref('')

  const fetchStats = async () => {
    isLoading.value = true
    statsError.value = ''
    try {
      const res = await getSystemStats()
      stats.value = res?.data || null
    } catch (e) {
      stats.value = null
      statsError.value = '系统统计不可用，请重试'
    } finally {
      isLoading.value = false
    }
  }

  const checkHealth = async () => {
    try {
      await getSystemHealth()
      isHealthy.value = true
    } catch (e) {
      isHealthy.value = false
    }
  }

  const fetchConfig = (): Promise<void> => {
    if (configRequest) return configRequest
    configLoading.value = true
    configError.value = ''
    configRequest = (async () => {
      try {
        const res = await getSystemConfig()
        if (!validateCatalog(res.data?.model_catalog)) throw new Error('invalid catalog')
        config.value = res.data
      } catch {
        config.value = null
        configError.value = '模型目录加载失败或配置不兼容，相关操作已禁用，请重试'
      } finally {
        configLoading.value = false
        configRequest = null
      }
    })()
    return configRequest
  }

  return {
    stats,
    statsError,
    config,
    catalog,
    catalogReady,
    configLoading,
    configError,
    isLoading,
    isHealthy,
    fetchStats,
    checkHealth,
    fetchConfig
  }
})
