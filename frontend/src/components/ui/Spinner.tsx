import styles from './Spinner.module.css'

interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg' | 'xl'
  color?: 'primary' | 'secondary' | 'white'
  className?: string
}

export default function Spinner({ size = 'md', color = 'primary', className = '' }: SpinnerProps) {
  return (
    <div className={`${styles.spinner} ${styles[size]} ${styles[color]} ${className}`}>
      <div className={styles.circle}></div>
    </div>
  )
}
