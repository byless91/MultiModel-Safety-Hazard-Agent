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
        </nav>
        <el-tag v-if="provider" size="small" :type="provider === 'mock' ? 'info' : 'success'">
          {{ provider === 'mock' ? 'Mock 演示模式' : '真实模型模式' }}
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
  background: #164e63;
}

.topbar-inner {
  display: flex;
  align-items: center;
  gap: 24px;
  max-width: 1200px;
  margin: 0 auto;
  padding: 12px 20px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #ffffff;
  font-weight: 700;
  white-space: nowrap;
}

.brand-icon {
  color: #7dd3fc;
}

.nav {
  display: flex;
  gap: 18px;
  flex: 1;
}

.nav-link {
  color: #cbd5e1;
  text-decoration: none;
  padding: 4px 2px;
}

.nav-link.router-link-active {
  color: #ffffff;
  font-weight: 600;
}

@media (max-width: 640px) {
  .topbar-inner {
    flex-wrap: wrap;
    gap: 10px;
  }
}
</style>
