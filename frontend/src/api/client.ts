import axios from 'axios'
import type { AuthMode } from '../types'

const TOKEN_STORAGE_KEY = 'safety_hazard_token'
let authenticationMode: AuthMode | 'unknown' = 'unknown'

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

export function setStoredToken(token: string | null): void {
  if (token) {
    localStorage.setItem(TOKEN_STORAGE_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
  }
}

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api/v1',
  timeout: 90000,
})

// 请求拦截：注入 Bearer token
api.interceptors.request.use((config) => {
  const token = getStoredToken()
  if (token && authenticationMode !== 'none' && !config.headers.has('Authorization')) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 只对已确认的 JWT 模式处理会话过期；静态凭证 401 保留凭证并交给页面说明。
api.interceptors.response.use(
  (response) => {
    if (response.config.url === '/health') {
      const data = response.data
      authenticationMode = ['none', 'token', 'jwt'].includes(data.auth_mode) ? data.auth_mode
        : data.auth_mode === undefined && typeof data.auth_required === 'boolean'
          ? data.auth_required ? 'jwt' : 'none' : 'unknown'
    }
    if (response.config.url === '/auth/token') authenticationMode = 'jwt'
    return response
  },
  (error) => {
    const status = error?.response?.status
    const path = window.location.pathname
    const sent = error?.config?.headers?.Authorization
    const stored = getStoredToken()
    const isCurrentCredential = !stored || sent === `Bearer ${stored}`
    if (status === 401 && authenticationMode === 'jwt' && isCurrentCredential
      && error?.config?.url !== '/auth/token') {
      setStoredToken(null)
      if (!path.startsWith('/login')) window.location.assign('/login')
    }
    return Promise.reject(error)
  },
)
