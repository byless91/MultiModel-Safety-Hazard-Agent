import { createRouter, createWebHistory } from 'vue-router'

import AssessmentDetailView from '../views/AssessmentDetailView.vue'
import EvaluationView from '../views/EvaluationView.vue'
import HistoryView from '../views/HistoryView.vue'
import HomeView from '../views/HomeView.vue'
import KnowledgeView from '../views/KnowledgeView.vue'
import LoginView from '../views/LoginView.vue'

import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/evaluation', name: 'evaluation', component: EvaluationView },
    { path: '/history', name: 'history', component: HistoryView },
    { path: '/knowledge', name: 'knowledge', component: KnowledgeView },
    { path: '/assessments/:id', name: 'assessment-detail', component: AssessmentDetailView },
    { path: '/login', name: 'login', component: LoginView },
  ],
})

// 登录守卫：后端要求鉴权（AUTH_MODE != none）且本地无有效 token 时跳登录页
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.ensureBootstrapped()
  if (to.name !== 'login' && auth.authRequired && !auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && auth.isLoggedIn) {
    return { name: 'home' }
  }
  return true
})

export default router
