import React, { useState } from 'react'
import { Search, Filter, ArrowUpDown, ChevronRight, Zap, RefreshCw, CheckCircle2, AlertTriangle, ShieldCheck } from 'lucide-react'
import StatusPill from '../ui/StatusPill'
import RiskScoreBadge from '../ui/RiskScoreBadge'
import EmptyState from '../ui/EmptyState'

export default function PaymentTable({ payments, onSelectPayment, onExecuteAction, token }) {
  const [filter, setFilter] = useState('ALL')
  const [search, setSearch] = useState('')
  const [rowLoading, setRowLoading] = useState({})

  const handleQuickRetry = async (e, payment) => {
    e.stopPropagation()
    setRowLoading(prev => ({ ...prev, [payment.id]: true }))
    try {
      const res = await fetch(`/api/agent/recover/${payment.id}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {})
        }
      })
      if (res.ok) {
        if (onExecuteAction) {
          onExecuteAction(payment.id, 'RETRY')
        }
      } else {
        const err = await res.json().catch(() => ({}))
        alert(`Retry failed: ${err.detail || 'Recovery attempt unsuccessful'}`)
      }
    } catch (err) {
      alert(`Network error: ${err.message}`)
    } finally {
      setRowLoading(prev => ({ ...prev, [payment.id]: false }))
    }
  }

  const filteredPayments = payments.filter((item) => {
    // Status / Risk filter
    if (filter === 'RECOVERABLE' && (item.riskLevel !== 'LOW' || item.recoveryStatus === 'RECOVERED')) return false
    if (filter === 'RISKY' && item.riskLevel !== 'HIGH') return false
    if (filter === 'RECOVERED' && item.recoveryStatus !== 'RECOVERED') return false
    if (filter === 'IN_REVIEW' && item.recoveryStatus !== 'IN_REVIEW') return false
    if (filter === 'HELD' && item.recoveryStatus !== 'HELD') return false

    // Search query filter
    if (search.trim()) {
      const q = search.toLowerCase()
      const matchId = item.id.toLowerCase().includes(q)
      const matchCustomer = item.customerName.toLowerCase().includes(q)
      const matchEmail = item.customerEmail.toLowerCase().includes(q)
      const matchReason = (item.failureReason || '').toLowerCase().includes(q)
      const matchDiagnosis = (item.aiDiagnosis || '').toLowerCase().includes(q)
      const matchAction = (item.recommendedAction || '').toLowerCase().includes(q)
      return matchId || matchCustomer || matchEmail || matchReason || matchDiagnosis || matchAction
    }
    return true
  })

  const filterTabs = [
    { id: 'ALL', label: 'All Failures' },
    { id: 'RECOVERABLE', label: 'Recoverable' },
    { id: 'RISKY', label: 'High Risk' },
    { id: 'IN_REVIEW', label: 'In Review' },
    { id: 'RECOVERED', label: 'Recovered' },
    { id: 'HELD', label: 'Capped / Held' }
  ]

  return (
    <div className="neu-card" style={{ padding: '1.75rem' }}>
      {/* Top Controls: Filter tabs and search bar */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: '1rem',
          marginBottom: '1.5rem'
        }}
      >
        <div className="neu-tabs" style={{ flexWrap: 'wrap' }}>
          {filterTabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setFilter(t.id)}
              className={`neu-tab-btn ${filter === t.id ? 'active' : ''}`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div style={{ position: 'relative', width: '320px', maxWidth: '100%' }}>
          <Search
            size={16}
            style={{
              position: 'absolute',
              left: '14px',
              top: '50%',
              transform: 'translateY(-50%)',
              color: 'var(--text-muted)'
            }}
          />
          <input
            type="text"
            placeholder="Search ID, customer, AI diagnosis..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="neu-input"
            style={{ paddingLeft: '2.5rem' }}
          />
        </div>
      </div>

      {/* Payment Table */}
      {filteredPayments.length === 0 ? (
        <EmptyState
          title="No Failed Payments Ingested"
          message={
            search || filter !== 'ALL'
              ? 'No failed transactions match the current filter or search criteria.'
              : 'The payment feed is currently empty. Ingested failures from Razorpay or NPCI will appear here.'
          }
          actionText={search || filter !== 'ALL' ? 'Clear Filters' : null}
          onAction={() => {
            setFilter('ALL')
            setSearch('')
          }}
        />
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table
            style={{
              width: '100%',
              borderCollapse: 'separate',
              borderSpacing: '0 0.5rem',
              textAlign: 'left'
            }}
          >
            <thead>
              <tr style={{ color: 'var(--text-muted)', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                <th style={{ padding: '0.75rem 1rem' }}>Transaction ID</th>
                <th style={{ padding: '0.75rem 1rem' }}>Customer</th>
                <th style={{ padding: '0.75rem 1rem' }}>Amount</th>
                <th style={{ padding: '0.75rem 1rem', minWidth: '220px' }}>AI Root Cause Diagnosis</th>
                <th style={{ padding: '0.75rem 1rem' }}>Recommended Action</th>
                <th style={{ padding: '0.75rem 1rem' }}>Risk Score</th>
                <th style={{ padding: '0.75rem 1rem' }}>Status</th>
                <th style={{ padding: '0.75rem 1rem', textAlign: 'right', minWidth: '130px' }}>Agent Recovery</th>
              </tr>
            </thead>
            <tbody>
              {filteredPayments.map((payment) => {
                const isRecovered = payment.recoveryStatus === 'RECOVERED'
                const isHighRisk = payment.riskLevel === 'HIGH'
                const isCapped = (payment.retryCount || 0) >= (payment.maxRetries || 3)
                const canRetry = !isRecovered && !isHighRisk && !isCapped
                const isLoading = Boolean(rowLoading[payment.id])

                return (
                  <tr
                    key={payment.id}
                    onClick={() => onSelectPayment(payment)}
                    className="neu-table-row"
                    style={{
                      cursor: 'pointer',
                      transition: 'var(--transition-smooth)'
                    }}
                  >
                    <td style={{ padding: '1rem', borderTopLeftRadius: 'var(--radius-md)', borderBottomLeftRadius: 'var(--radius-md)' }}>
                      <span className="code-pill">{payment.id}</span>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                        {payment.timestamp}
                      </div>
                    </td>

                    <td style={{ padding: '1rem' }}>
                      <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{payment.customerName}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{payment.customerEmail}</div>
                    </td>

                    <td style={{ padding: '1rem' }}>
                      <div style={{ fontWeight: 800, fontSize: '1rem', color: 'var(--text-primary)' }}>
                        ₹{payment.amount.toLocaleString('en-IN')}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        {payment.currency}
                      </div>
                    </td>

                    <td style={{ padding: '1rem', maxWidth: '280px' }}>
                      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.35rem' }}>
                        <Zap size={14} color="var(--accent-primary)" style={{ marginTop: '2px', flexShrink: 0 }} />
                        <div>
                          <div
                            style={{
                              fontSize: '0.8125rem',
                              color: 'var(--text-primary)',
                              fontWeight: 600,
                              lineHeight: 1.35
                            }}
                            title={payment.aiDiagnosis}
                          >
                            {payment.aiDiagnosis ? (
                              payment.aiDiagnosis.length > 70 
                                ? `${payment.aiDiagnosis.slice(0, 70)}...` 
                                : payment.aiDiagnosis
                            ) : payment.failureReason}
                          </div>
                          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                            Code: <span className="code-pill" style={{ fontSize: '0.68rem', padding: '0.1rem 0.35rem' }}>{payment.failureCode}</span>
                          </div>
                        </div>
                      </div>
                    </td>

                    <td style={{ padding: '1rem' }}>
                      <span
                        className="neu-badge"
                        style={{
                          fontSize: '0.72rem',
                          fontWeight: 700,
                          padding: '0.25rem 0.6rem',
                          background: isHighRisk 
                            ? 'rgba(239, 68, 68, 0.12)' 
                            : isRecovered 
                              ? 'rgba(16, 185, 129, 0.12)' 
                              : 'rgba(99, 102, 241, 0.12)',
                          color: isHighRisk 
                            ? 'var(--accent-rose)' 
                            : isRecovered 
                              ? 'var(--accent-emerald)' 
                              : 'var(--accent-primary)',
                          border: `1px solid ${isHighRisk ? 'var(--accent-rose)' : isRecovered ? 'var(--accent-emerald)' : 'var(--accent-primary)'}`
                        }}
                      >
                        {payment.recommendedAction || (isHighRisk ? 'ESCALATE_TO_HUMAN' : 'DIRECT_GATEWAY_RETRY')}
                      </span>
                    </td>

                    <td style={{ padding: '1rem' }}>
                      <RiskScoreBadge riskLevel={payment.riskLevel} score={payment.riskScore} />
                    </td>

                    <td style={{ padding: '1rem' }}>
                      <StatusPill status={payment.recoveryStatus} />
                    </td>

                    <td
                      style={{
                        padding: '1rem',
                        textAlign: 'right',
                        borderTopRightRadius: 'var(--radius-md)',
                        borderBottomRightRadius: 'var(--radius-md)'
                      }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '0.5rem' }}>
                        {canRetry ? (
                          <button
                            onClick={(e) => handleQuickRetry(e, payment)}
                            disabled={isLoading}
                            className="neu-btn neu-btn-primary"
                            style={{ padding: '0.35rem 0.75rem', fontSize: '0.75rem', fontWeight: 700 }}
                            title="Execute LangGraph Autonomous Recovery"
                          >
                            <RefreshCw size={13} className={isLoading ? 'spin-anim' : ''} />
                            {isLoading ? 'Retrying...' : 'Auto-Retry'}
                          </button>
                        ) : isRecovered ? (
                          <span
                            style={{
                              fontSize: '0.75rem',
                              fontWeight: 700,
                              color: 'var(--accent-emerald)',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '0.25rem'
                            }}
                          >
                            <CheckCircle2 size={15} /> Recovered
                          </span>
                        ) : (
                          <button
                            onClick={() => onSelectPayment(payment)}
                            className="neu-btn"
                            style={{ padding: '0.35rem 0.65rem', fontSize: '0.75rem' }}
                          >
                            Triage
                          </button>
                        )}

                        <button
                          onClick={() => onSelectPayment(payment)}
                          className="neu-btn neu-btn-icon"
                          style={{ width: '30px', height: '30px' }}
                          title="View Full AI Diagnosis & State Machine"
                        >
                          <ChevronRight size={15} />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
