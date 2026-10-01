import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Mail, Lock } from 'lucide-react'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import Card from '@/components/ui/Card'
import Alert from '@/components/ui/Alert'
import authService from '@/services/authService'
import styles from './LoginPage.module.css'

export default function LoginPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    // Validation
    if (!email || !password) {
      setError('Please enter both email and password')
      return
    }

    setIsLoading(true)

    try {
      await authService.login({ email, password })
      navigate('/dashboard')
    } catch (err: any) {
      console.error('Login error:', err)
      setError(err.response?.data?.detail || 'Login failed. Please check your credentials.')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className={styles.loginPage}>
      <div className={styles.container}>
        <div className={styles.header}>
          <h1 className={styles.title}>ArchDraft</h1>
          <p className={styles.subtitle}>Sign in to your account</p>
        </div>

        <Card className={styles.card}>
          <form onSubmit={handleSubmit} className={styles.form}>
            {error && (
              <Alert variant="danger" onClose={() => setError('')}>
                {error}
              </Alert>
            )}

            <Input
              type="email"
              label="Email Address"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              leftIcon={<Mail size={18} />}
              required
              autoComplete="email"
              autoFocus
            />

            <Input
              type="password"
              label="Password"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              leftIcon={<Lock size={18} />}
              required
              autoComplete="current-password"
            />

            <Button type="submit" variant="primary" size="lg" isLoading={isLoading} className={styles.submitButton}>
              Sign In
            </Button>

            <div className={styles.footer}>
              <p className={styles.footerText}>
                Don't have an account?{' '}
                <Link to="/register" className={styles.link}>
                  Sign up
                </Link>
              </p>
            </div>
          </form>
        </Card>

      </div>
    </div>
  )
}
