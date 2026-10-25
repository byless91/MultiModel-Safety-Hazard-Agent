import { useTheme } from '../composables/useTheme'

export type ThemeColorToken = '--success' | '--warning' | '--danger' | '--brand'

/**
 * 读取当前主题下的语义色值（供 SVG/图表等需要字符串颜色的场景）。
 * 内部引用主题 mode 建立响应依赖：切换主题后相关 computed 会重新取值。
 */
export function themeColor(token: ThemeColorToken): string {
  // eslint-disable-next-line @typescript-eslint/no-unused-expressions
  useTheme().mode.value
  return getComputedStyle(document.documentElement).getPropertyValue(token).trim()
}
