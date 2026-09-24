/**
 * 用户管理 API
 */
import api from './index'

export interface UserResponse {
  id: string
  username: string
  email: string | null
  role: string
  is_demo: number
  is_active: number
  created_at: string | null
}

export interface PaginatedUsers {
  items: UserResponse[]
  total: number
  page: number
  page_size: number
}

export interface LoginLog {
  id: string
  user_id: string
  ip_address: string
  user_agent: string
  status: string
  created_at: string
}

export interface PaginatedLoginLogs {
  items: LoginLog[]
  total: number
  page: number
  page_size: number
}

export interface ActiveSession {
  user_id: string
  username: string
  ip_address: string
  last_active: string
}

export const usersApi = {
  /** 获取用户列表（分页） */
  async getUsers(page: number = 1, pageSize: number = 20): Promise<PaginatedUsers> {
    const res = await api.get('/users/', { params: { page, page_size: pageSize } })
    return (res as any).data
  },

  /** 创建用户 */
  async createUser(data: { username: string; password: string; email?: string; role?: string; is_demo?: number }): Promise<UserResponse> {
    const res = await api.post('/users/', data)
    return (res as any).data
  },

  /** 获取单个用户 */
  async getUser(userId: string): Promise<UserResponse> {
    const res = await api.get(`/users/${userId}`)
    return (res as any).data
  },

  /** 更新用户 */
  async updateUser(userId: string, data: { email?: string; role?: string; is_demo?: number; is_active?: number }): Promise<UserResponse> {
    const res = await api.put(`/users/${userId}`, data)
    return (res as any).data
  },

  /** 删除用户 */
  async deleteUser(userId: string): Promise<{ message: string }> {
    const res = await api.delete(`/users/${userId}`)
    return (res as any).data
  },

  /** 获取用户登录日志 */
  async getUserLoginLogs(userId: string, page: number = 1, pageSize: number = 20): Promise<PaginatedLoginLogs> {
    const res = await api.get(`/users/${userId}/login-logs`, { params: { page, page_size: pageSize } })
    return (res as any).data
  },

  /** 获取活跃会话 */
  async getActiveSessions(): Promise<ActiveSession[]> {
    const res = await api.get('/users/sessions/active')
    return (res as any).data
  },
}
