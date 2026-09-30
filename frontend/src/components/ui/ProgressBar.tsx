import styles from './ProgressBar.module.css'

interface ProgressBarProps {
  value: number // 0-100
  label?: string
  showPercentage?: boolean
  variant?: 'primary' | 'success' | 'warning' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

export default function ProgressBar({
  value,
  label,
  showPercentage = true,
  variant = 'primary',
  size = 'md',
  className = '',
}: ProgressBarProps) {
  const clampedValue = Math.min(100, Math.max(0, value))

  return (
    <div className={`${styles.progressWrapper} ${className}`}>
      {(label || showPercentage) && (
        <div className={styles.header}>
          {label && <span className={styles.label}>{label}</span>}
          {showPercentage && <span className={styles.percentage}>{clampedValue}%</span>}
        </div>
      )}

      <div className={`${styles.progressBar} ${styles[size]}`}>
        <div
          className={`${styles.progressFill} ${styles[variant]}`}
          style={{ width: `${clampedValue}%` }}
        >
          {size === 'lg' && showPercentage && (
            <span className={styles.innerText}>{clampedValue}%</span>
          )}
        </div>
      </div>
    </div>
  )
}
