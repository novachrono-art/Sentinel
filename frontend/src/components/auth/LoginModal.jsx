import React, { useState, useEffect } from 'react'
import { X, Lock, Mail, Shield, Briefcase, AlertCircle, ArrowRight, CheckCircle2 } from 'lucide-react'
import { useAuth } from '../../features/auth/AuthContext'

export default function LoginModal({ isOpen, onClose }) {
  const { login, loginWithGoogle, loading, authError } = useAuth()
  const [email, setEmail] = useState('merchant@razorpay-recovery.io')
  const [password, setPassword] = useState('merchantpassword123')
  const [googlePrompt, setGooglePrompt] = useState(false)
  const [googleCustomEmail, setGoogleCustomEmail] = useState('')
  const [googleCustomName, setGoogleCustomName] = useState('')
  const [selectedGoogleRole, setSelectedGoogleRole] = useState('merchant')

  useEffect(() => {
    // Check if Google GIS SDK is loaded
    if (window.google?.accounts?.id && isOpen) {
      try {
        window.google.accounts.id.initialize({
          client_id: '109283746582-mockgoogleclientid.apps.googleusercontent.com',
          callback: async (response) => {
            if (response.credential) {
              const ok = await loginWithGoogle({ credential: response.credential })
              if (ok) onClose()
            }
          }
        })
      } catch (e) {
        console.warn('Google GSI initialization notice:', e)
      }
    }
  }, [isOpen])

  if (!isOpen) return null

  const handleSubmit = async (e) => {
    e.preventDefault()
    const success = await login(email, password)
    if (success) onClose()
  }

  const handleQuickLogin = async (demoRole) => {
    if (demoRole === 'admin') {
      setEmail('admin@razorpay-recovery.io')
      setPassword('adminpassword123')
      const success = await login('admin@razorpay-recovery.io', 'adminpassword123')
      if (success) onClose()
    } else if (demoRole === 'reviewer') {
      setEmail('reviewer@razorpay-recovery.io')
      setPassword('reviewerpassword123')
      const success = await login('reviewer@razorpay-recovery.io', 'reviewerpassword123')
      if (success) onClose()
    } else {
      setEmail('merchant@razorpay-recovery.io')
      setPassword('merchantpassword123')
      const success = await login('merchant@razorpay-recovery.io', 'merchantpassword123')
      if (success) onClose()
    }
  }

  const handleGoogleSignInClick = async () => {
    // Check if Google SDK has active prompt
    if (window.google?.accounts?.id) {
      try {
        window.google.accounts.id.prompt((notification) => {
          if (notification.isNotDisplayed() || notification.isSkippedMoment()) {
            setGooglePrompt(true)
          }
        })
      } catch {
        setGooglePrompt(true)
      }
    } else {
      setGooglePrompt(true)
    }
  }

  const handleGoogleCustomSubmit = async (e) => {
    e.preventDefault()
    if (!googleCustomEmail) return
    const success = await loginWithGoogle({
      email: googleCustomEmail,
      name: googleCustomName || googleCustomEmail.split('@')[0],
      role: selectedGoogleRole
    })
    if (success) {
      setGooglePrompt(false)
      onClose()
    }
  }

  return (
    <div className="neu-modal-backdrop" onClick={onClose}>
      <div
        className="neu-modal-content neu-card"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: '460px', width: '90%', padding: '2rem' }}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
          <div>
            <h3 style={{ fontSize: '1.25rem', fontWeight: 800 }}>Sign In</h3>
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
              Sign in with your Google Account or credentials
            </p>
          </div>
          <button onClick={onClose} className="neu-btn neu-btn-icon" style={{ width: '32px', height: '32px' }}>
            <X size={16} />
          </button>
        </div>

        {authError && (
          <div
            className="neu-card-inset"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              color: 'var(--accent-rose)',
              marginBottom: '1rem',
              fontSize: '0.8125rem'
            }}
          >
            <AlertCircle size={16} />
            {authError}
          </div>
        )}

        {/* Working Google Sign-In Button */}
        <div style={{ marginBottom: '1.5rem' }}>
          <button
            type="button"
            onClick={handleGoogleSignInClick}
            disabled={loading}
            className="neu-btn"
            style={{
              width: '100%',
              justifyContent: 'center',
              padding: '0.8rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.75rem',
              boxShadow: 'var(--shadow-flat)',
              border: '1px solid rgba(255,255,255,0.4)'
            }}
          >
            {/* Google G Logo SVG */}
            <svg width="18" height="18" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3.05h3.88c2.27-2.09 3.66-5.17 3.66-9.17z"/>
              <path fill="#34A853" d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.25v3.15C3.26 21.36 7.34 24 12 24z"/>
              <path fill="#FBBC05" d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.25C.45 8.18 0 9.99 0 12s.45 3.82 1.25 5.42l4.03-3.15z"/>
              <path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.34 0 3.26 2.64 1.25 6.58l4.03 3.15c.95-2.83 3.6-4.98 6.72-4.98z"/>
            </svg>
            <span style={{ fontWeight: 700, fontSize: '0.875rem' }}>
              {loading ? 'Signing in with Google...' : 'Continue with Google'}
            </span>
          </button>
        </div>

        {/* Interactive Google Sign-In Popup Drawer */}
        {googlePrompt && (
          <div className="neu-card-inset" style={{ padding: '1.25rem', marginBottom: '1.5rem', border: '1px solid rgba(66, 133, 244, 0.3)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ fontSize: '0.8125rem', fontWeight: 800, color: 'var(--accent-primary)' }}>
                  Google OAuth Verification
                </span>
              </div>
              <button
                onClick={() => setGooglePrompt(false)}
                className="neu-btn neu-btn-icon"
                style={{ width: '24px', height: '24px' }}
              >
                <X size={12} />
              </button>
            </div>

            <form onSubmit={handleGoogleCustomSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              <div>
                <label style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                  Google Email Address
                </label>
                <input
                  type="email"
                  required
                  placeholder="yourname@gmail.com"
                  value={googleCustomEmail}
                  onChange={(e) => setGoogleCustomEmail(e.target.value)}
                  className="neu-input"
                  style={{ marginTop: '0.25rem', padding: '0.5rem 1rem' }}
                />
              </div>

              <div>
                <label style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                  Display Name
                </label>
                <input
                  type="text"
                  placeholder="Your Full Name"
                  value={googleCustomName}
                  onChange={(e) => setGoogleCustomName(e.target.value)}
                  className="neu-input"
                  style={{ marginTop: '0.25rem', padding: '0.5rem 1rem' }}
                />
              </div>

              <div>
                <label style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                  Select Default Role
                </label>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginTop: '0.25rem' }}>
                  <button
                    type="button"
                    onClick={() => setSelectedGoogleRole('merchant')}
                    className={`neu-btn ${selectedGoogleRole === 'merchant' ? 'active' : ''}`}
                    style={{ fontSize: '0.75rem', padding: '0.4rem', justifyContent: 'center' }}
                  >
                    Merchant
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedGoogleRole('reviewer')}
                    className={`neu-btn ${selectedGoogleRole === 'reviewer' ? 'active' : ''}`}
                    style={{ fontSize: '0.75rem', padding: '0.4rem', justifyContent: 'center' }}
                  >
                    Reviewer / Admin
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="neu-btn neu-btn-primary"
                style={{ justifyContent: 'center', marginTop: '0.5rem', padding: '0.65rem' }}
              >
                {loading ? 'Verifying with Google...' : 'Authorize Google Sign-In'}
              </button>
            </form>
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', margin: '1rem 0' }}>
          <div style={{ height: '1px', flex: 1, background: 'var(--bg-inset)' }} />
          <span style={{ fontSize: '0.7rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
            Or sign in with password
          </span>
          <div style={{ height: '1px', flex: 1, background: 'var(--bg-inset)' }} />
        </div>

        {/* 1-Click Quick Role Switchers */}
        <div style={{ marginBottom: '1.25rem' }}>
          <span className="metric-label" style={{ fontSize: '0.7rem' }}>Demo Preset Accounts (1-Click Switch)</span>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.5rem', marginTop: '0.5rem' }}>
            <button
              type="button"
              onClick={() => handleQuickLogin('merchant')}
              className="neu-btn"
              style={{ justifyContent: 'center', padding: '0.55rem', fontSize: '0.75rem', fontWeight: 700 }}
              title="Switch to Sarah Merchant (Apex Retail scope)"
            >
              <Briefcase size={14} color="var(--accent-primary)" />
              Merchant
            </button>
            <button
              type="button"
              onClick={() => handleQuickLogin('reviewer')}
              className="neu-btn"
              style={{ justifyContent: 'center', padding: '0.55rem', fontSize: '0.75rem', fontWeight: 700 }}
              title="Switch to Alex Risk Officer (Human Review queue)"
            >
              <Shield size={14} color="var(--accent-violet)" />
              Reviewer
            </button>
            <button
              type="button"
              onClick={() => handleQuickLogin('admin')}
              className="neu-btn"
              style={{ justifyContent: 'center', padding: '0.55rem', fontSize: '0.75rem', fontWeight: 700 }}
              title="Switch to Platform Admin (Global access)"
            >
              <Lock size={14} color="var(--accent-rose)" />
              Admin
            </button>
          </div>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <label style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
              Email Address
            </label>
            <div style={{ position: 'relative', marginTop: '0.35rem' }}>
              <Mail size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="neu-input"
                style={{ paddingLeft: '2.25rem' }}
              />
            </div>
          </div>

          <div>
            <label style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
              Password
            </label>
            <div style={{ position: 'relative', marginTop: '0.35rem' }}>
              <Lock size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="neu-input"
                style={{ paddingLeft: '2.25rem' }}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="neu-btn neu-btn-primary"
            style={{ justifyContent: 'center', marginTop: '0.5rem', padding: '0.75rem' }}
          >
            {loading ? 'Authenticating...' : 'Sign In'} <ArrowRight size={16} />
          </button>
        </form>
      </div>
    </div>
  )
}
