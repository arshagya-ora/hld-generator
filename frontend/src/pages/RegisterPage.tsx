import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Mail, Lock, User, Building } from 'lucide-react'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import Card from '@/components/ui/Card'
import Alert from '@/components/ui/Alert'
import authService from '@/services/authService'
import styles from './RegisterPage.module.css'

export default function RegisterPage() {
  const navigate = useNavigate()
  const [formData, setFormData] = useState({
    email: '',
    password: '',
    confirmPassword: '',
    full_name: '',
    tenant_name: '',
  })
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData((prev) => ({
      ...prev,
      [e.target.name]: e.target.value,
    }))
  }

  const validateForm = () => {
    if (!formData.email || !formData.password || !formData.tenant_name) {
      setError('Please fill in all required fields')
      return false
    }

    if (formData.password.length < 12) {
      setError('Password must be at least 12 characters long')
      return false
    }

    if (formData.password !== formData.confirmPassword) {
      setError('Passwords do not match')
      return false
    }

    // Check password complexity
    const hasUpperCase = /[A-Z]/.test(formData.password)
    const hasLowerCase = /[a-z]/.test(formData.password)
    const hasNumber = /\d/.test(formData.password)
    const hasSpecial = /[!@#$%^&*()_+\-=[\]{}|;:,.<>?]/.test(formData.password)

    if (!hasUpperCase || !hasLowerCase || !hasNumber || !hasSpecial) {
      setError(
        'Password must contain uppercase, lowercase, number, and special character'
      )
      return false
    }

    return true
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!validateForm()) {
      return
    }

    setIsLoading(true)

    try {
      await authService.register({
        email: formData.email,
        password: formData.password,
        full_name: formData.full_name || undefined,
        tenant_name: formData.tenant_name,
      })

      setSuccess(true)

      // Auto-login after successful registration
      setTimeout(async () => {
        await authService.login({
          email: formData.email,
          password: formData.password,
        })
        navigate('/dashboard')
      }, 1500)
    } catch (err: any) {
      console.error('Registration error:', err)
      setError(
        err.response?.data?.detail || 'Registration failed. Please try again.'
      )
    } finally {
      setIsLoading(false)
    }
  }

  if (success) {
    return (
      <div className={styles.registerPage}>
        <div className={styles.container}>
          <Card className={styles.successCard}>
            <Alert variant="success" title="Account Created!">
              Your account has been successfully created. Redirecting to dashboard...
            </Alert>
          </Card>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.registerPage}>
      <div className={styles.container}>
        <div className={styles.header}>
          <h1 className={styles.title}>ArchDraft</h1>
          <p className={styles.subtitle}>Create your account</p>
        </div>

        <Card className={styles.card}>
          <form onSubmit={handleSubmit} className={styles.form}>
            {error && (
              <Alert variant="danger" onClose={() => setError('')}>
                {error}
              </Alert>
            )}

            <Input
              type="text"
              name="tenant_name"
              label="Organization Name"
              placeholder="Your Company Name"
              value={formData.tenant_name}
              onChange={handleChange}
              leftIcon={<Building size={18} />}
              required
              autoFocus
            />

            <Input
              type="text"
              name="full_name"
              label="Full Name"
              placeholder="John Doe"
              value={formData.full_name}
              onChange={handleChange}
              leftIcon={<User size={18} />}
              helperText="Optional"
            />

            <Input
              type="email"
              name="email"
              label="Email Address"
              placeholder="you@example.com"
              value={formData.email}
              onChange={handleChange}
              leftIcon={<Mail size={18} />}
              required
              autoComplete="email"
            />

            <Input
              type="password"
              name="password"
              label="Password"
              placeholder="Min. 12 characters"
              value={formData.password}
              onChange={handleChange}
              leftIcon={<Lock size={18} />}
              required
              autoComplete="new-password"
              helperText="Must contain uppercase, lowercase, number, and special character"
            />

            <Input
              type="password"
              name="confirmPassword"
              label="Confirm Password"
              placeholder="Re-enter your password"
              value={formData.confirmPassword}
              onChange={handleChange}
              leftIcon={<Lock size={18} />}
              required
              autoComplete="new-password"
            />

            <Button
              type="submit"
              variant="primary"
              size="lg"
              isLoading={isLoading}
              className={styles.submitButton}
            >
              Create Account
            </Button>

            <div className={styles.footer}>
              <p className={styles.footerText}>
                Already have an account?{' '}
                <Link to="/login" className={styles.link}>
                  Sign in
                </Link>
              </p>
            </div>
          </form>
        </Card>

      </div>
    </div>
  )
}
