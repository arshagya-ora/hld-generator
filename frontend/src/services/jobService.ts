import api from './api'

export interface Job {
  id: string
  user_id: string
  product_id: string
  product_profile_file?: string
  status: string
  celery_task_id?: string
  pipeline_stage?: string
  progress_percent: number
  download_available: boolean
  output_format: string
  started_at?: string
  completed_at?: string
  error_message?: string
  created_at: string
  updated_at?: string
  document_count: number
  duration_seconds?: number
}

export interface JobDetail extends Job {
  config: Record<string, any>
  job_metadata?: Record<string, any>
  documents: Array<{
    id: string
    original_filename: string
    document_type: string
    document_label?: string
    order: number
  }>
}

export interface JobListResponse {
  jobs: Job[]
  count: number
  page: number
  page_size: number
  total_pages: number
}

export interface JobStatusResponse {
  id: string
  status: string
  pipeline_stage?: string
  progress_percent: number
  error_message?: string
}

export interface CreateJobRequest {
  product_id: string
  document_ids: string[]
  user_prompt?: string
  config?: {
    output_format?: string
    include_diagrams?: boolean
    verbosity?: string
  }
}

class JobService {
  async createJob(data: CreateJobRequest): Promise<Job> {
    const response = await api.post<Job>('/jobs', data)
    return response.data
  }

  async listJobs(
    page: number = 1,
    pageSize: number = 20,
    statusFilter?: string
  ): Promise<JobListResponse> {
    const params: any = { page, page_size: pageSize }
    if (statusFilter) {
      params.status_filter = statusFilter
    }

    const response = await api.get<JobListResponse>('/jobs', { params })
    return response.data
  }

  async getJob(jobId: string): Promise<JobDetail> {
    const response = await api.get<JobDetail>(`/jobs/${jobId}`)
    return response.data
  }

  async getJobStatus(jobId: string): Promise<JobStatusResponse> {
    const response = await api.get<JobStatusResponse>(`/jobs/${jobId}/status`)
    return response.data
  }

  async cancelJob(jobId: string): Promise<void> {
    await api.delete(`/jobs/${jobId}`)
  }

  async downloadJob(jobId: string, filename: string): Promise<void> {
    const response = await api.get(`/jobs/${jobId}/download`, {
      responseType: 'blob',
    })

    // Create download link
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  }
}

export default new JobService()
