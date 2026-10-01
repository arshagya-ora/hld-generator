import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Briefcase, Plus, Search, Activity, CheckCircle, XCircle, Clock } from 'lucide-react'
import Card, { CardBody } from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import Spinner from '@/components/ui/Spinner'
import jobService, { Job } from '@/services/jobService'
import styles from './JobsPage.module.css'

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [cancellingJobId, setCancellingJobId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const fetchJobs = async () => {
    setLoading(true)
    try {
      const response = await jobService.listJobs(1, 100, statusFilter === 'all' ? undefined : statusFilter)
      setJobs(response.jobs)
    } catch (error) {
      console.error('Failed to fetch jobs:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchJobs()
  }, [statusFilter])

  const filteredJobs = jobs.filter(job =>
    job.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
    job.product_id.toLowerCase().includes(searchTerm.toLowerCase())
  )

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed': return <CheckCircle size={16} color="var(--hld-color-success)" />
      case 'failed': return <XCircle size={16} color="var(--hld-color-danger)" />
      case 'running':
      case 'processing': return <Activity size={16} color="var(--hld-color-primary)" />
      case 'queued': return <Clock size={16} color="var(--hld-color-warning)" />
      default: return null
    }
  }

  const isCancellable = (status: string) => ['queued', 'running', 'processing'].includes(status)

  const handleCancelJob = async (jobId: string) => {
    const confirmed = window.confirm('Cancel this job?')
    if (!confirmed) return

    setActionError(null)
    setCancellingJobId(jobId)
    try {
      await jobService.cancelJob(jobId)
      await fetchJobs()
    } catch (err: any) {
      setActionError(err.response?.data?.detail || 'Failed to cancel job')
    } finally {
      setCancellingJobId(null)
    }
  }

  return (
    <div className={styles.jobsPage}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>All Jobs</h1>
          <p className={styles.subtitle}>Manage and monitor your HLD generation tasks</p>
        </div>
        <Link to="/jobs/new">
          <Button variant="primary" icon={<Plus size={18} />}>
            New Job
          </Button>
        </Link>
      </div>

      <Card className={styles.filterCard}>
        <div className={styles.filters}>
          <div className={styles.searchBox}>
            <Search size={18} className={styles.searchIcon} />
            <input
              type="text"
              placeholder="Search by Job ID or Product..."
              className={styles.searchInput}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          <div className={styles.statusFilter}>
            <span className={styles.filterLabel}>Status:</span>
            <select
              className={styles.statusSelect}
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="all">All Statuses</option>
              <option value="queued">Queued</option>
              <option value="running">Running</option>
              <option value="cancelled">Cancelled</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
            </select>
          </div>
        </div>
      </Card>

      <Card className={styles.listCard}>
        <CardBody>
          {actionError && <p className={styles.actionError}>{actionError}</p>}
          {loading ? (
            <div className={styles.loadingState}>
              <Spinner size="lg" />
              <p>Fetching jobs...</p>
            </div>
          ) : filteredJobs.length === 0 ? (
            <div className={styles.emptyState}>
              <Briefcase size={48} color="var(--hld-text-tertiary)" />
              <p>No jobs found</p>
              <Button onClick={() => fetchJobs()} variant="secondary" size="sm">Refresh</Button>
            </div>
          ) : (
            <div className={styles.tableWrapper}>
              <table className={styles.jobsTable}>
                <thead>
                  <tr>
                    <th>Job ID</th>
                    <th>Product</th>
                    <th>Status</th>
                    <th>Progress</th>
                    <th>Created At</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredJobs.map(job => (
                    <tr key={job.id}>
                      <td className={styles.idCell}>
                        <Link to={`/jobs/${job.id}`}>{job.id.slice(0, 8)}...</Link>
                      </td>
                      <td>{job.product_id}</td>
                      <td>
                        <div className={styles.statusWrapper}>
                          {getStatusIcon(job.status)}
                          <span className={`${styles.badge} ${styles[`badge${job.status.charAt(0).toUpperCase() + job.status.slice(1)}`]}`}>
                            {job.status}
                          </span>
                        </div>
                      </td>
                      <td className={styles.progressCell}>
                        <div className={styles.progressWrapper}>
                          <div className={styles.progressBarBg}>
                            <div
                              className={styles.progressBarFill}
                              style={{ width: `${job.progress_percent}%` }}
                            />
                          </div>
                          <span className={styles.progressText}>{job.progress_percent}%</span>
                        </div>
                      </td>
                      <td>{new Date(job.created_at).toLocaleString()}</td>
                      <td className={styles.actionsCell}>
                        <Link to={`/jobs/${job.id}`}>
                          <Button variant="ghost" size="sm">View Details</Button>
                        </Link>
                        {isCancellable(job.status) && (
                          <Button
                            variant="danger"
                            size="sm"
                            isLoading={cancellingJobId === job.id}
                            onClick={() => handleCancelJob(job.id)}
                          >
                            Cancel
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
