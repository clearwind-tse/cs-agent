import React, { createContext, useContext, useState, useEffect } from 'react'
import api from '../api'
import { useToast } from './ToastContext'

interface User {
  id: number
  username: string
  nickname: string | null
  role: string
}

interface AuthContextType {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (token: string, refreshToken: string, userData: User) => void
  logout: () => void
  updateUser: (user: User) => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const { showToast } = useToast()

  useEffect(() => {
    // 页面加载时检查 token 获取当前用户
    const checkAuth = async () => {
      const token = localStorage.getItem('access_token')
      if (token) {
        try {
          const res = await api.get('/auth/me')
          setUser(res.data)
        } catch (error) {
          console.error('Failed to fetch user info:', error)
          // 可以在这里处理自动 refresh token 的逻辑，
          // 但因为 api 请求拦截器可以处理 401 刷新，先暂且如此
        }
      }
      setIsLoading(false)
    }

    checkAuth()
  }, [])

  const login = (token: string, refreshToken: string, userData: User) => {
    localStorage.setItem('access_token', token)
    localStorage.setItem('refresh_token', refreshToken)
    setUser(userData)
  }

  const logout = () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    setUser(null)
    showToast('已安全退出', 'success')
  }

  const updateUser = (userData: User) => {
    setUser(userData)
  }

  return (
    <AuthContext.Provider value={{
      user,
      isAuthenticated: !!user,
      isLoading,
      login,
      logout,
      updateUser
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
