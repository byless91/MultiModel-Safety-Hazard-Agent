import axios from 'axios'

const TOKEN_STORAGE_KEY = 'safety_hazard_token'

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
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：401（token 缺失/过期）清除本地凭证并跳登录页
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status
    const path = window.location.pathname
    if (status === 401 && !path.startsWith('/login')) {
      setStoredToken(null)
      window.location.assign('/login')
    }
    return Promise.reject(error)
  },
)
