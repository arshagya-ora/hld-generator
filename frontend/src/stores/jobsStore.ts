import { create } from 'zustand'
import jobService, { Job, JobDetail } from '@/services/jobService'

interface JobsState {
  jobs: Job[]
  currentJob: JobDetail | null
  isLoading: boolean
  error: string | null
  filters: {
    status?: string
    page: number
    pageSize: number
  }
  totalPages: number

  // Actions
  fetchJobs: () => Promise<void>
  fetchJob: (jobId: string) => Promise<void>
  createJob: (productId: string, documentIds: string[], config?: any, userPrompt?: string) => Promise<Job>
  cancelJob: (jobId: string) => Promise<void>
  setFilter: (key: string, value: any) => void
  clearCurrentJob: () => void
}

export const useJobsStore = create<JobsState>((set, get) => ({
  jobs: [],
  currentJob: null,
  isLoading: false,
  error: null,
  filters: {
    page: 1,
    pageSize: 20,
  },
  totalPages: 1,

  fetchJobs: async () => {
    set({ isLoading: true, error: null })
    try {
      const { page, pageSize, status } = get().filters
      const response = await jobService.listJobs(page, pageSize, status)
      set({
        jobs: response.jobs,
        totalPages: response.total_pages,
        isLoading: false,
      })
    } catch (error: any) {
      set({
        error: error.response?.data?.detail || 'Failed to fetch jobs',
        isLoading: false,
      })
    }
  },

  fetchJob: async (jobId: string) => {
    set({ isLoading: true, error: null })
    try {
      const job = await jobService.getJob(jobId)
      set({ currentJob: job, isLoading: false })
    } catch (error: any) {
      set({
        error: error.response?.data?.detail || 'Failed to fetch job',
        isLoading: false,
      })
    }
  },

  createJob: async (productId: string, documentIds: string[], config?: any, userPrompt?: string) => {
    set({ isLoading: true, error: null })
    try {
      const job = await jobService.createJob({
        product_id: productId,
        document_ids: documentIds,
        user_prompt: userPrompt,
        config,
      })
      set({ isLoading: false })
      return job
    } catch (error: any) {
      set({
        error: error.response?.data?.detail || 'Failed to create job',
        isLoading: false,
      })
      throw error
    }
  },

  cancelJob: async (jobId: string) => {
    try {
      await jobService.cancelJob(jobId)
      // Refresh jobs list
      await get().fetchJobs()
    } catch (error: any) {
      set({
        error: error.response?.data?.detail || 'Failed to cancel job',
      })
    }
  },

  setFilter: (key: string, value: any) => {
    set((state) => ({
      filters: {
        ...state.filters,
        [key]: value,
      },
    }))
  },

  clearCurrentJob: () => {
    set({ currentJob: null })
  },
}))
