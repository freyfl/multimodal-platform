import { defineStore } from 'pinia'
import { ref } from 'vue'
import { startImport, getImportTasks, getImportTaskStatus, cancelImportTask } from '@/api/import'
import type { ImportTask, StartImportParams } from '@/types'

export const useImportStore = defineStore('import', () => {
  const tasks = ref<ImportTask[]>([])
  const currentTask = ref<ImportTask | null>(null)
  const isLoading = ref(false)
  const isImporting = ref(false)

  const fetchTasks = async () => {
    isLoading.value = true
    try {
      const res = await getImportTasks()
      tasks.value = res?.data?.tasks || []
    } catch {
      tasks.value = []
    } finally {
      isLoading.value = false
    }
  }

  const startImportTask = async (params: StartImportParams) => {
    isImporting.value = true
    try {
      const res = await startImport(params)
      if (res?.data?.task_id) {
        await fetchTasks()
      }
      return res
    } finally {
      isImporting.value = false
    }
  }

  const refreshTaskStatus = async (taskId: string) => {
    try {
      const res = await getImportTaskStatus(taskId)
      const index = tasks.value.findIndex(t => t.task_id === taskId)
      if (index !== -1 && res?.data) {
        tasks.value[index] = res.data
      }
      return res?.data
    } catch (e) {
      console.error('刷新任务状态失败:', e)
      return null
    }
  }

  const cancelTask = async (taskId: string) => {
    try {
      await cancelImportTask(taskId)
      await fetchTasks()
      return true
    } catch {
      return false
    }
  }

  return {
    tasks,
    currentTask,
    isLoading,
    isImporting,
    fetchTasks,
    startImportTask,
    refreshTaskStatus,
    cancelTask
  }
})
