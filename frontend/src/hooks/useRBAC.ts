import { useAuthStore } from '@/stores/authStore'

export type Role = 'user' | 'admin' | 'super_admin'

export type Permission =
  | 'create_job'
  | 'view_own_jobs'
  | 'manage_own_profile'
  | 'view_all_jobs'
  | 'manage_users'
  | 'view_metrics'
  | 'manage_tenant_settings'

// Mirror of backend models/user.py permission map
const ROLE_PERMISSIONS: Record<Role, Permission[] | ['*']> = {
  super_admin: ['*'],
  admin: ['view_all_jobs', 'manage_users', 'view_metrics', 'manage_tenant_settings'],
  user: ['create_job', 'view_own_jobs', 'manage_own_profile'],
}

export function hasPermission(role: Role | string | undefined, permission: Permission): boolean {
  if (!role) return false
  const perms = ROLE_PERMISSIONS[role as Role]
  if (!perms) return false
  return perms.includes('*' as never) || perms.includes(permission as never)
}

export function hasRole(userRole: string | undefined, ...allowedRoles: Role[]): boolean {
  if (!userRole) return false
  return allowedRoles.includes(userRole as Role)
}

export function isAdmin(role: string | undefined): boolean {
  return hasRole(role, 'admin', 'super_admin')
}

export function useRBAC() {
  const user = useAuthStore((state) => state.user)
  const role = user?.role as Role | undefined

  return {
    role,
    hasPermission: (permission: Permission) => hasPermission(role, permission),
    hasRole: (...allowedRoles: Role[]) => hasRole(role, ...allowedRoles),
    isAdmin: isAdmin(role),
    isSuperAdmin: role === 'super_admin',
    isUser: role === 'user',
  }
}
