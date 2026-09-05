import React from 'react'
import { ShieldCheck, ShieldAlert, Shield } from 'lucide-react'

export default function RiskScoreBadge({ riskLevel, score }) {
  const level = (riskLevel || 'LOW').toUpperCase()

  let badgeClass = 'badge-low'
  let Icon = ShieldCheck
  let color = 'var(--accent-emerald)'

  if (level === 'HIGH') {
    badgeClass = 'badge-high'
    Icon = ShieldAlert
    color = 'var(--accent-rose)'
  } else if (level === 'MEDIUM') {
    badgeClass = 'badge-warning'
    Icon = Shield
    color = 'var(--accent-amber)'
  }

  return (
    <span
      className={`neu-badge ${badgeClass}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.35rem',
        padding: '0.35rem 0.75rem',
        fontSize: '0.75rem',
        fontWeight: 700
      }}
    >
      <Icon size={14} color={color} />
      <span>{level}</span>
      {typeof score === 'number' && (
        <span
          style={{
            marginLeft: '0.2rem',
            paddingLeft: '0.4rem',
            borderLeft: '1px solid currentColor',
            opacity: 0.85
          }}
        >
          {score.toFixed(2)}
        </span>
      )}
    </span>
  )
}
