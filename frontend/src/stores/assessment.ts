import { defineStore } from 'pinia'

import { api } from '../api/client'
import { extractError } from '../utils/errors'
import {
  loadSubmission, newSubmission, saveSubmission, submissionError,
  type SubmissionAttempt, type SubmissionPayload,
} from '../utils/submission'
import type {
  Assessment,
  JobOut,
  KnowledgeDocument,
  KnowledgeDocumentDetail,
} from '../types'

export const useAssessmentStore = defineStore('assessment', {
  state: () => ({
    loading: false,
    error: '',
    /** 异步模式下正在轮询的研判任务（用于展示进度步骤） */
    activeJob: null as JobOut | null,
    submission: loadSubmission() as SubmissionAttempt | null,
    submissionPayload: null as SubmissionPayload | null,
    submissionBusy: false,
  }),
  getters: {
    hasPendingSubmission: (state): boolean => Boolean(state.submission && state.submission.phase !== 'resolved'),
    canRetrySubmission: (state): boolean => Boolean(
      state.submission && state.submission.phase !== 'failed' && state.submissionPayload,
    ),
  },
  actions: {
    async create(description: string, files: File[]): Promise<Assessment> {
      if (this.submissionBusy || this.hasPendingSubmission) {
        throw new Error('已有尚未确认的提交，请先查询本次提交或明确新建研判')
      }
      this.activeJob = null
      this.submissionPayload = { description, files: [...files] }
      this.setSubmission(newSubmission())
      return this.runSubmission(() => this.postSubmission(), true)
    },
    setSubmission(attempt: SubmissionAttempt | null): void {
      this.submission = attempt
      saveSubmission(attempt)
    },
    startNewSubmission(): void {
      if (this.submissionBusy) throw new Error('当前请求尚未结束')
      this.setSubmission(null)
      this.submissionPayload = null
      this.activeJob = null
      this.error = ''
    },
    async runSubmission(operation: () => Promise<Assessment>, newAttempt = false): Promise<Assessment> {
      if (this.submissionBusy) throw new Error('当前请求尚未结束')
      this.submissionBusy = true
      this.loading = true
      this.error = ''
      try {
        return await operation()
      } catch (err) {
        const { status, assessmentId } = submissionError(err)
        if (assessmentId && this.submission) {
          this.setSubmission({ ...this.submission, assessmentId, phase: status === 502 ? 'failed' : 'pending' })
        } else if (newAttempt && status && [400, 401, 403, 413, 415, 422].includes(status)
          && !this.submission?.assessmentId) {
          // A definite pre-acceptance rejection can be corrected with a new key.
          this.setSubmission(null)
          this.submissionPayload = null
        }
        this.error = extractError(err)
        throw err
      } finally {
        this.submissionBusy = false
        this.loading = false
      }
    },
    async postSubmission(): Promise<Assessment> {
      if (!this.submission || !this.submissionPayload) throw new Error('原照片未保留，请先查询原提交或明确新建研判')
      const form = new FormData()
      form.append('description', this.submissionPayload.description)
      for (const file of this.submissionPayload.files) form.append('files', file)
      const { data } = await api.post<Assessment | JobOut>('/assessments', form, {
        headers: { 'Idempotency-Key': this.submission.key },
      })
      return this.acceptSubmission(data)
    },
    async retryCreate(): Promise<Assessment> {
      if (!this.submission) throw new Error('没有可恢复的提交')
      return this.runSubmission(async () => {
        let data: Assessment | JobOut
        try {
          const result = await api.get<Assessment | JobOut>(`/assessment-submissions/${this.submission!.key}`)
          data = result.data
        } catch (err) {
          if (submissionError(err).status === 404) return this.postSubmission()
          throw err // 查询不确定时不盲目重发。
        }
        return this.acceptSubmission(data)
      })
    },
    async recoverCreate(): Promise<Assessment> {
      if (!this.submission) throw new Error('没有可恢复的提交')
      return this.runSubmission(async () => {
        const { data } = await api.get<Assessment | JobOut>(`/assessment-submissions/${this.submission!.key}`)
        return this.acceptSubmission(data)
      })
    },
    async acceptSubmission(data: Assessment | JobOut): Promise<Assessment> {
      if (!this.submission) throw new Error('提交标识已失效')
      const assessmentId = this.isJobOut(data) ? data.assessment_id : data.id
      this.setSubmission({ ...this.submission, assessmentId, phase: data.status === 'failed' ? 'failed' : 'pending' })
      let result: Assessment
      try {
        result = await this.resolveAsyncResult(data)
      } catch (err) {
        if (this.activeJob?.status === 'failed') this.setSubmission({ ...this.submission, phase: 'failed' })
        throw err
      }
      if (result.status === 'failed') {
        this.setSubmission({ ...this.submission, phase: 'failed' })
        throw new Error('本次研判已失败，原记录已保留；重新执行请明确新建研判')
      }
      if (result.status !== 'pending') {
        this.setSubmission({ ...this.submission, phase: 'resolved' })
        this.submissionPayload = null
      }
      return result
    },
    isJobOut(data: Assessment | JobOut): data is JobOut {
      return typeof data === 'object' && data !== null && 'progress_step' in data
    },
    async resolveAsyncResult(data: Assessment | JobOut): Promise<Assessment> {
      if (!this.isJobOut(data)) return data
      // 异步模式：轮询任务直至完成（每 2s，最长约 2 分钟）
      this.activeJob = data
      const maxPolls = 60
      for (let attempt = 0; attempt < maxPolls; attempt++) {
        if (this.activeJob.status === 'succeeded') break
        if (this.activeJob.status === 'failed') {
          throw new Error(this.activeJob.error || '研判任务执行失败')
        }
        await new Promise((resolve) => setTimeout(resolve, 2000))
        const { data: job } = await api.get<JobOut>(
          `/assessments/${data.assessment_id}/job`,
        )
        this.activeJob = job
      }
      if (this.activeJob.status !== 'succeeded') {
        throw new Error('研判任务超时，请稍后在历史记录中查看结果')
      }
      return await this.get(data.assessment_id)
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
        const { data } = await api.post<Assessment | JobOut>(
          `/assessments/${id}/followup`,
          { answer },
        )
        return await this.resolveAsyncResult(data)
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
    async transitionRectification(
      id: string,
      toStatus: string,
      note?: string,
    ): Promise<Assessment> {
      this.loading = true
      try {
        const { data } = await api.post<Assessment>(
          `/assessments/${id}/rectification/transition`,
          { to_status: toStatus, note },
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
