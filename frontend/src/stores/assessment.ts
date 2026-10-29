import { defineStore } from 'pinia'

import { api } from '../api/client'
import { extractError } from '../utils/errors'
import { waitForPoll, type TaskOptions } from '../utils/jobs'
import {
  loadSubmission, newSubmission, saveSubmission, submissionError,
  type SubmissionAttempt, type SubmissionPayload,
} from '../utils/submission'
import type {
  Assessment,
  JobOut,
  KnowledgeDocument,
  KnowledgeDocumentDetail,
  ReviewRequest,
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
    reviewPending: {} as Record<string, boolean>,
  }),
  getters: {
    hasPendingSubmission: (state): boolean => Boolean(state.submission && state.submission.phase !== 'resolved'),
    canRetrySubmission: (state): boolean => Boolean(
      state.submission && state.submission.phase !== 'failed' && state.submissionPayload,
    ),
  },
  actions: {
    async create(description: string, files: File[], options?: TaskOptions): Promise<Assessment> {
      if (this.submissionBusy || this.hasPendingSubmission) {
        throw new Error('已有尚未确认的提交，请先查询本次提交或明确新建研判')
      }
      this.activeJob = null
      this.submissionPayload = { description, files: [...files] }
      this.setSubmission(newSubmission())
      return this.runSubmission(() => this.postSubmission(options), true)
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
    async postSubmission(options?: TaskOptions): Promise<Assessment> {
      if (!this.submission || !this.submissionPayload) throw new Error('原照片未保留，请先查询原提交或明确新建研判')
      const form = new FormData()
      form.append('description', this.submissionPayload.description)
      for (const file of this.submissionPayload.files) form.append('files', file)
      const { data } = await api.post<Assessment | JobOut>('/assessments', form, {
        headers: { 'Idempotency-Key': this.submission.key },
        ...(options?.signal ? { signal: options.signal } : {}),
      })
      return this.acceptSubmission(data, options)
    },
    async retryCreate(options?: TaskOptions): Promise<Assessment> {
      if (!this.submission) throw new Error('没有可恢复的提交')
      return this.runSubmission(async () => {
        let data: Assessment | JobOut
        try {
          const result = await api.get<Assessment | JobOut>(`/assessment-submissions/${this.submission!.key}`)
          data = result.data
        } catch (err) {
          if (submissionError(err).status === 404) return this.postSubmission(options)
          throw err // 查询不确定时不盲目重发。
        }
        return this.acceptSubmission(data, options)
      })
    },
    async recoverCreate(options?: TaskOptions): Promise<Assessment> {
      if (!this.submission) throw new Error('没有可恢复的提交')
      return this.runSubmission(async () => {
        const { data } = await api.get<Assessment | JobOut>(`/assessment-submissions/${this.submission!.key}`)
        return this.acceptSubmission(data, options)
      })
    },
    async acceptSubmission(data: Assessment | JobOut, options?: TaskOptions): Promise<Assessment> {
      if (!this.submission) throw new Error('提交标识已失效')
      const assessmentId = this.isJobOut(data) ? data.assessment_id : data.id
      this.setSubmission({ ...this.submission, assessmentId, phase: data.status === 'failed' ? 'failed' : 'pending' })
      let result: Assessment
      try {
        result = await this.resolveAsyncResult(data, options)
      } catch (err) {
        if (this.activeJob?.assessment_id === assessmentId && this.activeJob.status === 'failed') {
          this.setSubmission({ ...this.submission, phase: 'failed' })
        }
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
    finishSubmission(result: Assessment): void {
      if (!this.submission || this.submission.assessmentId !== result.id || this.submission.phase === 'resolved') return
      if (result.status === 'failed') this.setSubmission({ ...this.submission, phase: 'failed' })
      else if (!['pending', 'processing'].includes(result.status)) {
        this.setSubmission({ ...this.submission, phase: 'resolved' })
        this.submissionPayload = null
      }
    },
    isJobOut(data: Assessment | JobOut): data is JobOut {
      return typeof data === 'object' && data !== null && 'progress_step' in data
    },
    async resolveAsyncResult(data: Assessment | JobOut, options?: TaskOptions): Promise<Assessment> {
      if (!this.isJobOut(data)) return data
      // 兼容既有调用；页面使用 wait:false，并以独立会话恢复/停止轮询。
      this.activeJob = data
      if (options?.wait === false) return this.get(data.assessment_id, options.signal)
      let current = data
      const maxPolls = 60
      for (let attempt = 0; attempt < maxPolls; attempt++) {
        if (current.status === 'succeeded') break
        if (current.status === 'failed') {
          throw new Error(current.error || '研判任务执行失败')
        }
        await waitForPoll(2000, options?.signal)
        const { data: job } = await api.get<JobOut>(`/assessments/${data.assessment_id}/job`,
          options?.signal ? { signal: options.signal } : undefined)
        if (job.assessment_id !== data.assessment_id) throw new Error('任务记录不匹配，请重新查询')
        current = job
        this.activeJob = job
      }
      if (current.status !== 'succeeded') {
        throw new Error('本地等待已结束，服务端任务可能仍在执行，请从记录入口继续查询')
      }
      return await this.get(data.assessment_id, options?.signal)
    },
    async get(id: string, signal?: AbortSignal): Promise<Assessment> {
      this.loading = true
      try {
        const { data } = await api.get<Assessment>(`/assessments/${id}`, signal ? { signal } : undefined)
        return data
      } catch (err) {
        this.error = extractError(err)
        throw err
      } finally {
        this.loading = false
      }
    },
    async followup(id: string, answer: string, options?: TaskOptions): Promise<Assessment> {
      this.loading = true
      try {
        const { data } = options?.signal
          ? await api.post<Assessment | JobOut>(`/assessments/${id}/followup`, { answer }, { signal: options.signal })
          : await api.post<Assessment | JobOut>(`/assessments/${id}/followup`, { answer })
        return await this.resolveAsyncResult(data, options)
      } catch (err) {
        this.error = extractError(err)
        throw err
      } finally {
        this.loading = false
      }
    },
    async confirm(id: string, payload: ReviewRequest): Promise<Assessment> {
      if (this.reviewPending[id]) throw new Error('这条研判正在保存复核结果，请等待完成')
      this.reviewPending[id] = true
      this.loading = true
      this.error = ''
      try {
        const { data } = await api.post<Assessment>(`/assessments/${id}/confirm`, payload)
        return data
      } catch (err) {
        this.error = extractError(err)
        throw err
      } finally {
        delete this.reviewPending[id]
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
