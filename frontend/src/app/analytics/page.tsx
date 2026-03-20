'use client';

import { useState, useEffect } from 'react';
import Header from '@/components/Header';
import { getAnalyticsFromBackend } from '@/lib/api';
import type { AnalyticsData, CycleProfile, SegmentConcentration } from '@/lib/types';

export default function AnalyticsPage() {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const res = await getAnalyticsFromBackend();
        setData(res);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load analytics');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', background: '#F8F9FA' }}>
        <Header />
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 'calc(100vh - 56px)' }}>
          <div style={{ textAlign: 'center' }}>
            <div className="loader" style={{ 
              width: 40, height: 40, border: '3px solid #E2E8F0', borderTopColor: '#3B82F6', 
              borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto 16px' 
            }} />
            <p style={{ color: '#64748B', fontWeight: 500 }}>Loading intelligence dashboard...</p>
          </div>
        </div>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ minHeight: '100vh', background: '#F8F9FA' }}>
        <Header />
        <div style={{ padding: 40, maxWidth: 800, margin: '0 auto' }}>
          <div style={{ background: '#FEF2F2', border: '1px solid #FEE2E2', padding: 24, borderRadius: 12 }}>
            <h2 style={{ color: '#991B1B', marginTop: 0 }}>Analytics Error</h2>
            <p style={{ color: '#B91C1C' }}>{error}</p>
            <button 
              onClick={() => window.location.reload()}
              style={{ background: '#991B1B', color: '#fff', border: 'none', padding: '10px 20px', borderRadius: 8, cursor: 'pointer', fontWeight: 600 }}
            >
              Retry Connection
            </button>
          </div>
        </div>
      </div>
    );
  }

  const cycleProfiles = data ? Object.values(data.cycle_profiles).sort((a, b) => b.p90_days - a.p90_days) : [];
  const concentrationSegments = data ? data.concentration_segments.sort((a, b) => b.hhi - a.hhi) : [];
  const topCycleP90 = cycleProfiles.length ? Math.max(...cycleProfiles.map((p) => p.p90_days)) : 1;
  const topHHI = concentrationSegments.length ? Math.max(...concentrationSegments.map((s) => s.hhi)) : 1;
  const avgOnTime = cycleProfiles.length
    ? Math.round(cycleProfiles.reduce((sum, p) => sum + p.pct_on_time, 0) / cycleProfiles.length)
    : 0;
  const highRiskSegments = concentrationSegments.filter((s) => s.hhi_label === 'HIGHLY_CONCENTRATED').length;
  const improvingCycles = cycleProfiles.filter((p) => p.trend_direction === 'IMPROVING').length;
  const cyclePreview = cycleProfiles.slice(0, 5);
  const concentrationPreview = concentrationSegments.slice(0, 6);

  return (
    <div style={{ minHeight: '100vh', background: '#F8F9FA', color: '#1E293B', fontFamily: 'Inter, sans-serif' }}>
      <Header />
      
      <main style={{ maxWidth: 1400, margin: '0 auto', padding: '32px 24px 56px' }}>
        {/* Hero Section */}
        <section style={{ marginBottom: 40 }}>
          <h1 style={{ fontSize: 32, fontWeight: 800, color: '#0F172A', marginBottom: 8, letterSpacing: '-0.02em' }}>
            Historical Intelligence Dashboard
          </h1>
          <p style={{ color: '#64748B', fontSize: 16, maxWidth: 700 }}>
            Real-time analytics derived from historical procurement awards and request cycles. 
            These metrics drive our automated SLA predictions and risk monitoring.
          </p>
        </section>

        {/* Quick KPI Cards */}
        <section
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: 16,
            marginBottom: 24,
          }}
        >
          <div style={{ background: '#fff', borderRadius: 16, border: '1px solid #E2E8F0', padding: 18, boxShadow: '0 6px 20px rgba(15,23,42,0.04)' }}>
            <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: '#64748B', textTransform: 'uppercase' }}>Avg on-time</p>
            <p style={{ margin: '10px 0 6px', fontSize: 28, fontWeight: 800, color: '#0F172A' }}>{avgOnTime}%</p>
            <div style={{ height: 6, borderRadius: 999, background: '#E2E8F0', overflow: 'hidden' }}>
              <div style={{ width: `${Math.min(avgOnTime, 100)}%`, height: '100%', background: avgOnTime >= 80 ? '#10B981' : '#F59E0B' }} />
            </div>
          </div>
          <div style={{ background: '#fff', borderRadius: 16, border: '1px solid #E2E8F0', padding: 18, boxShadow: '0 6px 20px rgba(15,23,42,0.04)' }}>
            <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: '#64748B', textTransform: 'uppercase' }}>Improving cycles</p>
            <p style={{ margin: '10px 0 6px', fontSize: 28, fontWeight: 800, color: '#0F172A' }}>{improvingCycles}</p>
            <p style={{ margin: 0, color: '#64748B', fontSize: 13 }}>of {cycleProfiles.length} targets</p>
          </div>
          <div style={{ background: '#fff', borderRadius: 16, border: '1px solid #E2E8F0', padding: 18, boxShadow: '0 6px 20px rgba(15,23,42,0.04)' }}>
            <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: '#64748B', textTransform: 'uppercase' }}>High concentration risk</p>
            <p style={{ margin: '10px 0 6px', fontSize: 28, fontWeight: 800, color: '#0F172A' }}>{highRiskSegments}</p>
            <p style={{ margin: 0, color: '#64748B', fontSize: 13 }}>segments above healthy range</p>
          </div>
          <div style={{ background: '#fff', borderRadius: 16, border: '1px solid #E2E8F0', padding: 18, boxShadow: '0 6px 20px rgba(15,23,42,0.04)' }}>
            <p style={{ margin: 0, fontSize: 12, fontWeight: 700, color: '#64748B', textTransform: 'uppercase' }}>Tracked segments</p>
            <p style={{ margin: '10px 0 6px', fontSize: 28, fontWeight: 800, color: '#0F172A' }}>{concentrationSegments.length}</p>
            <p style={{ margin: 0, color: '#64748B', fontSize: 13 }}>active category-region clusters</p>
          </div>
        </section>

        {/* Mini Visualizations */}
        <section
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
            gap: 16,
            marginBottom: 28,
          }}
        >
          <div style={{ background: '#fff', borderRadius: 16, border: '1px solid #E2E8F0', padding: 20, boxShadow: '0 6px 20px rgba(15,23,42,0.04)' }}>
            <h3 style={{ margin: 0, marginBottom: 12, fontSize: 16, color: '#0F172A' }}>P90 cycle duration overview</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {cyclePreview.map((p) => {
                const width = Math.max(8, (p.p90_days / topCycleP90) * 100);
                return (
                  <div key={`viz-${p.escalation_target}`}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, gap: 12 }}>
                      <span style={{ fontSize: 12, color: '#334155', maxWidth: 220, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {p.escalation_target === 'baseline' ? 'Automated Pipeline' : p.escalation_target}
                      </span>
                      <span style={{ fontSize: 12, color: '#0F172A', fontWeight: 700 }}>{p.p90_days}d</span>
                    </div>
                    <div style={{ background: '#E2E8F0', borderRadius: 999, height: 8 }}>
                      <div
                        style={{
                          height: 8,
                          borderRadius: 999,
                          width: `${width}%`,
                          background: 'linear-gradient(90deg, #60A5FA 0%, #3B82F6 100%)',
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div style={{ background: '#fff', borderRadius: 16, border: '1px solid #E2E8F0', padding: 20, boxShadow: '0 6px 20px rgba(15,23,42,0.04)' }}>
            <h3 style={{ margin: 0, marginBottom: 12, fontSize: 16, color: '#0F172A' }}>Top supplier dependency</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 10 }}>
              {concentrationPreview.map((s, i) => {
                const pct = Math.min(Math.max(s.top_supplier_share_pct, 0), 100);
                return (
                  <div key={`donut-${s.category_l2}-${s.region}-${i}`} style={{ border: '1px solid #EEF2FF', borderRadius: 12, padding: 10, background: '#F8FAFC' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div
                        style={{
                          width: 38,
                          height: 38,
                          borderRadius: '50%',
                          background: `conic-gradient(#7C3AED ${pct}%, #E2E8F0 0%)`,
                          position: 'relative',
                          flexShrink: 0,
                        }}
                      >
                        <div
                          style={{
                            position: 'absolute',
                            inset: 6,
                            borderRadius: '50%',
                            background: '#fff',
                          }}
                        />
                      </div>
                      <div style={{ minWidth: 0 }}>
                        <p style={{ margin: 0, fontSize: 11, color: '#334155', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {s.category_l2}
                        </p>
                        <p style={{ margin: 0, fontSize: 11, color: '#64748B' }}>{s.region}</p>
                      </div>
                    </div>
                    <p style={{ margin: '8px 0 0', fontSize: 12, fontWeight: 700, color: '#0F172A' }}>{pct.toFixed(1)}% top-share</p>
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        {/* Data Tables */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(600px, 1fr))', gap: 32 }}>
          
          {/* Section 1: Escalation Cycles */}
          <section style={{ 
            background: 'rgba(255, 255, 255, 0.7)', 
            backdropFilter: 'blur(12px)', 
            borderRadius: 20, 
            border: '1px solid rgba(255, 255, 255, 0.3)',
            boxShadow: '0 8px 32px rgba(0,0,0,0.04)',
            padding: 24
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
              <div style={{ background: '#DBEAFE', color: '#2563EB', width: 40, height: 40, borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              </div>
              <h2 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>Escalation Cycle Insights</h2>
            </div>

            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #E2E8F0', textAlign: 'left' }}>
                    <th style={{ padding: '12px 8px', color: '#64748B', fontWeight: 600 }}>TARGET</th>
                    <th style={{ padding: '12px 8px', color: '#64748B', fontWeight: 600 }}>N</th>
                    <th style={{ padding: '12px 8px', color: '#64748B', fontWeight: 600 }}>MEDIAN</th>
                    <th style={{ padding: '12px 8px', color: '#64748B', fontWeight: 600 }}>P90</th>
                    <th style={{ padding: '12px 8px', color: '#64748B', fontWeight: 600 }}>SLA %</th>
                    <th style={{ padding: '12px 8px', color: '#64748B', fontWeight: 600 }}>TREND</th>
                  </tr>
                </thead>
                <tbody>
                  {cycleProfiles.map((p) => (
                    <tr key={p.escalation_target} style={{ borderBottom: '1px solid #F1F5F9', transition: 'background 0.2s' }}>
                      <td style={{ padding: '16px 8px', fontWeight: 600, color: '#0F172A' }}>
                        {p.escalation_target === 'baseline' ? 'Automated Pipeline (Baseline)' : p.escalation_target}
                        {p.insufficient_data && <span style={{ marginLeft: 8, fontSize: 10, background: '#F1F5F9', color: '#94A3B8', padding: '2px 6px', borderRadius: 4 }}>Low N</span>}
                      </td>
                      <td style={{ padding: '16px 8px', color: '#475569' }}>{p.n}</td>
                      <td style={{ padding: '16px 8px', color: '#0F172A', fontWeight: 600 }}>{p.median_days}d</td>
                      <td style={{ padding: '16px 8px', color: '#0F172A' }}>{p.p90_days}d</td>
                      <td style={{ padding: '16px 8px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ 
                            color: p.pct_on_time > 85 ? '#059669' : p.pct_on_time > 70 ? '#D97706' : '#DC2626',
                            fontWeight: 700
                          }}>
                            {p.pct_on_time}%
                          </span>
                        </div>
                      </td>
                      <td style={{ padding: '16px 8px' }}>
                        <div style={{ 
                          display: 'inline-flex', alignItems: 'center', gap: 4, 
                          padding: '4px 8px', borderRadius: 20, fontSize: 11, fontWeight: 700,
                          background: p.trend_direction === 'IMPROVING' ? '#ECFDF5' : p.trend_direction === 'WORSENING' ? '#FEF2F2' : '#F8F9FA',
                          color: p.trend_direction === 'IMPROVING' ? '#059669' : p.trend_direction === 'WORSENING' ? '#DC2626' : '#64748B'
                        }}>
                          {p.trend_direction === 'IMPROVING' ? '▼' : p.trend_direction === 'WORSENING' ? '▲' : '─'}
                          {Math.abs(p.trend_delta_days)}d
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* Section 2: Portfolio Concentration (HHI) */}
          <section style={{ 
            background: 'rgba(255, 255, 255, 0.7)', 
            backdropFilter: 'blur(12px)', 
            borderRadius: 20, 
            border: '1px solid rgba(255, 255, 255, 0.3)',
            boxShadow: '0 8px 32px rgba(0,0,0,0.04)',
            padding: 24
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
              <div style={{ background: '#FDF2F8', color: '#DB2777', width: 40, height: 40, borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M16 8v8m-4-5v5m-4-2v2m-2 4h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>
              </div>
              <h2 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>Supplier Concentration Risk</h2>
            </div>

            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #E2E8F0', textAlign: 'left' }}>
                    <th style={{ padding: '12px 8px', color: '#64748B', fontWeight: 600 }}>SEGMENT (Cat / Region)</th>
                    <th style={{ padding: '12px 8px', color: '#64748B', fontWeight: 600 }}>HHI</th>
                    <th style={{ padding: '12px 8px', color: '#64748B', fontWeight: 600 }}>TOP SUPPLIER</th>
                    <th style={{ padding: '12px 8px', color: '#64748B', fontWeight: 600 }}>SHARE</th>
                    <th style={{ padding: '12px 8px', color: '#64748B', fontWeight: 600 }}>STATUS</th>
                  </tr>
                </thead>
                <tbody>
                  {concentrationSegments.map((s, idx) => (
                    <tr key={idx} style={{ borderBottom: '1px solid #F1F5F9', transition: 'background 0.2s' }}>
                      <td style={{ padding: '16px 8px' }}>
                        <div style={{ fontWeight: 600, color: '#0F172A' }}>{s.category_l2}</div>
                        <div style={{ fontSize: 11, color: '#94A3B8' }}>{s.region}</div>
                      </td>
                      <td style={{ padding: '16px 8px', fontWeight: 700, color: '#334155' }}>{s.hhi.toLocaleString()}</td>
                      <td style={{ padding: '16px 8px', color: '#475569' }}>{s.top_supplier_name}</td>
                      <td style={{ padding: '16px 8px', color: '#0F172A', fontWeight: 600 }}>{s.top_supplier_share_pct.toFixed(1)}%</td>
                      <td style={{ padding: '16px 8px' }}>
                        <div style={{ 
                          display: 'inline-flex', padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 700,
                          background: s.hhi_label === 'COMPETITIVE' ? '#ECFDF5' : s.hhi_label === 'MODERATE' ? '#FFFBEB' : '#FEF2F2',
                          color: s.hhi_label === 'COMPETITIVE' ? '#059669' : s.hhi_label === 'MODERATE' ? '#D97706' : '#DC2626'
                        }}>
                          {s.hhi_label}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

        </div>
      </main>
      
      <style>{`
        body { margin: 0; }
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #F8F9FA; }
        ::-webkit-scrollbar-thumb { background: #CBD5E1; borderRadius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #94A3B8; }
      `}</style>
    </div>
  );
}
