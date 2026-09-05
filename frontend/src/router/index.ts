import { createRouter, createWebHistory } from 'vue-router'

import AssessmentDetailView from '../views/AssessmentDetailView.vue'
import HistoryView from '../views/HistoryView.vue'
import HomeView from '../views/HomeView.vue'
import KnowledgeView from '../views/KnowledgeView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/history', name: 'history', component: HistoryView },
    { path: '/knowledge', name: 'knowledge', component: KnowledgeView },
    { path: '/assessments/:id', name: 'assessment-detail', component: AssessmentDetailView },
  ],
})

export default router
