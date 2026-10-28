import { flushPromises, shallowMount } from '@vue/test-utils'
import { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { push, route } = vi.hoisted(() => ({ push: vi.fn(), route: { query: {} as Record<string, string> } }))
vi.mock('vue-router', async (original) => ({ ...await original<object>(), useRouter: () => ({ push }), useRoute: () => route }))

import { api, getStoredToken, setStoredToken } from '../../frontend/src/api/client'
import { useAuthStore } from '../../frontend/src/stores/auth'
import type { AuthMode } from '../../frontend/src/types'
import LoginView from '../../frontend/src/views/LoginView.vue'

const USER = { id: 'user-1', username: 'admin', role: 'admin' }
let calls: { url: string; authorization: unknown }[]
let mode: AuthMode
let failHealth: boolean

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  setActivePinia(createPinia())
  window.history.replaceState(null, '', '/login')
  push.mockReset()
  route.query = {}
  calls = []
  mode = 'none'
  failHealth = false
  api.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
    const authorization = config.headers.get('Authorization')
    calls.push({ url: config.url!, authorization })
    let data: unknown = {}
    let status = 200
    if (config.url === '/health') {
      status = failHealth ? 503 : 200
      data = { auth_mode: mode, auth_required: mode !== 'none' }
    } else if (config.url === '/auth/me') {
      status = authorization === 'Bearer valid-jwt' ? 200 : 401
      data = USER
    } else if (config.url === '/auth/check') {
      status = authorization === 'Bearer service-token' ? 200 : 401
      data = { authenticated: status === 200, auth_mode: mode }
    } else if (config.url === '/auth/token') {
      data = { access_token: 'valid-jwt', token_type: 'bearer', user: USER }
    } else if (config.url === '/denied') {
      status = 401
    }
    const response: AxiosResponse = { config, status, statusText: String(status), data, headers: {} }
    if (status >= 400) throw new AxiosError('test rejection', 'ERR_BAD_REQUEST', config, undefined, response)
    return response
  }
})

async function bootstrap(value: AuthMode, token?: string) {
  mode = value
  if (token) setStoredToken(token)
  const store = useAuthStore()
  await store.ensureBootstrapped()
  return store
}

describe('R5 explicit authentication modes', () => {
  it('none is explicit and does not send an old credential on protected requests', async () => {
    const store = await bootstrap('none', 'saved-static-token')
    expect(store.authRequired).toBe(false)
    expect(store.authMode).toBe('none')
    expect(store.isLoggedIn).toBe(false)
    await api.get('/assessments')
    expect(calls.at(-1)?.authorization).toBeUndefined()
    expect(calls.map((call) => call.url)).not.toContain('/auth/me')
  })

  it('token validates with auth/check instead of auth/me or password login', async () => {
    const store = await bootstrap('token', 'service-token')
    expect(store.isLoggedIn).toBe(true)
    expect(store.user).toBeNull()
    expect(calls.map((call) => call.url)).toEqual(['/health', '/auth/check'])
    await expect(store.login('admin', 'password')).rejects.toThrow('不提供用户名密码登录')
  })

  it('invalid static credentials remain available for explicit replacement without a retry loop', async () => {
    const store = await bootstrap('token', 'old-static-token')
    expect(store.isLoggedIn).toBe(false)
    expect(store.token).toBe('old-static-token')
    expect(getStoredToken()).toBe('old-static-token')
    await store.ensureBootstrapped()
    expect(calls).toHaveLength(2)
    expect(store.bootstrapError).toContain('静态凭证')
  })

  it('an explicitly supplied static candidate is not overwritten by the saved valid credential', async () => {
    const store = await bootstrap('token', 'service-token')
    await expect(store.useStaticToken('bad-candidate')).rejects.toBeDefined()
    expect(calls.at(-1)?.authorization).toBe('Bearer bad-candidate')
    expect(getStoredToken()).toBe('service-token')
    expect(store.isLoggedIn).toBe(true)
  })

  it('stores a replacement static credential only after successful verification', async () => {
    const store = await bootstrap('token', 'old-static-token')
    await store.useStaticToken('service-token')
    expect(getStoredToken()).toBe('service-token')
    expect(store.isLoggedIn).toBe(true)
    expect(store.bootstrapError).toBe('')
  })

  it('static 401 responses neither clear the credential nor call a password endpoint', async () => {
    await bootstrap('token', 'service-token')
    await expect(api.get('/denied')).rejects.toBeDefined()
    await expect(api.get('/denied')).rejects.toBeDefined()
    expect(getStoredToken()).toBe('service-token')
    expect(calls.filter((call) => call.url === '/denied')).toHaveLength(2)
    expect(calls.map((call) => call.url)).not.toContain('/auth/token')
  })

  it('jwt validates the saved user and clears only the current rejected credential', async () => {
    const store = await bootstrap('jwt', 'valid-jwt')
    expect(store.user).toEqual(USER)
    expect(store.isLoggedIn).toBe(true)
    await expect(api.get('/denied', { headers: { Authorization: 'Bearer stale-other-token' } })).rejects.toBeDefined()
    expect(getStoredToken()).toBe('valid-jwt')
    await expect(api.get('/denied')).rejects.toBeDefined()
    expect(getStoredToken()).toBeNull()
  })

  it('unknown configuration fails closed and can be explicitly retried', async () => {
    failHealth = true
    const store = await bootstrap('none', 'saved-token')
    expect(store.authMode).toBe('unknown')
    expect(store.authRequired).toBe(true)
    expect(store.isLoggedIn).toBe(false)
    expect(getStoredToken()).toBe('saved-token')
    failHealth = false
    await store.retryBootstrap()
    expect(store.authMode).toBe('none')
    expect(store.authRequired).toBe(false)
  })

  it('shares concurrent bootstraps rather than exposing a half-read mode', async () => {
    mode = 'jwt'
    const store = useAuthStore()
    await Promise.all([store.ensureBootstrapped(), store.ensureBootstrapped()])
    expect(calls.map((call) => call.url)).toEqual(['/health'])
    expect(store.authMode).toBe('jwt')
  })
})

describe('R5 mode-specific login entry', () => {
  function mountLogin() {
    return shallowMount(LoginView, { global: { stubs: {
      ElCard: { template: '<section><slot /></section>' },
      ElForm: { template: '<form><slot /></form>' },
      ElFormItem: { template: '<label><slot /></label>' },
      ElInput: { props: ['modelValue', 'placeholder', 'type'], emits: ['update:modelValue'],
        template: '<input :placeholder="placeholder" :type="type" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)">' },
      ElButton: { props: ['disabled'], emits: ['click'],
        template: '<button type="button" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
      ElAlert: { props: ['title'], template: '<p>{{ title }}</p>' }, ElIcon: true, Aim: true,
    } } })
  }

  it('none explains the local demo instead of offering account login', async () => {
    await bootstrap('none')
    const wrapper = mountLogin()
    expect(wrapper.text()).toContain('无需登录')
    expect(wrapper.findAll('input')).toHaveLength(0)
    wrapper.unmount()
  })

  it('token presents a static credential input and verifies it without password login', async () => {
    await bootstrap('token')
    const wrapper = mountLogin()
    expect(wrapper.text()).toContain('用户名密码登录不可用')
    await wrapper.find('input').setValue('service-token')
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(push).toHaveBeenCalledWith('/')
    expect(calls.map((call) => call.url)).toEqual(['/health', '/auth/check'])
    wrapper.unmount()
  })

  it('jwt presents username/password and rejects an external redirect target', async () => {
    await bootstrap('jwt')
    route.query = { redirect: '//external.invalid' }
    const wrapper = mountLogin()
    await wrapper.find('input[placeholder="请输入用户名"]').setValue('admin')
    await wrapper.find('input[placeholder="请输入密码"]').setValue('password')
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(getStoredToken()).toBe('valid-jwt')
    expect(push).toHaveBeenCalledWith('/')
    wrapper.unmount()
  })

  it('unknown mode offers configuration retry and no credential form', async () => {
    failHealth = true
    await bootstrap('none')
    const wrapper = mountLogin()
    expect(wrapper.text()).toContain('重新获取认证配置')
    expect(wrapper.findAll('input')).toHaveLength(0)
    wrapper.unmount()
  })
})
