import React from 'react'
import { TrendingUp, AlertCircle, ArrowUpRight } from 'lucide-react'

export default function MetricCard({ title, value, subtitle, icon: Icon, color, progress }) {
  return (
    <div className="neu-card" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', position: 'relative' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <span className="metric-label">{title}</span>
        {Icon && (
          <div
            style={{
              width: '36px',
              height: '36px',
              borderRadius: '50%',
              background: 'var(--bg-inset)',
              boxShadow: 'var(--shadow-inset-sm)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: color || 'var(--accent-primary)'
            }}
          >
            <Icon size={18} />
          </div>
        )}
      </div>

      <div className="metric-number" style={{ color: color || 'var(--text-primary)' }}>
        {value}
      </div>

      {typeof progress === 'number' && (
        <div style={{ marginTop: '0.25rem' }}>
          <div
            style={{
              height: '6px',
              width: '100%',
              background: 'var(--bg-inset)',
              borderRadius: '999px',
              boxShadow: 'var(--shadow-inset-sm)',
              overflow: 'hidden'
            }}
          >
            <div
              style={{
                height: '100%',
                width: `${Math.min(Math.max(progress, 0), 100)}%`,
                background: color || 'var(--accent-primary)',
                borderRadius: '999px',
                transition: 'width 0.6s ease-in-out'
              }}
            />
          </div>
        </div>
      )}

      {subtitle && (
        <div style={{ fontSize: '0.8125rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
          {subtitle}
        </div>
      )}
    </div>
  )
}
