<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="topbar-inner">
        <div class="brand">
          <el-icon class="brand-icon"><Aim /></el-icon>
          <span>基层安全隐患智能研判</span>
        </div>
        <nav class="nav">
          <router-link to="/" class="nav-link">现场研判</router-link>
          <router-link to="/history" class="nav-link">历史记录</router-link>
          <router-link to="/knowledge" class="nav-link">知识库</router-link>
          <router-link to="/evaluation" class="nav-link">评测总览</router-link>
        </nav>
        <el-tag
          v-if="provider"
          class="mode-tag"
          size="small"
          effect="dark"
          :type="provider === 'mock' ? 'info' : 'success'"
        >
          {{ provider === 'mock' ? '演示模式' : '真实模型' }}
        </el-tag>
        <el-tooltip :content="mode === 'dark' ? '切换到亮色模式' : '切换到暗色模式'" placement="bottom">
          <button
            class="theme-toggle"
            type="button"
            :aria-label="mode === 'dark' ? '切换到亮色模式' : '切换到暗色模式'"
            @click="toggle"
          >
            <el-icon><Sunny v-if="mode === 'dark'" /><Moon v-else /></el-icon>
          </button>
        </el-tooltip>
        <template v-if="auth.isLoggedIn && auth.user">
          <el-tag class="mode-tag" size="small" type="info">
            {{ auth.user.username }}（{{ roleLabel }}）
          </el-tag>
          <el-button class="logout-btn" link size="small" @click="onLogout">退出</el-button>
        </template>
      </div>
    </header>
    <main>
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from './api/client'
import { useTheme } from './composables/useTheme'
import { useAuthStore } from './stores/auth'

const provider = ref('')
const auth = useAuthStore()
const router = useRouter()
const { mode, toggle } = useTheme()

const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  reviewer: '复核员',
  inspector: '巡查员',
}
const roleLabel = computed(() => ROLE_LABELS[auth.user?.role || ''] || auth.user?.role || '')

function onLogout() {
  auth.logout()
  router.push('/login')
}

onMounted(async () => {
  try {
    const { data } = await api.get('/health')
    provider.value = data.provider
  } catch {
    provider.value = ''
  }
})
</script>

<style scoped>
.app-shell {
  min-height: 100vh;
}

/* 顶栏：最薄的玻璃面板（法则 3），悬浮于内容之上 */
.topbar {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--sg-panel);
  border-bottom: 1px solid var(--sg-hairline);
  backdrop-filter: var(--sg-blur);
  -webkit-backdrop-filter: var(--sg-blur);
  box-shadow: inset 0 1px 0 var(--sg-rim-soft);
}

.topbar-inner {
  display: flex;
  align-items: center;
  gap: var(--s-5);
  max-width: 1080px;
  margin: 0 auto;
  padding: var(--s-3) var(--s-5);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  color: var(--topbar-fg-active);
  font-size: var(--fs-lg);
  font-weight: 700;
  white-space: nowrap;
}

.brand-icon {
  color: var(--brand, var(--brand-strong));
}

.nav {
  display: flex;
  gap: var(--s-1);
  flex: 1;
}

.nav-link {
  padding: var(--s-1) var(--s-3);
  border-radius: var(--r-control);
  color: var(--topbar-fg);
  text-decoration: none;
  transition: background-color 0.16s ease, color 0.16s ease;
}

.nav-link:hover {
  background: var(--surface-2);
  color: var(--topbar-fg-active);
}

.nav-link.router-link-active {
  background: var(--surface-3);
  color: var(--topbar-fg-active);
  font-weight: 600;
  box-shadow: inset 0 1px 0 var(--sg-rim-soft);
}

.theme-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: var(--r-control);
  background: var(--surface-2);
  color: var(--topbar-fg);
  cursor: pointer;
  box-shadow: inset 0 1px 0 var(--sg-rim-soft);
  transition: background-color 0.16s ease, color 0.16s ease;
}

.theme-toggle:hover {
  background: var(--surface-3);
  color: var(--topbar-fg-active);
}

.mode-tag {
  flex: none;
}

.logout-btn {
  color: var(--topbar-fg);
  margin-left: calc(var(--s-1) * -1);
}

.logout-btn:hover {
  color: var(--topbar-fg-active);
}

@media (max-width: 720px) {
  .topbar-inner {
    flex-wrap: wrap;
    gap: var(--s-2);
    padding: var(--s-3) var(--s-3);
  }

  .nav {
    order: 3;
    flex: 1 1 100%;
    flex-wrap: wrap;
  }
}
</style>
