import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { apiMock, storage } = vi.hoisted(() => ({
  apiMock: {
    post: vi.fn(),
    get: vi.fn(),
  },
  storage: new Map<string, string>(),
}))

vi.mock('../../api/client', () => ({
  api: apiMock,
  getStoredToken: () => storage.get('token') ?? null,
  setStoredToken: (token: string | null) => {
    if (token) storage.set('token', token)
    else storage.delete('token')
  },
}))

import { useAuthStore } from '../auth'

describe('auth store（B6/WP5.4）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    storage.clear()
  })

  it('登录成功保存 token 与用户信息', async () => {
    apiMock.post.mockResolvedValueOnce({
      data: {
        access_token: 'jwt-abc',
        token_type: 'bearer',
        user: { id: 'u1', username: 'admin', role: 'admin' },
      },
    })
    const store = useAuthStore()
    await store.login('admin', 'password-123')

    expect(store.token).toBe('jwt-abc')
    expect(store.user?.username).toBe('admin')
    expect(store.isLoggedIn).toBe(true)
    expect(storage.get('token')).toBe('jwt-abc')
    expect(apiMock.post).toHaveBeenCalledWith(
      '/auth/token',
      expect.any(URLSearchParams),
    )
    const form = apiMock.post.mock.calls[0][1] as URLSearchParams
    expect(form.get('username')).toBe('admin')
  })

  it('登出清空 token 与用户', () => {
    const store = useAuthStore()
    store.token = 'jwt-abc'
    store.user = { id: 'u1', username: 'admin', role: 'admin' }
    storage.set('token', 'jwt-abc')

    store.logout()
    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
    expect(store.isLoggedIn).toBe(false)
    expect(storage.has('token')).toBe(false)
  })

  it('ensureBootstrapped：后端要求鉴权且本地 token 失效时登出', async () => {
    storage.set('token', 'expired-token')
    apiMock.get
      .mockResolvedValueOnce({ data: { auth_required: true } }) // /health
      .mockRejectedValueOnce(new Error('401')) // /auth/me
    const store = useAuthStore()
    await store.ensureBootstrapped()

    expect(store.authRequired).toBe(true)
    expect(store.token).toBeNull()
    expect(store.isLoggedIn).toBe(false)
  })

  it('ensureBootstrapped：后端不要求鉴权时保持无登录态可用', async () => {
    apiMock.get.mockResolvedValueOnce({ data: { auth_required: false } })
    const store = useAuthStore()
    await store.ensureBootstrapped()

    expect(store.authRequired).toBe(false)
    expect(store.isLoggedIn).toBe(false)
    // 未登录时不应调用 /auth/me
    expect(apiMock.get).toHaveBeenCalledTimes(1)
  })
})
