import { InputHTMLAttributes, forwardRef } from 'react'
import styles from './Input.module.css'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  helperText?: string
  leftIcon?: React.ReactNode
  rightIcon?: React.ReactNode
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, helperText, leftIcon, rightIcon, className = '', ...props }, ref) => {
    return (
      <div className={`${styles.inputWrapper} ${className}`}>
        {label && (
          <label className={styles.label} htmlFor={props.id}>
            {label}
            {props.required && <span className={styles.required}>*</span>}
          </label>
        )}

        <div className={`${styles.inputContainer} ${error ? styles.error : ''}`}>
          {leftIcon && <span className={styles.leftIcon}>{leftIcon}</span>}

          <input
            ref={ref}
            className={`${styles.input} ${leftIcon ? styles.hasLeftIcon : ''} ${
              rightIcon ? styles.hasRightIcon : ''
            }`}
            {...props}
          />

          {rightIcon && <span className={styles.rightIcon}>{rightIcon}</span>}
        </div>

        {error && <span className={styles.errorText}>{error}</span>}
        {!error && helperText && <span className={styles.helperText}>{helperText}</span>}
      </div>
    )
  }
)

Input.displayName = 'Input'

export default Input
