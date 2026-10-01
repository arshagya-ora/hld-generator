import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Briefcase, Plus } from 'lucide-react'
import styles from './Sidebar.module.css'

const navItems = [
  {
    to: '/dashboard',
    icon: LayoutDashboard,
    label: 'Dashboard',
  },
  {
    to: '/jobs',
    icon: Briefcase,
    label: 'Jobs',
  },
  {
    to: '/jobs/new',
    icon: Plus,
    label: 'Create Job',
    primary: true,
  },
]

export default function Sidebar() {
  return (
    <aside className={styles.sidebar}>
      <nav className={styles.nav}>
        {navItems.map((item) => {
          const Icon = item.icon
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `${styles.navItem} ${isActive ? styles.active : ''} ${
                  item.primary ? styles.primary : ''
                }`
              }
            >
              <Icon size={20} />
              <span>{item.label}</span>
            </NavLink>
          )
        })}
      </nav>
    </aside>
  )
}
