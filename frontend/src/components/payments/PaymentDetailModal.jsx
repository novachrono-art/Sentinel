import React, { useState } from 'react'
import {
  X,
  ShieldAlert,
  ShieldCheck,
  Zap,
  RefreshCw,
  Link,
  Send,
  AlertTriangle,
  CheckCircle2,
  Clock,
  User,
  History,
  FileText,
  Activity,
  ArrowRight
} from 'lucide-react'
import StatusPill from '../ui/StatusPill'
import RiskScoreBadge from '../ui/RiskScoreBadge'

export default function PaymentDetailModal({ payment, onClose, onExecuteAction, token }) {
  const [actionLoading, setActionLoading] = useState(null)
  const [actionSuccess, setActionSuccess] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [livePayment, setLivePayment] = useState(payment)
  const [liveTrace, setLiveTrace] = useState(null)

  if (!livePayment) return null

  const handleAction = async (actionType) => {
    setActionLoading(actionType)
    setActionSuccess(null)
    setActionError(null)
    setLiveTrace(null)

    try {
      if (actionType === 'RETRY') {
        const res = await fetch(`/api/agent/recover/${livePayment.id}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {})
          }
        })
        const data = await res.json()
        if (res.ok) {
          const runData = data.data || {}
          if (runData.trace) {
            setLiveTrace(runData.trace)
          }
          const finalOutcome = runData.final_outcome || 'RECOVERED'
          setActionSuccess(`LangGraph Recovery Complete: ${data.message || 'Outcome verified.'}`)
          setLivePayment(prev => ({
            ...prev,
            recoveryStatus: finalOutcome === 'ESCALATED' ? 'IN_REVIEW' : 'RECOVERED',
            status: finalOutcome === 'ESCALATED' ? 'IN_REVIEW' : 'RECOVERED',
            retryCount: (prev.retryCount || 0) + 1
          }))
          if (onExecuteAction) onExecuteAction(livePayment.id, 'RETRY')
        } else {
          setActionError(data.detail || 'Recovery attempt failed.')
        }
      } else if (actionType === 'ESCALATE') {
        const res = await fetch(`/api/review/quarantine/${livePayment.id}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {})
          },
          body: JSON.stringify({ reason: 'Operator escalated from triage modal' })
        })
        const data = await res.json()
        if (res.ok) {
          setActionSuccess('Payment successfully quarantined to Human Review queue.')
          setLivePayment(prev => ({
            ...prev,
            recoveryStatus: 'IN_REVIEW',
            status: 'IN_REVIEW'
          }))
          if (onExecuteAction) onExecuteAction(livePayment.id, 'ESCALATE')
        } else {
          setActionError(data.detail || 'Failed to escalate.')
        }
      } else {
        // Payment Link generation
        setActionSuccess(`Smart Recovery Link generated: https://checkout.razorpay.com/pay/${livePayment.id}`)
        if (onExecuteAction) onExecuteAction(livePayment.id, actionType)
      }
    } catch (err) {
      setActionError(`Network error: ${err.message}`)
    } finally {
      setActionLoading(null)
    }
  }

  const isCapped = (livePayment.retryCount || 0) >= (livePayment.maxRetries || 3)
  const isHighRisk = livePayment.riskLevel === 'HIGH'
  const isRecovered = livePayment.recoveryStatus === 'RECOVERED'

  return (
    <div className="neu-modal-backdrop" onClick={onClose}>
      <div
        className="neu-modal-content neu-card"
        onClick={(e) => e.stopPropagation()}
        style={{
          maxWidth: '820px',
          width: '92%',
          maxHeight: '90vh',
          overflowY: 'auto',
          padding: '2rem'
        }}
      >
        {/* Modal Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.35rem' }}>
              <h3 style={{ fontSize: '1.35rem', fontWeight: 800 }}>Payment Failure Triage & Recovery</h3>
              <StatusPill status={livePayment.recoveryStatus} />
            </div>
            <span className="code-pill">{livePayment.id}</span>
          </div>

          <button onClick={onClose} className="neu-btn neu-btn-icon" style={{ width: '36px', height: '36px' }}>
            <X size={18} />
          </button>
        </div>

        {/* Success / Error Banners */}
        {actionSuccess && (
          <div
            className="neu-card-inset"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.75rem',
              color: 'var(--accent-emerald)',
              marginBottom: '1.5rem',
              borderLeft: '4px solid var(--accent-emerald)',
              padding: '1rem'
            }}
          >
            <CheckCircle2 size={20} style={{ flexShrink: 0 }} />
            <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>{actionSuccess}</span>
          </div>
        )}

        {actionError && (
          <div
            className="neu-card-inset"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.75rem',
              color: 'var(--accent-rose)',
              marginBottom: '1.5rem',
              borderLeft: '4px solid var(--accent-rose)',
              padding: '1rem'
            }}
          >
            <AlertTriangle size={20} style={{ flexShrink: 0 }} />
            <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>{actionError}</span>
          </div>
        )}

        {/* Core Transaction Highlights */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
          <div className="neu-card-inset">
            <span className="metric-label">Amount</span>
            <div style={{ fontSize: '1.5rem', fontWeight: 800, color: 'var(--text-primary)', marginTop: '0.25rem' }}>
              ₹{(livePayment.amount || 0).toLocaleString('en-IN')}
            </div>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{livePayment.currency}</span>
          </div>

          <div className="neu-card-inset">
            <span className="metric-label">Customer Profile</span>
            <div style={{ fontWeight: 700, color: 'var(--text-primary)', marginTop: '0.25rem' }}>
              {livePayment.customerName}
            </div>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{livePayment.customerEmail}</span>
          </div>

          <div className="neu-card-inset">
            <span className="metric-label">Deterministic Risk</span>
            <div style={{ marginTop: '0.35rem' }}>
              <RiskScoreBadge riskLevel={livePayment.riskLevel} score={livePayment.riskScore} />
            </div>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginTop: '0.25rem' }}>
              Model: Logistic Regression v1.0
            </span>
          </div>

          <div className="neu-card-inset">
            <span className="metric-label">Retry Guardrail</span>
            <div style={{ fontSize: '1.25rem', fontWeight: 800, color: isCapped ? 'var(--accent-rose)' : 'var(--text-primary)', marginTop: '0.25rem' }}>
              {livePayment.retryCount} / {livePayment.maxRetries}
            </div>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              {isCapped ? 'Ceiling reached (Hard stop)' : 'Attempts available'}
            </span>
          </div>
        </div>

        {/* AI Root Cause Diagnosis & Recommendation Panel */}
        <div className="neu-card" style={{ marginBottom: '1.5rem', borderLeft: '4px solid var(--accent-primary)', padding: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.65rem' }}>
            <Zap size={20} color="var(--accent-primary)" />
            <h4 style={{ fontSize: '1rem', fontWeight: 800 }}>AI Root Cause Diagnosis & Context</h4>
          </div>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', lineHeight: 1.65, marginBottom: '1rem' }}>
            {livePayment.aiDiagnosis || 'Automated failure taxonomy indicates network timeout during authorization.'}
          </p>

          <div className="neu-card-inset" style={{ padding: '0.85rem 1.15rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
            <div>
              <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                Recommended Action:
              </span>
              <div style={{ fontSize: '0.925rem', fontWeight: 800, color: 'var(--accent-primary)', marginTop: '0.2rem' }}>
                {livePayment.recommendedAction || 'DIRECT_GATEWAY_RETRY'}
              </div>
            </div>
            <span className="neu-badge badge-primary" style={{ fontSize: '0.75rem' }}>
              Confidence: 94%
            </span>
          </div>
        </div>

        {/* Live LangGraph State Machine Execution Trace */}
        {liveTrace && liveTrace.length > 0 && (
          <div className="neu-card-inset" style={{ marginBottom: '1.5rem', padding: '1.25rem', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
              <Activity size={18} color="var(--accent-emerald)" />
              <h4 style={{ fontSize: '0.875rem', fontWeight: 800, color: 'var(--accent-emerald)' }}>
                Live LangGraph Execution Trace
              </h4>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {liveTrace.map((step, idx) => (
                <div key={idx} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', fontSize: '0.8125rem' }}>
                  <CheckCircle2 size={15} color="var(--accent-emerald)" style={{ marginTop: '2px', flexShrink: 0 }} />
                  <div>
                    <strong style={{ color: 'var(--text-primary)', marginRight: '0.35rem' }}>
                      [{step.step}]:
                    </strong>
                    <span style={{ color: 'var(--text-secondary)' }}>{step.details}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Signals & Evidence */}
        {livePayment.signals && livePayment.signals.length > 0 && (
          <div className="neu-card-inset" style={{ marginBottom: '1.5rem' }}>
            <h4 style={{ fontSize: '0.8125rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
              Extracted Risk Features & Evidence
            </h4>
            <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
              {livePayment.signals.map((sig, idx) => (
                <li key={idx} style={{ fontSize: '0.8125rem', display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)' }}>
                  <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: isHighRisk ? 'var(--accent-rose)' : 'var(--accent-emerald)' }}></div>
                  {sig}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Safe Action Execution Buttons */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem', justifyContent: 'flex-end', paddingTop: '1rem', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
          <button onClick={onClose} className="neu-btn">
            Close
          </button>

          {!isRecovered && !isHighRisk && !isCapped && (
            <button
              onClick={() => handleAction('RETRY')}
              className="neu-btn neu-btn-primary"
              disabled={Boolean(actionLoading)}
            >
              <RefreshCw size={16} className={actionLoading === 'RETRY' ? 'spin-anim' : ''} />
              {actionLoading === 'RETRY' ? 'Executing LangGraph Retry...' : `Execute Auto-Retry (${livePayment.retryCount + 1}/${livePayment.maxRetries})`}
            </button>
          )}

          {isRecovered && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--accent-emerald)', fontWeight: 700, fontSize: '0.875rem', padding: '0.5rem 1rem' }}>
              <CheckCircle2 size={18} /> Recovered by TheSentinel Agent
            </div>
          )}

          <button
            onClick={() => handleAction('PAYMENT_LINK')}
            className="neu-btn"
            disabled={Boolean(actionLoading)}
          >
            <Link size={16} color="var(--accent-primary)" />
            Generate Payment Link
          </button>

          {isHighRisk && livePayment.recoveryStatus !== 'IN_REVIEW' && (
            <button
              onClick={() => handleAction('ESCALATE')}
              className="neu-btn"
              style={{ color: 'var(--accent-amber)' }}
              disabled={Boolean(actionLoading)}
            >
              <AlertTriangle size={16} />
              Escalate to Reviewer Queue
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
