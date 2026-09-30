import { Link } from 'react-router-dom'
import { Briefcase, FileText, CheckCircle, Clock, Plus } from 'lucide-react'
import Card, { CardHeader, CardBody } from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import { useAuthStore } from '@/stores/authStore'
import { useState, useEffect } from 'react'
import api from '@/services/api'
import styles from './DashboardPage.module.css'

interface Job {
  id: string
  status: string
  product_id: string
  created_at: string
}

export default function DashboardPage() {
  const user = useAuthStore((state) => state.user)
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchJobs = async () => {
      try {
        const response = await api.get('/jobs?page=1&page_size=100')
        // The backend returns { jobs: [...], count: X, ... }
        const jobsList = response.data.jobs || []
        setJobs(jobsList)
      } catch (error) {
        console.error('Failed to fetch jobs:', error)
      } finally {
        setLoading(false)
      }
    }

    fetchJobs()
  }, [])

  const stats = {
    totalJobs: jobs.length,
    runningJobs: jobs.filter(j => j.status === 'processing' || j.status === 'queued' || j.status === 'running').length,
    completedJobs: jobs.filter(j => j.status === 'completed').length,
    documents: 0, // This would need a separate API call
  }

  return (
    <div className={styles.dashboard}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Dashboard</h1>
          <p className={styles.subtitle}>
            Welcome back, {user?.full_name || user?.email || 'User'}!
          </p>
        </div>

        <Link to="/jobs/new">
          <Button variant="primary" icon={<Plus size={18} />}>
            Create New Job
          </Button>
        </Link>
      </div>

      <div className={styles.statsGrid}>
        <Card className={styles.statCard} hover>
          <div className={styles.statIcon} style={{ backgroundColor: 'rgba(199, 70, 52, 0.1)' }}>
            <Briefcase size={24} color="var(--hld-color-primary)" />
          </div>
          <div className={styles.statContent}>
            <p className={styles.statLabel}>Total Jobs</p>
            <p className={styles.statValue}>{stats.totalJobs}</p>
          </div>
        </Card>

        <Card className={styles.statCard} hover>
          <div className={styles.statIcon} style={{ backgroundColor: 'rgba(234, 179, 8, 0.1)' }}>
            <Clock size={24} color="var(--hld-color-warning)" />
          </div>
          <div className={styles.statContent}>
            <p className={styles.statLabel}>Running</p>
            <p className={styles.statValue}>{stats.runningJobs}</p>
          </div>
        </Card>

        <Card className={styles.statCard} hover>
          <div className={styles.statIcon} style={{ backgroundColor: 'rgba(22, 163, 74, 0.1)' }}>
            <CheckCircle size={24} color="var(--hld-color-success)" />
          </div>
          <div className={styles.statContent}>
            <p className={styles.statLabel}>Completed</p>
            <p className={styles.statValue}>{stats.completedJobs}</p>
          </div>
        </Card>

        <Card className={styles.statCard} hover>
          <div className={styles.statIcon} style={{ backgroundColor: 'rgba(59, 130, 246, 0.1)' }}>
            <FileText size={24} color="var(--hld-color-info)" />
          </div>
          <div className={styles.statContent}>
            <p className={styles.statLabel}>Documents</p>
            <p className={styles.statValue}>{stats.documents}</p>
          </div>
        </Card>
      </div>

      <div className={styles.content}>
        <Card>
          <CardHeader>
            <h2 className={styles.sectionTitle}>Recent Jobs</h2>
          </CardHeader>
          <CardBody>
            {loading ? (
              <div className={styles.emptyState}>
                <p>Loading jobs...</p>
              </div>
            ) : jobs.length === 0 ? (
              <div className={styles.emptyState}>
                <Briefcase size={48} color="var(--hld-text-tertiary)" />
                <p className={styles.emptyText}>No jobs yet</p>
                <p className={styles.emptySubtext}>
                  Create your first HLD generation job to get started
                </p>
                <Link to="/jobs/new">
                  <Button variant="primary" icon={<Plus size={18} />}>
                    Create Job
                  </Button>
                </Link>
              </div>
            ) : (
              <div className={styles.jobsList}>
                <table className={styles.jobsTable}>
                  <thead>
                    <tr>
                      <th>Job ID</th>
                      <th>Product</th>
                      <th>Status</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.slice(0, 5).map(job => (
                      <tr key={job.id}>
                        <td>{job.id.slice(0, 8)}...</td>
                        <td>{job.product_id}</td>
                        <td>
                          <span className={`${styles.badge} ${styles[`badge${job.status.charAt(0).toUpperCase() + job.status.slice(1)}`]}`}>
                            {job.status}
                          </span>
                        </td>
                        <td>{new Date(job.created_at).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className={styles.viewAll}>
                  <Link to="/jobs">
                    <Button variant="secondary">View All Jobs</Button>
                  </Link>
                </div>
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}
