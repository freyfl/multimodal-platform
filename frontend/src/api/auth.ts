/**
 * 认证相关 API
 */
import api from './index'
import type { LoginResponse, RefreshResponse, AuthUser } from '@/types'

export const authApi = {
  login(username: string, password: string) {
    return api.post<any, LoginResponse>('/auth/login', { username, password })
  },

  register(username: string, password: string, email?: string) {
    return api.post<any, LoginResponse>('/auth/register', { username, password, email })
  },

  refreshToken(refreshToken: string) {
    return api.post<any, RefreshResponse>('/auth/refresh', { refresh_token: refreshToken })
  },

  logout(refreshToken: string) {
    return api.post('/auth/logout', { refresh_token: refreshToken })
  },

  getMe() {
    return api.get<any, AuthUser>('/auth/me')
  },

  changePassword(oldPassword: string, newPassword: string) {
    return api.put('/auth/me/password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
  },
}
