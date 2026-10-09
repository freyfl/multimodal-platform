/**
 * API请求封装
 */
import axios from 'axios'
import { message } from 'ant-design-vue'

// 创建axios实例
const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器 - 自动附加 Bearer token
api.interceptors.request.use(
  config => {
    const token = localStorage.getItem('accessToken')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => {
    return Promise.reject(error)
  }
)

// Token 刷新锁，避免并发刷新
let isRefreshing = false
let failedQueue: Array<{
  resolve: (token: string) => void
  reject: (error: any) => void
}> = []

function processQueue(error: any, token: string | null = null) {
  failedQueue.forEach(prom => {
    if (error) {
      prom.reject(error)
    } else {
      prom.resolve(token!)
    }
  })
  failedQueue = []
}

// 响应拦截器
api.interceptors.response.use(
  response => {
    return response.data
  },
  async error => {
    const originalRequest = error.config

    // 401 且非刷新请求本身 → 尝试刷新 token
    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      !originalRequest.url?.includes('/auth/refresh') &&
      !originalRequest.url?.includes('/auth/login')
    ) {
      if (isRefreshing) {
        // 已在刷新中，排队等待
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        }).then(token => {
          originalRequest.headers.Authorization = `Bearer ${token}`
          return api(originalRequest)
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      const refreshToken = localStorage.getItem('refreshToken')
      if (!refreshToken) {
        isRefreshing = false
        processQueue(error, null)
        redirectToLogin()
        return Promise.reject(error)
      }

      try {
        const res = await axios.post('/api/auth/refresh', { refresh_token: refreshToken })
        // 后端返回 ApiResponse {code, message, data: {access_token, token_type}}
        const newToken = res.data?.data?.access_token || res.data?.access_token
        if (!newToken) {
          throw new Error('No access_token in refresh response')
        }
        localStorage.setItem('accessToken', newToken)
        processQueue(null, newToken)
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return api(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        localStorage.removeItem('accessToken')
        localStorage.removeItem('refreshToken')
        redirectToLogin()
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    const errorMsg = error.response?.data?.detail || error.message || '请求失败'
    // 不对 401 重复弹错误提示
    if (error.response?.status !== 401) {
      message.error(errorMsg)
    }
    return Promise.reject(error)
  }
)

function redirectToLogin() {
  // 避免在登录页反复跳转
  if (window.location.pathname !== '/login') {
    window.location.href = '/login'
  }
}

export default api
