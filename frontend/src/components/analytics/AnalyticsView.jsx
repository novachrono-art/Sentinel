import React from 'react'
import { BarChart3, TrendingUp, ShieldCheck, CheckCircle2, AlertOctagon, Inbox } from 'lucide-react'
import MetricCard from '../ui/MetricCard'
import EmptyState from '../ui/EmptyState'

export default function AnalyticsView({ payments = [] }) {
  // If no data exists, show an honest empty state with zero values
  if (!payments || payments.length === 0) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        <div className="dashboard-grid">
          <MetricCard
            title="Total Ingested Failures"
            value="0"
            subtitle="No transactions ingested"
            icon={AlertOctagon}
            color="var(--accent-rose)"
          />
          <MetricCard
            title="Recovered Revenue"
            value="₹0"
            subtitle="0.0% Recovery Rate"
            icon={TrendingUp}
            color="var(--accent-emerald)"
            progress={0}
          />
          <MetricCard
            title="Safe Recovery Rate"
            value="0.0%"
            subtitle="0 evaluated transactions"
            icon={ShieldCheck}
            color="var(--accent-primary)"
            progress={0}
          />
          <MetricCard
            title="Average Retries"
            value="0.0"
            subtitle="Max limit: 3"
            icon={CheckCircle2}
            color="var(--accent-cyan)"
          />
        </div>
        <EmptyState
          title="No Analytics Data Available"
          message="Analytics will dynamically compute from live payment failures once data is ingested."
        />
      </div>
    )
  }

  // Dynamic calculations derived strictly from current payments state
  const totalCount = payments.length
  const totalVolume = payments.reduce((sum, p) => sum + (p.amount || 0), 0)
  const atRiskPayments = payments.filter(p => p.recoveryStatus !== 'RECOVERED' && p.status !== 'CAPTURED')
  const totalAmountAtRisk = atRiskPayments.reduce((sum, p) => sum + (p.amount || 0), 0)
  
  const recoveredPayments = payments.filter(p => p.recoveryStatus === 'RECOVERED' || p.status === 'CAPTURED')
  const recoveredAmount = recoveredPayments.reduce((sum, p) => sum + (p.amount || 0), 0)
  const recoveryRate = totalVolume > 0 ? ((recoveredAmount / totalVolume) * 100) : 0

  const safePayments = payments.filter(p => p.riskLevel === 'LOW')
  const safeAmount = safePayments.reduce((sum, p) => sum + (p.amount || 0), 0)
  const safeRate = totalCount > 0 ? ((safePayments.length / totalCount) * 100) : 0

  const attemptedPayments = payments.filter(p => p.retryCount > 0)
  const totalRetries = payments.reduce((sum, p) => sum + (p.retryCount || 0), 0)
  const avgRetries = attemptedPayments.length > 0 ? (totalRetries / attemptedPayments.length).toFixed(1) : '0.0'

  // Dynamic failure breakdown grouped by failureCode / failureReason
  const reasonMap = {}
  payments.forEach(p => {
    const key = p.failureCode || 'UNKNOWN'
    if (!reasonMap[key]) {
      reasonMap[key] = { label: p.failureCode || 'Unknown', count: 0, sampleReason: p.failureReason }
    }
    reasonMap[key].count += 1
  })

  const colors = [
    'var(--accent-primary)',
    'var(--accent-cyan)',
    'var(--accent-violet)',
    'var(--accent-amber)',
    'var(--accent-rose)'
  ]

  const failureDistribution = Object.values(reasonMap).map((item, index) => ({
    label: item.label.replace(/_/g, ' '),
    count: item.count,
    percentage: totalCount > 0 ? Math.round((item.count / totalCount) * 100) : 0,
    color: colors[index % colors.length]
  }))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Top High-level KPIs - 100% Computed Dynamically */}
      <div className="dashboard-grid">
        <MetricCard
          title="Total Ingested Failures"
          value={totalCount.toString()}
          subtitle="Active Dataset"
          icon={AlertOctagon}
          color="var(--accent-rose)"
        />
        <MetricCard
          title="Recovered Revenue"
          value={`₹${recoveredAmount.toLocaleString('en-IN')}`}
          subtitle={`${recoveryRate.toFixed(1)}% of total revenue at risk`}
          icon={TrendingUp}
          color="var(--accent-emerald)"
          progress={recoveryRate}
        />
        <MetricCard
          title="Low-Risk Qualification"
          value={`${safeRate.toFixed(1)}%`}
          subtitle={`${safePayments.length} of ${totalCount} transactions`}
          icon={ShieldCheck}
          color="var(--accent-primary)"
          progress={safeRate}
        />
        <MetricCard
          title="Average Retries per Recovery"
          value={avgRetries}
          subtitle="Max limit: 3 attempts"
          icon={CheckCircle2}
          color="var(--accent-cyan)"
        />
      </div>

      {/* Dynamic Failure Breakdown & Pipeline */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '1.5rem' }}>
        {/* Dynamic Failure Distribution */}
        <div className="neu-card">
          <h3 style={{ fontSize: '1.1rem', fontWeight: 800, marginBottom: '1.25rem' }}>
            Failure Reason Distribution
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {failureDistribution.map((item, idx) => (
              <div key={idx}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8125rem', marginBottom: '0.35rem' }}>
                  <span style={{ fontWeight: 600 }}>{item.label}</span>
                  <span style={{ color: 'var(--text-muted)' }}>
                    {item.count} {item.count === 1 ? 'case' : 'cases'} ({item.percentage}%)
                  </span>
                </div>
                <div
                  style={{
                    height: '8px',
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
                      width: `${item.percentage}%`,
                      background: item.color,
                      borderRadius: '999px'
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Dynamic Funnel & Conversion */}
        <div className="neu-card">
          <h3 style={{ fontSize: '1.1rem', fontWeight: 800, marginBottom: '1.25rem' }}>
            Revenue Recovery Pipeline
          </h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div className="neu-card-inset">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <span className="metric-label">Stage 1: Ingested Revenue at Risk</span>
                  <div style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--accent-rose)', marginTop: '0.2rem' }}>
                    ₹{totalAmountAtRisk.toLocaleString('en-IN')}
                  </div>
                </div>
                <span className="code-pill">100% Ingested</span>
              </div>
            </div>

            <div className="neu-card-inset">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <span className="metric-label">Stage 2: Low-Risk Recoverable Sum</span>
                  <div style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--accent-primary)', marginTop: '0.2rem' }}>
                    ₹{safeAmount.toLocaleString('en-IN')}
                  </div>
                </div>
                <span className="code-pill">
                  {totalAmountAtRisk > 0 ? ((safeAmount / totalAmountAtRisk) * 100).toFixed(1) : 0}% Qualified
                </span>
              </div>
            </div>

            <div className="neu-card-inset">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <span className="metric-label">Stage 3: Successfully Recovered</span>
                  <div style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--accent-emerald)', marginTop: '0.2rem' }}>
                    ₹{recoveredAmount.toLocaleString('en-IN')}
                  </div>
                </div>
                <span className="code-pill">
                  {totalAmountAtRisk > 0 ? ((recoveredAmount / totalAmountAtRisk) * 100).toFixed(1) : 0}% Conversion
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
