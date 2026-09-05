import { defineStore } from 'pinia'

import { api } from '../api/client'
import type {
  Assessment,
  KnowledgeDocument,
  KnowledgeDocumentDetail,
} from '../types'

export const useAssessmentStore = defineStore('assessment', {
  state: () => ({
    loading: false,
    error: '',
  }),
  actions: {
    async create(description: string, files: File[]): Promise<Assessment> {
      this.loading = true
      this.error = ''
      try {
        const form = new FormData()
        form.append('description', description)
        for (const file of files) {
          form.append('files', file)
        }
        const { data } = await api.post<Assessment>('/assessments', form)
        return data
      } catch (err) {
        this.error = extractError(err)
        throw err
      } finally {
        this.loading = false
      }
    },
    async get(id: string): Promise<Assessment> {
      this.loading = true
      try {
        const { data } = await api.get<Assessment>(`/assessments/${id}`)
        return data
      } catch (err) {
        this.error = extractError(err)
        throw err
      } finally {
        this.loading = false
      }
    },
    async followup(id: string, answer: string): Promise<Assessment> {
      this.loading = true
      try {
        const { data } = await api.post<Assessment>(`/assessments/${id}/followup`, { answer })
        return data
      } catch (err) {
        this.error = extractError(err)
        throw err
      } finally {
        this.loading = false
      }
    },
    async confirm(id: string, confirmed: boolean, edits: Record<string, unknown> = {}): Promise<Assessment> {
      this.loading = true
      try {
        const { data } = await api.post<Assessment>(`/assessments/${id}/confirm`, { confirmed, edits })
        return data
      } catch (err) {
        this.error = extractError(err)
        throw err
      } finally {
        this.loading = false
      }
    },
    async list(status?: string): Promise<Assessment[]> {
      this.loading = true
      try {
        const { data } = await api.get<Assessment[]>('/assessments', {
          params: status ? { status } : undefined,
        })
        return data
      } catch (err) {
        this.error = extractError(err)
        throw err
      } finally {
        this.loading = false
      }
    },
    async downloadReport(id: string): Promise<{ filename: string; content: string }> {
      const { data } = await api.get(`/assessments/${id}/export`)
      return data
    },
    async submitRectification(
      id: string,
      files: File[],
      note: string,
    ): Promise<Assessment> {
      this.loading = true
      try {
        const form = new FormData()
        form.append('note', note)
        for (const file of files) {
          form.append('files', file)
        }
        const { data } = await api.post<Assessment>(
          `/assessments/${id}/rectification`,
          form,
        )
        return data
      } catch (err) {
        this.error = extractError(err)
        throw err
      } finally {
        this.loading = false
      }
    },
    async confirmRectification(
      id: string,
      resolved: boolean,
      note?: string,
    ): Promise<Assessment> {
      this.loading = true
      try {
        const { data } = await api.post<Assessment>(
          `/assessments/${id}/rectification/confirm`,
          { resolved, note },
        )
        return data
      } catch (err) {
        this.error = extractError(err)
        throw err
      } finally {
        this.loading = false
      }
    },
    async compareRectification(id: string): Promise<Assessment> {
      this.loading = true
      try {
        const { data } = await api.post<Assessment>(
          `/assessments/${id}/rectification/compare`,
        )
        return data
      } catch (err) {
        this.error = extractError(err)
        throw err
      } finally {
        this.loading = false
      }
    },
    async uploadDocument(
      file: File,
      title: string,
      source: string,
    ): Promise<KnowledgeDocument> {
      this.loading = true
      try {
        const form = new FormData()
        form.append('file', file)
        form.append('title', title)
        form.append('source', source)
        const { data } = await api.post<KnowledgeDocument>(
          '/knowledge/documents',
          form,
        )
        return data
      } catch (err) {
        this.error = extractError(err)
        throw err
      } finally {
        this.loading = false
      }
    },
    async listDocuments(): Promise<KnowledgeDocument[]> {
      const { data } = await api.get<KnowledgeDocument[]>('/knowledge/documents')
      return data
    },
    async getDocument(id: string): Promise<KnowledgeDocumentDetail> {
      const { data } = await api.get<KnowledgeDocumentDetail>(
        `/knowledge/documents/${id}`,
      )
      return data
    },
    async deleteDocument(id: string): Promise<void> {
      await api.delete(`/knowledge/documents/${id}`)
    },
    async rebuildKnowledge(): Promise<{
      chunks: number
      records: number
      embedding_fallback: boolean
    }> {
      this.loading = true
      try {
        const { data } = await api.post('/knowledge/rebuild')
        return data
      } finally {
        this.loading = false
      }
    },
  },
})

function extractError(err: unknown): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    return anyErr.response?.data?.detail || anyErr.message || '请求失败'
  }
  return String(err)
}
