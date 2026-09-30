import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  Clock,
  CheckCircle,
  XCircle,
  AlertCircle,
  ChevronLeft,
  Download,
  FileText,
  Activity,
  Loader,
} from 'lucide-react'
import Card, { CardHeader, CardBody } from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import Spinner from '@/components/ui/Spinner'
import ProgressBar from '@/components/ui/ProgressBar'
import jobService, { JobDetail } from '@/services/jobService'
import styles from './JobDetailPage.module.css'

// Pipeline stages in order
const STAGES = [
  { key: 'document_processing', label: 'Processing Documents' },
  { key: 'analyzing', label: 'Analyzing' },
  { key: 'blueprint', label: 'Blueprint' },
  { key: 'retrieving', label: 'Retrieving' },
  { key: 'generating_sections', label: 'Generating' },
  { key: 'assembling', label: 'Assembling' },
]

function getStageStatus(stageKey: string, currentStage: string | null | undefined, jobStatus: string) {
  if (jobStatus === 'completed') return 'completed'
  if (jobStatus === 'failed') {
    const currentIdx = STAGES.findIndex(s => s.key === currentStage)
    const stageIdx = STAGES.findIndex(s => s.key === stageKey)
    if (stageIdx < currentIdx) return 'completed'
    if (stageIdx === currentIdx) return 'failed'
    return 'pending'
  }

  const currentIdx = STAGES.findIndex(s => s.key === currentStage)
  const stageIdx = STAGES.findIndex(s => s.key === stageKey)

  if (currentIdx < 0) return 'pending'
  if (stageIdx < currentIdx) return 'completed'
  if (stageIdx === currentIdx) return 'active'
  return 'pending'
}

export default function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const [job, setJob] = useState<JobDetail | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isCancelling, setIsCancelling] = useState(false)
  const [cancelError, setCancelError] = useState<string | null>(null)
  const logEndRef = useRef<HTMLDivElement>(null)

  // Initial fetch
  useEffect(() => {
    if (!jobId) return

    const fetchJob = async () => {
      try {
        const data = await jobService.getJob(jobId)
        setJob(data)
        setError(null)
      } catch (err: any) {
        console.error('Failed to fetch job:', err)
        setError(err.response?.data?.detail || 'Failed to load job details')
      } finally {
        setIsLoading(false)
      }
    }

    fetchJob()
  }, [jobId])

  // Polling
  useEffect(() => {
    if (!jobId) return
    if (!job) return

    const isActive = ['queued', 'running', 'processing'].includes(job.status)
    if (!isActive) return

    const interval = window.setInterval(async () => {
      try {
        const data = await jobService.getJob(jobId)
        setJob(data)
        setError(null)
      } catch (err: any) {
        console.error('Failed to poll job:', err)
      }
    }, 3000)

    return () => clearInterval(interval)
  }, [jobId, job?.status])

  // Auto-scroll activity log
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [job?.job_metadata])

  if (isLoading) {
    return (
      <div className={styles.loading}>
        <Spinner size="lg" />
        <p>Loading job details...</p>
      </div>
    )
  }

  if (error || !job) {
    return (
      <div className={styles.errorContainer}>
        <XCircle size={48} color="var(--hld-color-danger)" />
        <h2>Error</h2>
        <p>{error || 'Job not found'}</p>
        <Link to="/dashboard">
          <Button variant="secondary" icon={<ChevronLeft size={18} />}>
            Back to Dashboard
          </Button>
        </Link>
      </div>
    )
  }

  const isCancellable = ['queued', 'running', 'processing'].includes(job.status)
  const pipelineLog: Array<{ stage: string; label: string; percent: number; message: string; timestamp: string }> =
    job.job_metadata?.pipeline_log || []

  const handleCancelJob = async () => {
    const confirmed = window.confirm('Cancel this job?')
    if (!confirmed) return

    setCancelError(null)
    setIsCancelling(true)

    try {
      await jobService.cancelJob(job.id)
      const updated = await jobService.getJob(job.id)
      setJob(updated)
    } catch (err: any) {
      setCancelError(err.response?.data?.detail || 'Failed to cancel job')
    } finally {
      setIsCancelling(false)
    }
  }

  const getStatusIcon = () => {
    switch (job.status) {
      case 'completed': return <CheckCircle size={24} color="var(--hld-color-success)" />
      case 'failed': return <XCircle size={24} color="var(--hld-color-danger)" />
      case 'running':
      case 'processing': return <Activity size={24} color="var(--hld-color-primary)" className={styles.pulse} />
      case 'queued': return <Clock size={24} color="var(--hld-color-warning)" />
      default: return <AlertCircle size={24} color="var(--hld-text-secondary)" />
    }
  }

  const formatTime = (ts: string) => {
    const d = new Date(ts)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }

  return (
    <div className={styles.jobDetail}>
      <div className={styles.header}>
        <Link to="/dashboard" className={styles.backLink}>
          <ChevronLeft size={16} />
          Back to Dashboard
        </Link>
        <div className={styles.titleRow}>
          <h1 className={styles.title}>Job Details</h1>
          <div className={styles.statusBadge}>
            {getStatusIcon()}
            <span className={styles.statusText}>{job.status.toUpperCase()}</span>
          </div>
        </div>
        <p className={styles.jobId}>ID: {job.id}</p>
      </div>

      <div className={styles.content}>
        <div className={styles.mainCol}>
          {/* Progress Bar */}
          <Card className={styles.progressCard}>
            <CardHeader>
              <h3 className={styles.sectionTitle}>Pipeline Progress</h3>
            </CardHeader>
            <CardBody>
              <div className={styles.progressInfo}>
                <span className={styles.stageName}>
                  {pipelineLog.length > 0
                    ? pipelineLog[pipelineLog.length - 1].message
                    : job.pipeline_stage || (job.status === 'queued' ? 'Waiting in queue...' : 'Initializing...')}
                </span>
                <span className={styles.percentText}>{job.progress_percent}%</span>
              </div>
              <ProgressBar
                value={job.progress_percent}
                showPercentage={false}
                variant={job.status === 'failed' ? 'danger' : job.status === 'completed' ? 'success' : 'primary'}
              />

              {job.error_message && (
                <div className={styles.errorMessage}>
                  <AlertCircle size={18} />
                  <p>{job.error_message}</p>
                </div>
              )}
            </CardBody>
          </Card>

          {/* Stage Timeline */}
          <Card className={styles.timelineCard}>
            <CardHeader>
              <h3 className={styles.sectionTitle}>Pipeline Stages</h3>
            </CardHeader>
            <CardBody>
              <div className={styles.timeline}>
                {STAGES.map((stage, idx) => {
                  const status = getStageStatus(stage.key, job.pipeline_stage, job.status)
                  return (
                    <div key={stage.key} className={`${styles.timelineItem} ${styles[status]}`}>
                      <div className={styles.timelineConnector}>
                        <div className={styles.timelineDot}>
                          {status === 'completed' && <CheckCircle size={16} />}
                          {status === 'active' && <Loader size={16} className={styles.spin} />}
                          {status === 'failed' && <XCircle size={16} />}
                          {status === 'pending' && <div className={styles.emptyDot} />}
                        </div>
                        {idx < STAGES.length - 1 && <div className={styles.timelineLine} />}
                      </div>
                      <div className={styles.timelineContent}>
                        <span className={styles.timelineLabel}>{stage.label}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </CardBody>
          </Card>

          {/* Activity Log */}
          {pipelineLog.length > 0 && (
            <Card className={styles.logCard}>
              <CardHeader>
                <h3 className={styles.sectionTitle}>Activity Log</h3>
              </CardHeader>
              <CardBody>
                <div className={styles.logContainer}>
                  {pipelineLog.map((entry, idx) => (
                    <div key={idx} className={styles.logEntry}>
                      <span className={styles.logTime}>{formatTime(entry.timestamp)}</span>
                      <span className={styles.logMessage}>{entry.message}</span>
                    </div>
                  ))}
                  <div ref={logEndRef} />
                </div>
              </CardBody>
            </Card>
          )}

          {/* Documents */}
          <Card className={styles.detailsCard}>
            <CardHeader>
              <h3 className={styles.sectionTitle}>Documents ({job.documents.length})</h3>
            </CardHeader>
            <CardBody>
              <ul className={styles.docList}>
                {job.documents.map((doc) => (
                  <li key={doc.id} className={styles.docItem}>
                    <FileText size={20} color="var(--hld-text-secondary)" />
                    <div className={styles.docInfo}>
                      <span className={styles.docName}>{doc.original_filename}</span>
                      <span className={styles.docType}>{doc.document_type}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
        </div>

        <div className={styles.sideCol}>
          <Card className={styles.infoCard}>
            <CardHeader>
              <h3 className={styles.sectionTitle}>Job Info</h3>
            </CardHeader>
            <CardBody>
              <div className={styles.infoGrid}>
                <div className={styles.infoItem}>
                  <span className={styles.infoLabel}>Product</span>
                  <span className={styles.infoValue}>{job.product_id}</span>
                </div>
                <div className={styles.infoItem}>
                  <span className={styles.infoLabel}>Started</span>
                  <span className={styles.infoValue}>
                    {job.started_at ? new Date(job.started_at).toLocaleString() : 'Not started'}
                  </span>
                </div>
                <div className={styles.infoItem}>
                  <span className={styles.infoLabel}>Created</span>
                  <span className={styles.infoValue}>{new Date(job.created_at).toLocaleString()}</span>
                </div>
                {job.job_metadata?.duration_seconds && (
                  <div className={styles.infoItem}>
                    <span className={styles.infoLabel}>Duration</span>
                    <span className={styles.infoValue}>{Math.round(job.job_metadata.duration_seconds)}s</span>
                  </div>
                )}
              </div>
            </CardBody>
          </Card>

          {job.status === 'completed' && job.download_available && (
            <Button
              variant="primary"
              size="lg"
              className={styles.downloadBtn}
              icon={<Download size={20} />}
              onClick={() => jobService.downloadJob(job.id, `HLD_${job.product_id}.docx`)}
            >
              Download Generated HLD
            </Button>
          )}

          {isCancellable && (
            <Button
              variant="danger"
              size="lg"
              className={styles.cancelBtn}
              isLoading={isCancelling}
              onClick={handleCancelJob}
            >
              Cancel Job
            </Button>
          )}

          {cancelError && (
            <div className={styles.errorMessage}>
              <AlertCircle size={18} />
              <p>{cancelError}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
