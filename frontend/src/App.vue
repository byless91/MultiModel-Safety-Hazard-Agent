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
      </div>
    </header>
    <main>
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from './api/client'

const provider = ref('')

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

.topbar {
  background: var(--brand-dark);
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
  color: #ffffff;
  font-size: var(--fs-lg);
  font-weight: 700;
  white-space: nowrap;
}

.brand-icon {
  color: #7dd3fc;
}

.nav {
  display: flex;
  gap: var(--s-1);
  flex: 1;
}

.nav-link {
  padding: var(--s-1) var(--s-3);
  border-radius: var(--r-control);
  color: #cbd5e1;
  text-decoration: none;
  transition: background-color 0.16s ease, color 0.16s ease;
}

.nav-link:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #ffffff;
}

.nav-link.router-link-active {
  background: rgba(255, 255, 255, 0.14);
  color: #ffffff;
  font-weight: 600;
}

.mode-tag {
  flex: none;
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
