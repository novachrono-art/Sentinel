import React, { createContext, useContext, useState, useEffect } from 'react'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  // Pre-initialize with Sarah Merchant for seamless local development
  const [user, setUser] = useState({
    id: 'usr_merchant_001',
    name: 'Sarah Merchant',
    email: 'merchant@razorpay-recovery.io',
    role: 'merchant',
    merchant_id: 'mer_rzp_live_01'
  })
  const [token, setToken] = useState('demo_dev_jwt_token_active')
  const [loading, setLoading] = useState(false)
  const [authError, setAuthError] = useState(null)

  useEffect(() => {
    // Auto-login to obtain a genuine active JWT session
    const autoLogin = async () => {
      try {
        const res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email: 'merchant@razorpay-recovery.io',
            password: 'merchantpassword123'
          })
        })
        if (res.ok) {
          const data = await res.json()
          setToken(data.access_token)
          setUser({
            id: 'usr_merchant_001',
            name: data.name,
            email: data.email,
            role: data.role,
            merchant_id: 'mer_demo_apex'
          })
        }
      } catch (err) {
        console.warn('Auto login fallback:', err)
      }
    }
    autoLogin()
  }, [])


  const login = async (email, password) => {
    setLoading(true)
    setAuthError(null)
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      })

      if (!res.ok) {
        const errorData = await res.json()
        throw new Error(errorData.detail || 'Authentication failed')
      }

      const data = await res.json()
      setToken(data.access_token)
      setUser({
        id: data.role === 'merchant' ? 'usr_merchant_001' : 'usr_reviewer_002',
        name: data.name,
        email: data.email,
        role: data.role
      })
      return true
    } catch (err) {
      setAuthError(err.message || 'Login failed')
      return false
    } finally {
      setLoading(false)
    }
  }

  const loginWithGoogle = async (googleData) => {
    setLoading(true)
    setAuthError(null)
    try {
      const res = await fetch('/api/auth/google', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(googleData)
      })

      if (!res.ok) {
        const errorData = await res.json()
        throw new Error(errorData.detail || 'Google authentication failed')
      }

      const data = await res.json()
      setToken(data.access_token)
      setUser({
        id: `usr_google_${Date.now()}`,
        name: data.name,
        email: data.email,
        role: data.role,
        picture: data.picture
      })
      return true
    } catch (err) {
      setAuthError(err.message || 'Google Login failed')
      return false
    } finally {
      setLoading(false)
    }
  }

  const switchDemoRole = async (targetRole) => {
    if (targetRole === 'admin') {
      await login('admin@razorpay-recovery.io', 'adminpassword123')
    } else if (targetRole === 'reviewer') {
      await login('reviewer@razorpay-recovery.io', 'reviewerpassword123')
    } else {
      await login('merchant@razorpay-recovery.io', 'merchantpassword123')
    }
  }

  const logout = () => {
    setUser(null)
    setToken(null)
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        loading,
        authError,
        login,
        loginWithGoogle,
        logout,
        switchDemoRole,
        isMerchant: user?.role === 'merchant',
        isReviewer: user?.role === 'reviewer'
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
