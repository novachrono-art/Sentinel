import React from 'react'
import { User, Shield, Briefcase, ChevronDown } from 'lucide-react'
import { useAuth } from '../../features/auth/AuthContext'

export default function UserRoleBadge({ onOpenProfile, onOpenLogin }) {
  const { user } = useAuth()

  if (!user) {
    return (
      <button onClick={onOpenLogin} className="neu-btn neu-btn-primary" style={{ padding: '0.5rem 1rem' }}>
        <User size={15} /> Sign In
      </button>
    )
  }

  const isMerchant = user.role === 'merchant'

  return (
    <button
      onClick={onOpenProfile}
      className="neu-btn"
      style={{
        padding: '0.35rem 0.85rem 0.35rem 0.45rem',
        borderRadius: 'var(--radius-pill)',
        display: 'flex',
        alignItems: 'center',
        gap: '0.65rem',
        cursor: 'pointer'
      }}
      title="Click to view Operator Profile & Permissions"
    >
      <div
        style={{
          width: '32px',
          height: '32px',
          borderRadius: '50%',
          background: isMerchant ? 'var(--accent-primary)' : 'var(--accent-violet)',
          color: '#ffffff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: 'var(--shadow-flat-sm)',
          overflow: 'hidden',
          fontSize: '0.8125rem',
          fontWeight: 700
        }}
      >
        {user.picture ? (
          <img src={user.picture} alt={user.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          isMerchant ? <Briefcase size={16} /> : <Shield size={16} />
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', textAlign: 'left' }}>
        <span style={{ fontSize: '0.8125rem', fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.2 }}>
          {user.name}
        </span>
        <span
          className={`neu-badge ${isMerchant ? 'badge-primary' : 'badge-warning'}`}
          style={{ padding: '0.05rem 0.4rem', fontSize: '0.625rem', marginTop: '0.1rem' }}
        >
          {user.role.toUpperCase()}
        </span>
      </div>

      <ChevronDown size={14} color="var(--text-muted)" style={{ marginLeft: '0.15rem' }} />
    </button>
  )
}
