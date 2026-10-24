import { defineStore } from 'pinia'

import { api, getStoredToken, setStoredToken } from '../api/client'
import type { AuthUser, TokenOut } from '../types'

interface HealthAuthInfo {
  auth_required: boolean
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getStoredToken(),
    user: null as AuthUser | null,
    /** 后端 AUTH_MODE != none 时为 true，前端据此启用登录守卫 */
    authRequired: false,
    bootstrapped: false,
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token),
  },
  actions: {
    /** 启动时执行一次：探测后端是否要求登录，并校验本地 token 有效性 */
    async ensureBootstrapped(): Promise<void> {
      if (this.bootstrapped) return
      this.bootstrapped = true
      try {
        const { data } = await api.get<HealthAuthInfo>('/health')
        this.authRequired = Boolean(data.auth_required)
      } catch {
        this.authRequired = false
      }
      if (this.token && this.authRequired) {
        try {
          const { data } = await api.get<AuthUser>('/auth/me')
          this.user = data
        } catch {
          this.logout()
        }
      }
    },
    async login(username: string, password: string): Promise<void> {
      const form = new URLSearchParams()
      form.append('username', username)
      form.append('password', password)
      const { data } = await api.post<TokenOut>('/auth/token', form)
      this.token = data.access_token
      this.user = data.user
      setStoredToken(data.access_token)
    },
    logout(): void {
      this.token = null
      this.user = null
      setStoredToken(null)
    },
  },
})
