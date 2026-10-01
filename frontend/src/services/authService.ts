import api from './api'
import { useAuthStore } from '@/stores/authStore'

export interface RegisterRequest {
  email: string
  password: string
  full_name?: string
  tenant_name: string
}

export interface LoginRequest {
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface UserResponse {
  id: string
  tenant_id: string
  email: string
  full_name?: string
  role: string
  is_active: boolean
  created_at: string
  last_login_at?: string
}

class AuthService {
  async register(data: RegisterRequest): Promise<UserResponse> {
    const response = await api.post<UserResponse>('/auth/register', data)
    return response.data
  }

  async login(data: LoginRequest): Promise<void> {
    const response = await api.post<TokenResponse>('/auth/login', data)
    const { access_token, refresh_token } = response.data

    // Store tokens
    useAuthStore.getState().setTokens(access_token, refresh_token)

    // Fetch user info
    await this.getCurrentUser()
  }

  async getCurrentUser(): Promise<UserResponse> {
    const response = await api.get<UserResponse>('/auth/me')
    const user = response.data

    // Store user
    useAuthStore.getState().setUser({
      id: user.id,
      email: user.email,
      full_name: user.full_name,
      role: user.role,
      tenant_id: user.tenant_id,
    })

    return user
  }

  async logout(): Promise<void> {
    try {
      await api.post('/auth/logout')
    } catch (error) {
      console.error('Logout error:', error)
    } finally {
      useAuthStore.getState().logout()
    }
  }

  async refreshToken(refreshToken: string): Promise<TokenResponse> {
    const response = await api.post<TokenResponse>('/auth/refresh', {
      refresh_token: refreshToken,
    })
    return response.data
  }
}

export default new AuthService()
