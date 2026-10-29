import { defineStore } from 'pinia'

import { api } from '../api/client'
import type { AnalyticsOptions, AnalyticsOverview, Benchmarks } from '../types'

export interface AnalyticsFilters {
  district?: string
  category?: string
  facility?: string
  scene?: string
  start?: string
  end?: string
}

export interface BenchmarkFilters {
  facility?: string
  scene?: string
  category?: string
}

function paramsOf<T extends object>(filters: T): Record<string, string> {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => Boolean(value))) as Record<string, string>
}

export const useAnalyticsStore = defineStore('analytics', {
  state: () => ({
    options: null as AnalyticsOptions | null,
    overview: null as AnalyticsOverview | null,
    benchmarks: null as Benchmarks | null,
    loading: false,
    benchmarkLoading: false,
  }),
  actions: {
    async loadOptions(): Promise<void> {
      const { data } = await api.get<AnalyticsOptions>('/analytics/options')
      this.options = data
    },
    async loadOverview(filters: AnalyticsFilters): Promise<void> {
      this.loading = true
      try {
        const { data } = await api.get<AnalyticsOverview>('/analytics/overview', { params: paramsOf(filters) })
        this.overview = data
      } catch (err) {
        this.overview = null
        throw err
      } finally {
        this.loading = false
      }
    },
    async loadBenchmarks(filters: BenchmarkFilters): Promise<void> {
      this.benchmarkLoading = true
      try {
        const { data } = await api.get<Benchmarks>('/analytics/benchmarks', { params: paramsOf(filters) })
        this.benchmarks = data
      } catch (err) {
        this.benchmarks = null
        throw err
      } finally {
        this.benchmarkLoading = false
      }
    },
  },
})
