import api from './index'
import type { ApiResponse, ImportTask, StartImportParams } from './types'

export async function startImport(params: StartImportParams): Promise<ApiResponse<{ task_id: string }>> {
  return api.post('/import/start', params)
}

export async function getImportTasks(): Promise<ApiResponse<{ tasks: ImportTask[] }>> {
  return api.get('/import/tasks')
}

export async function getImportTaskStatus(taskId: string): Promise<ApiResponse<ImportTask>> {
  return api.get(`/import/tasks/${taskId}`)
}

export async function cancelImportTask(taskId: string): Promise<ApiResponse> {
  return api.delete(`/import/tasks/${taskId}`)
}
