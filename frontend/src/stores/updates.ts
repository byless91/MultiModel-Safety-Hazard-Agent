import { defineStore } from 'pinia'

import { api } from '../api/client'
import type {
  KnowledgeIndustry,
  KnowledgePack,
  KnowledgePackImportResult,
  KnowledgePackStatus,
  KnowledgeSourceItem,
  TrendAlertItem,
  TrendReport,
} from '../types'

export const useUpdatesStore = defineStore('updates', {
  state: () => ({
    sources: [] as KnowledgeSourceItem[],
    trend: null as TrendReport | null,
    packStatus: null as KnowledgePackStatus | null,
    sourcesLoading: false,
    trendBusy: false,
  }),
  actions: {
    async loadSources(): Promise<void> {
      this.sourcesLoading = true
      try {
        const { data } = await api.get<KnowledgeSourceItem[]>('/knowledge/sources')
        this.sources = data
      } finally {
        this.sourcesLoading = false
      }
    },
    async addSource(payload: { name: string; url: string; industry: KnowledgeIndustry }): Promise<KnowledgeSourceItem> {
      const { data } = await api.post<KnowledgeSourceItem>('/knowledge/sources', payload)
      this.sources = [...this.sources, data]
      return data
    },
    async checkSource(id: string): Promise<KnowledgeSourceItem> {
      const { data } = await api.post<KnowledgeSourceItem>(`/knowledge/sources/${id}/check`)
      this.sources = this.sources.map(item => item.id === id ? data : item)
      return data
    },
    async acknowledgeSource(id: string): Promise<KnowledgeSourceItem> {
      const { data } = await api.post<KnowledgeSourceItem>(`/knowledge/sources/${id}/ack`)
      this.sources = this.sources.map(item => item.id === id ? data : item)
      return data
    },
    async deleteSource(id: string): Promise<void> {
      await api.delete(`/knowledge/sources/${id}`)
      this.sources = this.sources.filter(item => item.id !== id)
    },
    async loadTrend(): Promise<void> {
      const { data } = await api.get<TrendReport>('/analytics/trend-alerts')
      this.trend = data
    },
    async refreshTrend(): Promise<void> {
      this.trendBusy = true
      try {
        const { data } = await api.post<TrendReport>('/analytics/trend-alerts/refresh')
        this.trend = data
      } finally {
        this.trendBusy = false
      }
    },
    async reviewTrend(id: string, status: 'acknowledged' | 'false_positive', note: string): Promise<TrendAlertItem> {
      const { data } = await api.post<TrendAlertItem>(`/analytics/trend-alerts/${id}`, { status, note })
      if (this.trend) {
        this.trend.alerts = this.trend.alerts.map(item => item.id === id ? data : item)
        this.trend.false_positive_count = this.trend.alerts.filter(item => item.status === 'false_positive').length
      }
      return data
    },
    async loadPackStatus(): Promise<void> {
      const { data } = await api.get<KnowledgePackStatus>('/knowledge/pack/status')
      this.packStatus = data
    },
    async exportPack(): Promise<KnowledgePack> {
      const { data } = await api.get<KnowledgePack>('/knowledge/pack/export')
      return data
    },
    async importPack(pack: unknown): Promise<KnowledgePackImportResult> {
      const { data } = await api.post<KnowledgePackImportResult>('/knowledge/pack/import', pack)
      await this.loadPackStatus()
      return data
    },
  },
})
