import { create } from 'zustand'
import { loginUser } from '../lib/api'

interface AuthUser {
  email: string
  is_admin: boolean
  is_approved: boolean
}

interface AuthState {
  user: AuthUser | null
  token: string | null          // access token — 2h TTL
  refreshToken: string | null   // refresh token — 30d TTL
  initialized: boolean          // true once loadFromStorage has run

  isAuthenticated: () => boolean
  isAdmin: () => boolean

  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refreshSession: () => Promise<boolean>
  loadFromStorage: () => void
}

const BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  token: null,
  refreshToken: null,
  initialized: false,

  isAuthenticated: () => get().token !== null,
  isAdmin: () => get().user?.is_admin === true,

  // -----------------------------------------------------------------------
  // login — calls /auth/login, stores both tokens
  // -----------------------------------------------------------------------
  login: async (email, password) => {
    const data = await loginUser(email, password)

    const token        = data.access_token  as string
    const refreshToken = data.refresh_token as string
    const user: AuthUser = {
      email:       data.email,
      is_admin:    data.is_admin,
      is_approved: true,
    }

    localStorage.setItem('qcm_token',         token)
    localStorage.setItem('qcm_refresh_token', refreshToken)
    localStorage.setItem('qcm_user',          JSON.stringify(user))
    set({ token, refreshToken, user })
  },

  // -----------------------------------------------------------------------
  // logout — best-effort call to /auth/logout, then clears everything
  // -----------------------------------------------------------------------
  logout: async () => {
    const { token } = get()
    if (token) {
      try {
        await fetch(`${BASE}/auth/logout`, {
          method:  'POST',
          headers: { Authorization: `Bearer ${token}` },
        })
      } catch {
        // best effort — ignore network errors
      }
    }
    localStorage.removeItem('qcm_token')
    localStorage.removeItem('qcm_refresh_token')
    localStorage.removeItem('qcm_user')
    set({ user: null, token: null, refreshToken: null })
  },

  // -----------------------------------------------------------------------
  // refreshSession — exchanges refresh token for a new token pair.
  // Returns true if successful, false if the user must re-login.
  // -----------------------------------------------------------------------
  refreshSession: async () => {
    const { refreshToken, logout } = get()
    if (!refreshToken) {
      await logout()
      return false
    }

    try {
      const res = await fetch(`${BASE}/auth/refresh`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ refresh_token: refreshToken }),
      })

      if (!res.ok) {
        await logout()
        return false
      }

      const data = await res.json()
      const newToken        = data.access_token  as string
      const newRefreshToken = data.refresh_token as string

      localStorage.setItem('qcm_token',         newToken)
      localStorage.setItem('qcm_refresh_token', newRefreshToken)
      set({ token: newToken, refreshToken: newRefreshToken })
      return true
    } catch {
      await logout()
      return false
    }
  },

  // -----------------------------------------------------------------------
  // loadFromStorage — restores session from localStorage on app mount
  // -----------------------------------------------------------------------
  loadFromStorage: () => {
    const token        = localStorage.getItem('qcm_token')
    const refreshToken = localStorage.getItem('qcm_refresh_token')
    const userJson     = localStorage.getItem('qcm_user')

    if (token && userJson) {
      try {
        set({
          token,
          refreshToken: refreshToken ?? null,
          user: JSON.parse(userJson),
          initialized: true,
        })
        return
      } catch {
        // corrupt storage — clear it
      }
    }

    localStorage.removeItem('qcm_token')
    localStorage.removeItem('qcm_refresh_token')
    localStorage.removeItem('qcm_user')
    set({ token: null, refreshToken: null, user: null, initialized: true })
  },
}))
