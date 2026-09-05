import React from 'react'

export default function StatusPill({ status }) {
  const normalized = (status || '').toUpperCase()

  const configMap = {
    RECOVERED: { label: 'Recovered', class: 'badge-low', dotColor: 'var(--accent-emerald)' },
    CAPTURED: { label: 'Recovered', class: 'badge-low', dotColor: 'var(--accent-emerald)' },
    FAILED: { label: 'Failed', class: 'badge-high', dotColor: 'var(--accent-rose)' },
    RETRYING: { label: 'Retrying', class: 'badge-primary', dotColor: 'var(--accent-primary)' },
    RECOVERING: { label: 'Retrying', class: 'badge-primary', dotColor: 'var(--accent-primary)' },
    PENDING: { label: 'Pending Triage', class: 'badge-warning', dotColor: 'var(--accent-amber)' },
    IN_REVIEW: { label: 'Human Review', class: 'badge-warning', dotColor: 'var(--accent-amber)' },
    HELD: { label: 'Held / Blocked', class: 'badge-high', dotColor: 'var(--accent-rose)' },
    SCHEDULED: { label: 'Scheduled', class: 'badge-primary', dotColor: 'var(--accent-cyan)' },
    PROCESSING: { label: 'Processing', class: 'badge-primary', dotColor: 'var(--accent-primary)' }
  }

  const current = configMap[normalized] || { label: status || 'Unknown', class: '', dotColor: 'var(--text-muted)' }

  return (
    <span className={`neu-badge ${current.class}`} style={{ gap: '0.4rem' }}>
      <span className="pulse-dot" style={{ color: current.dotColor }}></span>
      {current.label}
    </span>
  )
}
