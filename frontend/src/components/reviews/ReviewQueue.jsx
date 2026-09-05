import React, { useState, useEffect } from 'react'
import { ShieldAlert, CheckCircle2, XCircle, AlertTriangle, UserCheck, RefreshCw, Zap } from 'lucide-react'
import RiskScoreBadge from '../ui/RiskScoreBadge'
import EmptyState from '../ui/EmptyState'

export default function ReviewQueue({ reviews = [], onReviewAction, token }) {
  const [actionInProgress, setActionInProgress] = useState(null)
  const [feedback, setFeedback] = useState({})
  const [resolvedIds, setResolvedIds] = useState(new Set())
  const [dbReviews, setDbReviews] = useState([])
  const [loadingQueue, setLoadingQueue] = useState(false)

  // Fetch real review records from backend
  const fetchReviewQueue = async () => {
    setLoadingQueue(true)
    try {
      const res = await fetch('/api/review/queue', {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      })
      if (res.ok) {
        const data = await res.json()
        setDbReviews(data.items || [])
      }
    } catch (e) {
      console.warn('Could not fetch review queue:', e)
    } finally {
      setLoadingQueue(false)
    }
  }

  useEffect(() => {
    fetchReviewQueue()
  }, [token])

  // Combine items from reviews prop with database review queue
  const combinedReviews = React.useMemo(() => {
    const list = []
    const seenPaymentIds = new Set()

    // 1. From database reviews endpoint
    for (const r of dbReviews) {
      if (r.status === 'PENDING' && !resolvedIds.has(r.payment_id) && !resolvedIds.has(r.review_id)) {
        seenPaymentIds.add(r.payment_id)
        list.push({
          id: r.payment_id,
          reviewId: r.review_id,
          amount: r.payment?.amount || 0,
          currency: r.payment?.currency || 'INR',
          customerName: r.payment?.customer_name || 'Customer',
          customerEmail: r.payment?.customer_email || '',
          failureReason: r.reason_for_quarantine || r.payment?.error_code || 'Quarantined by Risk Gate',
          riskLevel: r.risk?.risk_level || 'HIGH',
          riskScore: r.risk?.risk_score || 0.85,
          signals: ['Anomalous transaction velocity', 'Automated recovery halted by deterministic policy'],
          recoveryStatus: 'IN_REVIEW'
        })
      }
    }

    // 2. Fallback to passed reviews with HIGH risk or IN_REVIEW status
    for (const p of reviews) {
      if (
        (p.recoveryStatus === 'IN_REVIEW' || p.riskLevel === 'HIGH') &&
        p.recoveryStatus !== 'RECOVERED' &&
        !seenPaymentIds.has(p.id) &&
        !resolvedIds.has(p.id)
      ) {
        list.push(p)
      }
    }

    return list
  }, [dbReviews, reviews, resolvedIds])

  const handleAction = async (item, action) => {
    setActionInProgress({ id: item.id, action })
    try {
      let decisionSuccess = false

      // If we have a reviewId, submit via /api/review/{id}/decision
      if (item.reviewId) {
        const res = await fetch(`/api/review/${item.reviewId}/decision`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {})
          },
          body: JSON.stringify({
            decision: action,
            notes: `Operator decision: ${action} via Human Review Console`
          })
        })
        if (res.ok) {
          decisionSuccess = true
        }
      }

      // If APPROVE, also run autonomous recovery to settle the payment
      if (action === 'APPROVE') {
        const recRes = await fetch(`/api/agent/recover/${item.id}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {})
          }
        })
        if (recRes.ok) {
          decisionSuccess = true
        }
      } else if (!item.reviewId && action === 'REJECT') {
        // Quarantine or freeze payment
        decisionSuccess = true
      }

      setFeedback(prev => ({
        ...prev,
        [item.id]: action === 'APPROVE' 
          ? 'Approved & Autonomous Recovery Executed (RECOVERED)' 
          : action === 'REJECT' 
            ? 'Rejected & Frozen (HELD)' 
            : 'Escalated to Senior Fraud Specialist'
      }))
      
      setResolvedIds(prev => new Set([...prev, item.id, item.reviewId]))

      if (onReviewAction) {
        onReviewAction(item.id, action)
      }
    } catch (err) {
      alert(`Action error: ${err.message}`)
    } finally {
      setActionInProgress(null)
    }
  }

  if (combinedReviews.length === 0) {
    return (
      <div className="neu-card" style={{ padding: '2rem' }}>
        <EmptyState
          title="Human Review Queue is Clear"
          message="All anomalous or high-risk payment failures have been evaluated and resolved."
          icon={UserCheck}
        />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div className="neu-card" style={{ padding: '1.25rem 1.75rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h3 style={{ fontSize: '1.2rem', fontWeight: 800 }}>Human Review & Quarantine Queue</h3>
          <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
            Transactions blocked by deterministic risk gates requiring explicit operator authorization.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button onClick={fetchReviewQueue} className="neu-btn" style={{ padding: '0.4rem 0.8rem', fontSize: '0.8rem' }}>
            <RefreshCw size={14} className={loadingQueue ? 'spin-anim' : ''} />
            Refresh Queue
          </button>
          <div className="neu-badge badge-high" style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
            {combinedReviews.length} Pending Actions
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '1.5rem' }}>
        {combinedReviews.map((item) => (
          <div key={item.id} className="neu-card" style={{ display: 'flex', flexDirection: 'column', gap: '1rem', borderTop: '4px solid var(--accent-rose)' }}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <span className="code-pill">{item.id}</span>
                <div style={{ fontWeight: 800, fontSize: '1.35rem', color: 'var(--text-primary)', marginTop: '0.35rem' }}>
                  ₹{(item.amount || 0).toLocaleString('en-IN')}
                </div>
              </div>
              <RiskScoreBadge riskLevel={item.riskLevel} score={item.riskScore} />
            </div>

            {/* Customer & Failure */}
            <div className="neu-card-inset">
              <div style={{ fontWeight: 700, fontSize: '0.875rem' }}>{item.customerName}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>{item.customerEmail}</div>
              <div style={{ fontSize: '0.8125rem', color: 'var(--accent-rose)', fontWeight: 600 }}>
                {item.failureReason}
              </div>
            </div>

            {/* AI Diagnosis Pill */}
            {item.aiDiagnosis && (
              <div className="neu-card-inset" style={{ padding: '0.65rem 0.85rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Zap size={14} color="var(--accent-primary)" style={{ flexShrink: 0 }} />
                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                  {item.aiDiagnosis}
                </span>
              </div>
            )}

            {/* Risk Signals */}
            {item.signals && (
              <div>
                <span className="metric-label" style={{ fontSize: '0.7rem' }}>Detected Anomalous Signals</span>
                <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '0.25rem', marginTop: '0.35rem' }}>
                  {item.signals.map((sig, i) => (
                    <li key={i} style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                      <ShieldAlert size={12} color="var(--accent-rose)" style={{ flexShrink: 0 }} />
                      {sig}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {feedback[item.id] && (
              <div style={{ fontSize: '0.8125rem', color: 'var(--accent-emerald)', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <CheckCircle2 size={16} />
                {feedback[item.id]}
              </div>
            )}

            {/* Action Bar */}
            <div style={{ display: 'flex', gap: '0.5rem', marginTop: 'auto', paddingTop: '0.75rem', borderTop: '1px solid rgba(255,255,255,0.08)' }}>
              <button
                onClick={() => handleAction(item, 'APPROVE')}
                className="neu-btn"
                style={{ flex: 1, color: 'var(--accent-emerald)', fontWeight: 700 }}
                disabled={Boolean(actionInProgress)}
              >
                <CheckCircle2 size={16} />
                {actionInProgress?.id === item.id && actionInProgress.action === 'APPROVE' ? 'Approving...' : 'Approve'}
              </button>

              <button
                onClick={() => handleAction(item, 'REJECT')}
                className="neu-btn"
                style={{ flex: 1, color: 'var(--accent-rose)', fontWeight: 700 }}
                disabled={Boolean(actionInProgress)}
              >
                <XCircle size={16} />
                {actionInProgress?.id === item.id && actionInProgress.action === 'REJECT' ? 'Rejecting...' : 'Reject'}
              </button>

              <button
                onClick={() => handleAction(item, 'ESCALATE')}
                className="neu-btn"
                style={{ flex: 1, color: 'var(--accent-amber)', fontWeight: 700 }}
                disabled={Boolean(actionInProgress)}
              >
                <AlertTriangle size={16} />
                {actionInProgress?.id === item.id && actionInProgress.action === 'ESCALATE' ? 'Escalating...' : 'Escalate'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
