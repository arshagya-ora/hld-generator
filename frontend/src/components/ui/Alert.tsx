import { ReactNode } from 'react'
import { AlertCircle, CheckCircle, Info, XCircle, X } from 'lucide-react'
import styles from './Alert.module.css'

interface AlertProps {
  variant?: 'success' | 'warning' | 'danger' | 'info'
  title?: string
  children: ReactNode
  onClose?: () => void
  className?: string
}

const icons = {
  success: CheckCircle,
  warning: AlertCircle,
  danger: XCircle,
  info: Info,
}

export default function Alert({
  variant = 'info',
  title,
  children,
  onClose,
  className = '',
}: AlertProps) {
  const Icon = icons[variant]

  return (
    <div className={`${styles.alert} ${styles[variant]} ${className}`} role="alert">
      <div className={styles.icon}>
        <Icon size={20} />
      </div>

      <div className={styles.content}>
        {title && <div className={styles.title}>{title}</div>}
        <div className={styles.message}>{children}</div>
      </div>

      {onClose && (
        <button className={styles.closeButton} onClick={onClose} aria-label="Close">
          <X size={18} />
        </button>
      )}
    </div>
  )
}
