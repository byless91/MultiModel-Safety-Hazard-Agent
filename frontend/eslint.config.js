import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import pluginVue from 'eslint-plugin-vue'

export default defineConfigWithVueTs(
  {
    ignores: ['**/dist/**', '**/node_modules/**', '**/.artifacts/**'],
  },
  pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,
  {
    rules: {
      // 视图组件沿用具名单词组合，App.vue 与既有命名习惯不受限
      'vue/multi-word-component-names': 'off',
    },
  },
)
