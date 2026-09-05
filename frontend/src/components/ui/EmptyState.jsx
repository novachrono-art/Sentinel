import React from 'react'
import { Inbox } from 'lucide-react'

export default function EmptyState({ title = 'No records found', message = 'There are currently no items matching your filter criteria.', icon: Icon = Inbox, actionText, onAction }) {
  return (
    <div
      className="neu-card-inset"
      style={{
        padding: '3rem 2rem',
        textAlign: 'center',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '1rem',
        margin: '1.5rem 0'
      }}
    >
      <div
        style={{
          width: '56px',
          height: '56px',
          borderRadius: '50%',
          background: 'var(--bg-card)',
          boxShadow: 'var(--shadow-flat-sm)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--text-muted)'
        }}
      >
        <Icon size={28} />
      </div>
      <div>
        <h4 style={{ fontSize: '1.125rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '0.25rem' }}>
          {title}
        </h4>
        <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)', maxWidth: '400px' }}>
          {message}
        </p>
      </div>
      {actionText && onAction && (
        <button onClick={onAction} className="neu-btn" style={{ marginTop: '0.5rem' }}>
          {actionText}
        </button>
      )}
    </div>
  )
}
