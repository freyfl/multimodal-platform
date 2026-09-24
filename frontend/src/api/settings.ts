/**
 * 用户系统配置 API
 */
import api from './index'
import type { ApiResponse, ServiceErrorDetail } from './types'

export interface UserSettingsResponse {
  id: string
  user_id: string
  tos_access_key_id_masked?: string | null
  tos_access_key_secret_masked?: string | null
  tos_security_token_masked?: string | null
  tos_bucket_name?: string | null
  tos_endpoint?: string | null
  tos_region?: string | null
  tos_custom_domain?: string | null
  ark_api_key_masked?: string | null
  embedding_model?: string | null
  embedding_dimension?: number | null
  tag_model?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface UserSettingsUpdate {
  tos_access_key_id?: string
  tos_access_key_secret?: string
  tos_security_token?: string
  tos_bucket_name?: string
  tos_endpoint?: string
  tos_region?: string
  tos_custom_domain?: string
  ark_api_key?: string
  embedding_model?: string
  embedding_dimension?: number
  tag_model?: string
}

export interface ConnectionTestResult {
  success: boolean
  message?: string
  error?: ServiceErrorDetail | null
}

export interface ArkTestResult {
  success: boolean
  embedding: ConnectionTestResult
  tag: ConnectionTestResult
}

export const settingsApi = {
  /** 获取当前用户配置 */
  async getMySettings(): Promise<UserSettingsResponse> {
    const res = await api.get('/settings/me') as unknown as ApiResponse<UserSettingsResponse>
    return res.data
  },

  /** 更新配置 */
  async updateMySettings(data: UserSettingsUpdate): Promise<UserSettingsResponse> {
    const res = await api.put('/settings/me', data) as unknown as ApiResponse<UserSettingsResponse>
    return res.data
  },

  /** 删除配置（回退全局默认） */
  async deleteMySettings(): Promise<void> {
    await api.delete('/settings/me')
  },

  /** 测试 TOS 连接 */
  async testTos(data: Partial<UserSettingsUpdate>): Promise<ConnectionTestResult> {
    const res = await api.post('/settings/me/test-tos', data) as unknown as ApiResponse<ConnectionTestResult>
    return res.data
  },

  /** 测试方舟 API Key */
  async testArk(data: Partial<UserSettingsUpdate>): Promise<ArkTestResult> {
    const res = await api.post('/settings/me/test-ark', data) as unknown as ApiResponse<ArkTestResult>
    return res.data
  },

  async getUserSettings(userId: string): Promise<UserSettingsResponse> {
    const res = await api.get(`/settings/users/${userId}`) as unknown as ApiResponse<UserSettingsResponse>
    return res.data
  },

  async updateUserSettings(userId: string, data: UserSettingsUpdate): Promise<UserSettingsResponse> {
    const res = await api.put(`/settings/users/${userId}`, data) as unknown as ApiResponse<UserSettingsResponse>
    return res.data
  },

  async deleteUserSettings(userId: string): Promise<void> {
    await api.delete(`/settings/users/${userId}`)
  },

  async testUserTos(userId: string, data: Partial<UserSettingsUpdate>): Promise<ConnectionTestResult> {
    const res = await api.post(`/settings/users/${userId}/test-tos`, data) as unknown as ApiResponse<ConnectionTestResult>
    return res.data
  },

  async testUserArk(userId: string, data: Partial<UserSettingsUpdate>): Promise<ArkTestResult> {
    const res = await api.post(`/settings/users/${userId}/test-ark`, data) as unknown as ApiResponse<ArkTestResult>
    return res.data
  },
}
