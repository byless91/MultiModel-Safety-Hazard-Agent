import { ref } from 'vue'

export type ThemeMode = 'dark' | 'light'

const STORAGE_KEY = 'safety_hazard_theme'

const mode = ref<ThemeMode>('dark')
let initialized = false

function apply(next: ThemeMode) {
  mode.value = next
  document.documentElement.classList.toggle('dark', next === 'dark')
}

/** 无存储选择时跟随系统偏好；Solid Glass 以暗色为设计本体。 */
function systemPreference(): ThemeMode {
  return window.matchMedia('(prefers-color-scheme: light)').matches
    ? 'light'
    : 'dark'
}

/** 应用启动时调用一次（main.ts），读取持久化选择或系统偏好。 */
export function initTheme(): ThemeMode {
  if (initialized) return mode.value
  initialized = true
  const stored = localStorage.getItem(STORAGE_KEY)
  apply(stored === 'light' || stored === 'dark' ? stored : systemPreference())
  return mode.value
}

export function useTheme() {
  function toggle() {
    const next: ThemeMode = mode.value === 'dark' ? 'light' : 'dark'
    apply(next)
    localStorage.setItem(STORAGE_KEY, next)
  }

  return { mode, toggle }
}
