import { defineStore } from 'pinia'

import { api, getStoredToken, setStoredToken } from '../api/client'
import type { AuthMode, AuthUser, TokenOut } from '../types'

interface HealthAuthInfo {
  auth_required: boolean
  auth_mode?: AuthMode
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getStoredToken(),
    user: null as AuthUser | null,
    /** 后端 AUTH_MODE != none 时为 true，前端据此启用登录守卫 */
    authRequired: true,
    authMode: 'unknown' as AuthMode | 'unknown',
    credentialValid: false,
    bootstrapError: '',
    bootstrapped: false,
    bootstrapPending: null as Promise<void> | null,
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token) && state.credentialValid && state.authMode !== 'none',
  },
  actions: {
    /** 启动时执行一次：探测后端是否要求登录，并校验本地 token 有效性 */
    async ensureBootstrapped(): Promise<void> {
      if (this.bootstrapped) return
      if (!this.bootstrapPending) this.bootstrapPending = this.bootstrapAuth()
      try {
        await this.bootstrapPending
      } finally {
        this.bootstrapPending = null
      }
    },
    async bootstrapAuth(): Promise<void> {
      this.bootstrapError = ''
      this.credentialValid = false
      this.user = null
      try {
        const { data } = await api.get<HealthAuthInfo>('/health')
        const mode = data.auth_mode ?? (typeof data.auth_required === 'boolean' ? data.auth_required ? 'jwt' : 'none' : null)
        if (!mode || !['none', 'token', 'jwt'].includes(mode)
          || (typeof data.auth_required === 'boolean' && data.auth_required !== (mode !== 'none'))) {
          throw new Error('认证元信息不完整')
        }
        this.authMode = mode
        this.authRequired = mode !== 'none'
      } catch {
        this.authMode = 'unknown'
        this.authRequired = true
        this.bootstrapError = '无法获取认证配置，请检查服务后重试'
        this.bootstrapped = true
        return
      }
      if (this.token && this.authMode === 'jwt') {
        try {
          const { data } = await api.get<AuthUser>('/auth/me')
          this.user = data
          this.credentialValid = true
        } catch {
          this.logout()
        }
      } else if (this.token && this.authMode === 'token') {
        try {
          const { data } = await api.get<{ authenticated: boolean }>('/auth/check')
          this.credentialValid = data.authenticated === true
        } catch {
          this.bootstrapError = '静态凭证验证未通过，请更换凭证或联系运维'
        }
      }
      this.bootstrapped = true
    },
    async retryBootstrap(): Promise<void> {
      this.bootstrapped = false
      await this.ensureBootstrapped()
    },
    async login(username: string, password: string): Promise<void> {
      if (this.authMode === 'token' || this.authMode === 'none') throw new Error('当前模式不提供用户名密码登录')
      const form = new URLSearchParams()
      form.append('username', username)
      form.append('password', password)
      const { data } = await api.post<TokenOut>('/auth/token', form)
      this.token = data.access_token
      this.user = data.user
      this.authMode = 'jwt'
      this.authRequired = true
      this.credentialValid = true
      this.bootstrapped = true
      setStoredToken(data.access_token)
    },
    async useStaticToken(value: string): Promise<void> {
      if (this.authMode !== 'token') throw new Error('当前服务不是静态凭证模式')
      const candidate = value.trim()
      if (!candidate) throw new Error('请输入运维提供的静态凭证')
      const { data } = await api.get<{ authenticated: boolean }>('/auth/check', {
        headers: { Authorization: `Bearer ${candidate}` },
      })
      if (!data.authenticated) throw new Error('静态凭证未通过验证')
      this.token = candidate
      this.user = null
      this.credentialValid = true
      this.bootstrapError = ''
      setStoredToken(candidate)
    },
    logout(): void {
      this.token = null
      this.user = null
      this.credentialValid = false
      setStoredToken(null)
    },
  },
})
