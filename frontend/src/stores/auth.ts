/**
 * Auth Store - 用户认证状态管理
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'
import type { AuthUser } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const accessToken = ref<string | null>(localStorage.getItem('accessToken'))
  const refreshToken = ref<string | null>(localStorage.getItem('refreshToken'))

  const isLoggedIn = computed(() => !!accessToken.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  function setTokens(access: string, refresh: string) {
    accessToken.value = access
    refreshToken.value = refresh
    localStorage.setItem('accessToken', access)
    localStorage.setItem('refreshToken', refresh)
  }

  function clearAuth() {
    user.value = null
    accessToken.value = null
    refreshToken.value = null
    localStorage.removeItem('accessToken')
    localStorage.removeItem('refreshToken')
    // 重置 init 单例，使下次登录后 ensureInit 能重新拉取用户信息
    _initPromise = null
  }

  async function login(username: string, password: string) {
    const res: any = await authApi.login(username, password)
    // 响应拦截器返回 axios response.data (即 ApiResponse {code, message, data})
    const payload = res?.data ?? res
    setTokens(payload.access_token, payload.refresh_token)
    user.value = payload.user
    return payload
  }

  async function register(username: string, password: string, email?: string) {
    const res: any = await authApi.register(username, password, email)
    const payload = res?.data ?? res
    setTokens(payload.access_token, payload.refresh_token)
    user.value = payload.user
    return payload
  }

  async function logout() {
    try {
      if (refreshToken.value) {
        await authApi.logout(refreshToken.value)
      }
    } catch {
      // 即使 logout 接口失败也继续清除本地状态
    } finally {
      clearAuth()
    }
  }

  async function refreshAccessToken() {
    if (!refreshToken.value) {
      clearAuth()
      throw new Error('No refresh token')
    }
    try {
      const res: any = await authApi.refreshToken(refreshToken.value)
      const payload = res?.data ?? res
      const newToken = payload.access_token
      accessToken.value = newToken
      localStorage.setItem('accessToken', newToken)
      return newToken
    } catch {
      clearAuth()
      throw new Error('Token refresh failed')
    }
  }

  async function fetchUser() {
    try {
      const res: any = await authApi.getMe()
      // getMe 返回 ApiResponse，实际用户数据在 .data 中
      user.value = res?.data ?? res
    } catch {
      clearAuth()
    }
  }

  // 用于确保路由守卫等待 init 完成
  let _initPromise: Promise<void> | null = null

  async function init() {
    if (accessToken.value) {
      await fetchUser()
    }
  }

  /** 单例 init，路由守卫可 await 确保初始化完成 */
  function ensureInit(): Promise<void> {
    if (!_initPromise) {
      _initPromise = init()
    }
    return _initPromise
  }

  return {
    user,
    accessToken,
    refreshToken,
    isLoggedIn,
    isAdmin,
    login,
    register,
    logout,
    refreshAccessToken,
    fetchUser,
    init,
    ensureInit,
    clearAuth,
  }
})
