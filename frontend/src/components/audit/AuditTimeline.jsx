import React from 'react'
import { History, CheckCircle, ShieldCheck, Zap, AlertCircle, ArrowRight } from 'lucide-react'
import StatusPill from '../ui/StatusPill'
import RiskScoreBadge from '../ui/RiskScoreBadge'
import EmptyState from '../ui/EmptyState'

export default function AuditTimeline({ auditLogs = [] }) {
  if (!auditLogs || auditLogs.length === 0) {
    return (
      <div className="neu-card" style={{ padding: '1.75rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
          <div>
            <h3 style={{ fontSize: '1.15rem', fontWeight: 800 }}>Immutable Recovery Audit Trail</h3>
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
              Cryptographically timestamped record of every risk calculation, tool execution, and state change.
            </p>
          </div>
          <span className="code-pill">APPEND-ONLY LOG</span>
        </div>
        <EmptyState
          title="No Audit Events Recorded"
          message="Audit entries will be logged automatically as payment failures are ingested and processed."
          icon={History}
        />
      </div>
    )
  }

  const getEventIcon = (event) => {
    switch (event) {
      case 'FAILURE_INGESTED':
        return <AlertCircle size={16} color="var(--accent-rose)" />
      case 'RISK_EVALUATION':
        return <ShieldCheck size={16} color="var(--accent-primary)" />
      case 'AI_DIAGNOSIS':
        return <Zap size={16} color="var(--accent-violet)" />
      case 'RECOVERY_EXECUTED':
        return <CheckCircle size={16} color="var(--accent-emerald)" />
      default:
        return <History size={16} color="var(--text-muted)" />
    }
  }

  return (
    <div className="neu-card" style={{ padding: '1.75rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div>
          <h3 style={{ fontSize: '1.15rem', fontWeight: 800 }}>Immutable Recovery Audit Trail</h3>
          <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
            Cryptographically timestamped record of every risk calculation, tool execution, and state change.
          </p>
        </div>
        <span className="code-pill">APPEND-ONLY LOG</span>
      </div>

      <div style={{ position: 'relative', paddingLeft: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        {/* Vertical line indicator */}
        <div
          style={{
            position: 'absolute',
            left: '27px',
            top: '10px',
            bottom: '10px',
            width: '2px',
            background: 'var(--bg-inset)',
            boxShadow: 'var(--shadow-inset-sm)'
          }}
        />

        {auditLogs.map((log) => (
          <div key={log.id} style={{ display: 'flex', gap: '1.25rem', position: 'relative' }}>
            {/* Dot Node */}
            <div
              style={{
                width: '34px',
                height: '34px',
                borderRadius: '50%',
                background: 'var(--bg-card)',
                boxShadow: 'var(--shadow-flat-sm)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: 2,
                flexShrink: 0
              }}
            >
              {getEventIcon(log.event)}
            </div>

            {/* Event Box */}
            <div className="neu-card-inset" style={{ flex: 1, padding: '1rem 1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.35rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span className="code-pill" style={{ fontWeight: 700 }}>{log.event}</span>
                  <span className="code-pill">{log.paymentId}</span>
                </div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                  {log.timestamp}
                </span>
              </div>

              <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                {log.details}
              </p>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                <span>Actor: <strong style={{ color: 'var(--text-primary)' }}>{log.actor}</strong></span>
                <span className="neu-badge badge-primary" style={{ padding: '0.2rem 0.5rem' }}>
                  {log.outcome}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
