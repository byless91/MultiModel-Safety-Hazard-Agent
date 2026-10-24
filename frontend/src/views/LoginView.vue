<template>
  <div class="login-page">
    <el-card class="login-card">
      <div class="login-head">
        <el-icon class="login-icon"><Aim /></el-icon>
        <h2>基层安全隐患智能研判</h2>
        <p class="login-sub">请使用账号登录后继续</p>
      </div>
      <el-form label-position="top" @submit.prevent="onLogin">
        <el-form-item label="用户名">
          <el-input
            v-model="username"
            placeholder="请输入用户名"
            size="large"
            autocomplete="username"
          />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="password"
            type="password"
            placeholder="请输入密码"
            size="large"
            show-password
            autocomplete="current-password"
            @keyup.enter="onLogin"
          />
        </el-form-item>
        <el-button
          type="primary"
          class="login-btn"
          size="large"
          :loading="loading"
          :disabled="!username.trim() || !password"
          @click="onLogin"
        >
          登 录
        </el-button>
      </el-form>
      <el-alert
        v-if="error"
        class="login-error"
        :title="error"
        type="error"
        :closable="false"
        show-icon
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { Aim } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function onLogin() {
  if (!username.value.trim() || !password.value) return
  loading.value = true
  error.value = ''
  try {
    await auth.login(username.value.trim(), password.value)
    ElMessage.success('登录成功')
    const redirect = route.query.redirect
    router.push(typeof redirect === 'string' && redirect ? redirect : '/')
  } catch (err) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    error.value = anyErr.response?.data?.detail || anyErr.message || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 64px);
  padding: var(--s-4);
}

.login-card {
  width: 380px;
  max-width: 100%;
}

.login-head {
  text-align: center;
  margin-bottom: var(--s-4);
}

.login-icon {
  font-size: 32px;
  color: var(--brand-primary, #2563eb);
}

.login-head h2 {
  margin: var(--s-2) 0 var(--s-1);
  font-size: var(--fs-lg);
}

.login-sub {
  color: var(--text-secondary, #64748b);
  font-size: var(--fs-sm);
  margin: 0;
}

.login-btn {
  width: 100%;
  margin-top: var(--s-2);
}

.login-error {
  margin-top: var(--s-3);
}
</style>
