import { useNavigate } from 'react-router-dom'
import { LogOut, User } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import authService from '@/services/authService'
import Button from '@/components/ui/Button'
import styles from './Header.module.css'

export default function Header() {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)

  const handleLogout = async () => {
    await authService.logout()
    navigate('/login')
  }

  return (
    <header className={styles.header}>
      <div className={styles.container}>
        <div className={styles.brand}>
          <h1 className={styles.title}>ArchDraft</h1>
        </div>

        <div className={styles.actions}>
          <div className={styles.userInfo}>
            <User size={18} />
            <span className={styles.userName}>{user?.email || 'User'}</span>
          </div>

          <Button variant="ghost" size="sm" onClick={handleLogout} icon={<LogOut size={16} />}>
            Logout
          </Button>
        </div>
      </div>
    </header>
  )
}
