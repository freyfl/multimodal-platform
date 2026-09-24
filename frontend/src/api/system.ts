import api from './index'
import type { ApiResponse, PublicSystemConfig, SystemStats } from './types'

export async function getSystemHealth(): Promise<ApiResponse> {
  return api.get('/system/health')
}

export async function getSystemStats(): Promise<ApiResponse<SystemStats>> {
  return api.get('/system/stats')
}

export async function getSystemConfig(): Promise<ApiResponse<PublicSystemConfig>> {
  return api.get('/system/config')
}

export async function getDashboardInfo(): Promise<ApiResponse> {
  return api.get('/system/dashboard')
}
