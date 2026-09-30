import { ReactNode } from 'react'
import styles from './Card.module.css'

interface CardProps {
  children: ReactNode
  className?: string
  padding?: 'none' | 'sm' | 'md' | 'lg'
  shadow?: 'none' | 'sm' | 'md' | 'lg'
  hover?: boolean
}

export default function Card({
  children,
  className = '',
  padding = 'md',
  shadow = 'md',
  hover = false,
}: CardProps) {
  return (
    <div
      className={`${styles.card} ${styles[`padding-${padding}`]} ${styles[`shadow-${shadow}`]} ${
        hover ? styles.hover : ''
      } ${className}`}
    >
      {children}
    </div>
  )
}

interface CardHeaderProps {
  children: ReactNode
  className?: string
}

export function CardHeader({ children, className = '' }: CardHeaderProps) {
  return <div className={`${styles.cardHeader} ${className}`}>{children}</div>
}

interface CardBodyProps {
  children: ReactNode
  className?: string
}

export function CardBody({ children, className = '' }: CardBodyProps) {
  return <div className={`${styles.cardBody} ${className}`}>{children}</div>
}

interface CardFooterProps {
  children: ReactNode
  className?: string
}

export function CardFooter({ children, className = '' }: CardFooterProps) {
  return <div className={`${styles.cardFooter} ${className}`}>{children}</div>
}
