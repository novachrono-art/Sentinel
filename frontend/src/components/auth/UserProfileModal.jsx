import React from 'react'
import {
  X,
  User,
  Shield,
  Briefcase,
  Mail,
  Key,
  Clock,
  RefreshCw,
  LogOut,
  CheckCircle2,
  Lock,
  Globe,
  Sliders
} from 'lucide-react'
import { useAuth } from '../../features/auth/AuthContext'

export default function UserProfileModal({ isOpen, onClose, onOpenLogin }) {
  const { user, logout, switchDemoRole, loading } = useAuth()

  if (!isOpen || !user) return null

  const isMerchant = user.role === 'merchant'
  const isGoogleUser = user.email.includes('@gmail.com') || Boolean(user.picture)

  const handleSwitchRole = async () => {
    await switchDemoRole(isMerchant ? 'reviewer' : 'merchant')
  }

  const handleSignOut = () => {
    logout()
    onClose()
    if (onOpenLogin) onOpenLogin()
  }

  return (
    <div className="neu-modal-backdrop" onClick={onClose}>
      <div
        className="neu-modal-content neu-card"
        onClick={(e) => e.stopPropagation()}
        style={{
          maxWidth: '520px',
          width: '90%',
          padding: '2rem',
          maxHeight: '90vh',
          overflowY: 'auto'
        }}
      >
        {/* Modal Top Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <User size={20} color="var(--accent-primary)" />
            <h3 style={{ fontSize: '1.25rem', fontWeight: 800 }}>Operator Profile</h3>
          </div>
          <button onClick={onClose} className="neu-btn neu-btn-icon" style={{ width: '32px', height: '32px' }}>
            <X size={16} />
          </button>
        </div>

        {/* User Identity Card Hero */}
        <div className="neu-card-inset" style={{ padding: '1.5rem', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
          {/* Avatar */}
          <div
            style={{
              width: '64px',
              height: '64px',
              borderRadius: '50%',
              background: isMerchant
                ? 'linear-gradient(135deg, #3b82f6, #2563eb)'
                : 'linear-gradient(135deg, #8b5cf6, #6366f1)',
              color: '#ffffff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '1.5rem',
              fontWeight: 800,
              boxShadow: 'var(--shadow-flat-sm)',
              flexShrink: 0,
              overflow: 'hidden'
            }}
          >
            {user.picture ? (
              <img src={user.picture} alt={user.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
            ) : (
              user.name.charAt(0).toUpperCase()
            )}
          </div>

          <div style={{ flex: 1, overflow: 'hidden' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
              <h4 style={{ fontSize: '1.15rem', fontWeight: 800, color: 'var(--text-primary)' }}>
                {user.name}
              </h4>
              <span
                className={`neu-badge ${isMerchant ? 'badge-primary' : 'badge-warning'}`}
                style={{ fontSize: '0.7rem', padding: '0.15rem 0.5rem' }}
              >
                {user.role.toUpperCase()}
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.8125rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
              <Mail size={13} />
              <span style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                {user.email}
              </span>
            </div>

            {isGoogleUser && (
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem', marginTop: '0.35rem', fontSize: '0.7rem', color: 'var(--accent-primary)', fontWeight: 600 }}>
                <Globe size={12} />
                Google OAuth Verified
              </div>
            )}
          </div>
        </div>

        {/* Account Details & Session Telemetry */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1.5rem' }}>
          <div className="neu-card-inset">
            <span className="metric-label" style={{ fontSize: '0.6875rem' }}>Account ID</span>
            <div className="code-pill" style={{ marginTop: '0.35rem', fontSize: '0.75rem', display: 'inline-block' }}>
              {user.id}
            </div>
            <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>
              Primary Identity
            </p>
          </div>

          <div className="neu-card-inset">
            <span className="metric-label" style={{ fontSize: '0.6875rem' }}>Merchant Organization</span>
            <div className="code-pill" style={{ marginTop: '0.35rem', fontSize: '0.75rem', display: 'inline-block' }}>
              {user.merchant_id || 'RZP_PLATFORM_ADMIN'}
            </div>
            <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>
              Active Org Context
            </p>
          </div>

          <div className="neu-card-inset">
            <span className="metric-label" style={{ fontSize: '0.6875rem' }}>Session Security</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', marginTop: '0.35rem', color: 'var(--accent-emerald)', fontWeight: 700, fontSize: '0.8125rem' }}>
              <CheckCircle2 size={14} />
              JWT ACTIVE
            </div>
            <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>
              HS256 24h Expiry
            </p>
          </div>

          <div className="neu-card-inset">
            <span className="metric-label" style={{ fontSize: '0.6875rem' }}>Environment</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', marginTop: '0.35rem', color: 'var(--accent-primary)', fontWeight: 700, fontSize: '0.8125rem' }}>
              <Sliders size={14} />
              RAZORPAY TEST
            </div>
            <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.35rem' }}>
              Sandbox / Deterministic
            </p>
          </div>
        </div>

        {/* Role Permissions Summary */}
        <div className="neu-card-inset" style={{ padding: '1rem 1.25rem', marginBottom: '1.5rem' }}>
          <span className="metric-label" style={{ fontSize: '0.7rem', marginBottom: '0.5rem', display: 'block' }}>
            Active Role Capabilities ({user.role.toUpperCase()})
          </span>
          <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
            {isMerchant ? (
              <>
                <li style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <CheckCircle2 size={14} color="var(--accent-emerald)" />
                  View all failed payments & revenue at risk
                </li>
                <li style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <CheckCircle2 size={14} color="var(--accent-emerald)" />
                  Trigger safe payment retries (Attempt limit: 3)
                </li>
                <li style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <CheckCircle2 size={14} color="var(--accent-emerald)" />
                  Generate and dispatch smart payment links
                </li>
              </>
            ) : (
              <>
                <li style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <CheckCircle2 size={14} color="var(--accent-violet)" />
                  Access Human Review & Quarantine Queue
                </li>
                <li style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <CheckCircle2 size={14} color="var(--accent-violet)" />
                  Approve / Reject high-risk transaction overrides
                </li>
                <li style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <CheckCircle2 size={14} color="var(--accent-violet)" />
                  Inspect complete cryptographically signed audit logs
                </li>
              </>
            )}
          </ul>
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' }}>
          <button
            type="button"
            onClick={handleSwitchRole}
            disabled={loading}
            className="neu-btn"
            style={{ flex: 1, justifyContent: 'center' }}
          >
            <RefreshCw size={15} className={loading ? 'spin-anim' : ''} />
            Switch to {isMerchant ? 'Reviewer' : 'Merchant'}
          </button>

          <button
            type="button"
            onClick={handleSignOut}
            className="neu-btn"
            style={{ color: 'var(--accent-rose)', justifyContent: 'center' }}
          >
            <LogOut size={15} />
            Sign Out
          </button>
        </div>
      </div>
    </div>
  )
}
