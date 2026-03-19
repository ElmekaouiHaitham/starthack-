'use client';

import { useState } from 'react';
import type { AnalysisResult, SupplierResult, PolicyRule, Escalation, AuditEntry, BackendResult } from '@/lib/types';

// ”€”€ Utility ”€”€
function h(s: unknown): string {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function Badge({ type, children }: { type: 'ok' | 'warn' | 'err' | 'info' | 'neutral'; children: React.ReactNode }) {
  const cls = { ok: 'badge-ok', warn: 'badge-warn', err: 'badge-err', info: 'badge-info', neutral: 'badge-neutral' }[type];
  return <span className={`badge ${cls}`}>{children}</span>;
}

// ”€”€ Step card shell ”€”€
// Uses a left-border colored strip instead of full outline tinting to reduce visual noise
function StepCard({
  num, numColor, title, sub, badge, badgeType, children,
}: {
  num: number | string; numColor: string; title: string; sub: string;
  badge: string; badgeType: 'ok' | 'warn' | 'err' | 'info' | 'neutral';
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  const borderCls = badgeType === 'err' ? 'step-card-err' : badgeType === 'warn' ? 'step-card-warn' : badgeType === 'ok' ? 'step-card-ok' : '';

  return (
    <div className={`step-card ${borderCls}`}>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '9px 13px', cursor: 'pointer', userSelect: 'none',
          background: '#F8FAFC',
          borderBottom: open ? '1px solid #E2E8F0' : 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          {/* Step number disc */}
          <div style={{
            width: 22, height: 22, borderRadius: '50%',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 10.5, fontWeight: 700, flexShrink: 0,
            background: numColor, color: '#fff',
          }}>{num}</div>
          <div>
            <div style={{ fontWeight: 600, fontSize: 12.5, color: '#0F172A' }}>{title}</div>
            <div style={{ fontSize: 10, color: '#94A3B8', marginTop: 1 }}>{sub}</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <Badge type={badgeType}>{badge}</Badge>
          <span style={{ color: '#CBD5E1', fontSize: 10, transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}>▼</span>
        </div>
      </div>
      {open && <div style={{ padding: '12px 14px' }}>{children}</div>}
    </div>
  );
}

// ”€”€ Shared micro-components ”€”€

// KV field: no box outlines, just a simple label + value pair in a grid
function KVField({ label, val, warnNull }: { label: string; val: string | null; warnNull?: boolean }) {
  const isEmpty = val == null || val === '' || val === 'null' || val === 'undefined';
  return (
    <div className="kv-item">
      <div className="kv-label">{label}</div>
      {isEmpty
        ? <div className="kv-null-soft">{warnNull ? <span className="kv-null">—</span> : '—'}</div>
        : <div className="kv-value">{String(val)}</div>
      }
    </div>
  );
}

// ”€”€ Step 1: Parsing ”€”€
function ParsedRequestCard({ data, compat }: { data: AnalysisResult['request_parsed'], compat: AnalysisResult['compatibility'] }) {
  const status = compat.overall_status;
  const numColor = status === 'error' ? '#DC2626' : status === 'warning' ? '#B45309' : '#059669';
  const badgeType = status === 'error' ? 'err' : status === 'warning' ? 'warn' : 'ok';
  const badgeText = status === 'error' ? 'ISSUES FOUND' : status === 'warning' ? 'WARNINGS' : 'COMPATIBLE';

  return (
    <StepCard num={1} numColor={numColor} title="Request Parsing & Compatibility"
      sub="NLP extraction · field validation · consistency check"
      badge={badgeText} badgeType={badgeType}>

      {/* ”€”€ Tight KV grid: no individual card borders ”€”€ */}
      <div className="kv-grid" style={{ border: '1px solid #E2E8F0', borderRadius: 4, overflow: 'hidden', marginBottom: 14 }}>
        <KVField label="Item" val={data.item} />
        <KVField label="Category" val={`${data.category_l1 || '—'} / ${data.category_l2 || '—'}`} />
        <KVField label="Quantity" val={data.quantity != null ? `${data.quantity} ${data.unit}` : null} warnNull />
        <KVField label="Budget" val={data.budget_amount != null ? `${Number(data.budget_amount).toLocaleString()} ${data.currency}` : null} warnNull />
        <KVField label="Deadline" val={data.deadline_iso || (data.deadline_days_from_today != null ? `In ${data.deadline_days_from_today} days` : null)} />
        <KVField label="Country" val={data.country} />
        <KVField label="Preferred Supplier" val={data.preferred_supplier_mentioned} />
        <KVField label="Business Unit" val={data.business_unit} />
      </div>

      {/* ”€”€ Issues ”€”€ */}
      <div style={{ fontSize: 9.5, letterSpacing: '0.08em', color: '#6B7280', textTransform: 'uppercase', marginBottom: 7, fontWeight: 600 }}>
        Detected Issues
      </div>
      {compat.issues.length === 0 ? (
        <div style={{ color: '#059669', fontSize: 12, display: 'flex', alignItems: 'center', gap: 5 }}>
          <span>✓</span> No compatibility issues detected
        </div>
      ) : (
        compat.issues.map((issue, i) => {
          const color = issue.severity === 'error' ? '#DC2626' : issue.severity === 'warning' ? '#B45309' : '#1D4ED8';
          const bg = issue.severity === 'error' ? 'rgba(220,38,38,0.05)' : issue.severity === 'warning' ? 'rgba(180,83,9,0.05)' : 'rgba(29,78,216,0.05)';
          const icon = issue.severity === 'error' ? '✗' : issue.severity === 'warning' ? '!' : 'i';
          return (
            <div key={i} style={{
              display: 'flex', gap: 9, padding: '8px 10px', borderRadius: 3, marginBottom: 5,
              background: bg, borderLeft: `2px solid ${color}`,
            }}>
              <div style={{
                fontSize: 11, color: '#fff', flexShrink: 0, width: 16, height: 16, borderRadius: '50%',
                background: color, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, marginTop: 1,
              }}>{icon}</div>
              <div>
                <div style={{ fontSize: 9, letterSpacing: '0.08em', textTransform: 'uppercase', color: '#6B7280', marginBottom: 2, fontWeight: 600 }}>{issue.field}</div>
                <div style={{ fontSize: 11.5, color: '#0F172A', lineHeight: 1.5 }}>{issue.description}</div>
                {issue.detected_value && <div style={{ fontSize: 10, color: '#6B7280', marginTop: 2 }}>Detected: {issue.detected_value}</div>}
                {issue.expected && <div style={{ fontSize: 10, color: '#6B7280', marginTop: 1 }}>Expected: {issue.expected}</div>}
              </div>
            </div>
          );
        })
      )}
    </StepCard>
  );
}

// ”€”€ Step 2: Policy ”€”€
function PolicyCard({ rules }: { rules: PolicyRule[] }) {
  const fails = rules.filter(r => r.status === 'fail').length;
  const warns = rules.filter(r => r.status === 'warning').length;
  const numColor = fails ? '#DC2626' : warns ? '#B45309' : '#059669';
  const badgeType: 'err' | 'warn' | 'ok' = fails ? 'err' : warns ? 'warn' : 'ok';
  const badgeText = fails ? `${fails} VIOLATION${fails > 1 ? 'S' : ''}` : warns ? `${warns} WARNING${warns > 1 ? 'S' : ''}` : `${rules.length} PASSED`;

  return (
    <StepCard num={2} numColor={numColor} title="Policy Evaluation"
      sub="Approval thresholds · restricted suppliers · category rules"
      badge={badgeText} badgeType={badgeType}>
      {rules.map((rule, idx) => {
        const dot = rule.status === 'pass' ? '#059669' : rule.status === 'warning' ? '#B45309' : '#DC2626';
        return (
          <div key={rule.rule_id} style={{
            display: 'grid', gridTemplateColumns: '1fr 10px', gap: 10, alignItems: 'start',
            padding: '8px 0', borderBottom: idx < rules.length - 1 ? '1px solid #F1F5F9' : 'none',
          }}>
            <div>
              <div style={{ fontSize: 9, letterSpacing: '0.06em', color: '#94A3B8', marginBottom: 2, textTransform: 'uppercase' }}>{rule.rule_id}</div>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#0F172A', marginBottom: 2 }}>{rule.rule_name}</div>
              <div style={{ fontSize: 11, color: '#4B5563', lineHeight: 1.5 }}>{rule.description}</div>
              {rule.status !== 'pass' && rule.impact && (
                <div style={{ fontSize: 10, color: '#DC2626', marginTop: 3 }}>⚡ {rule.impact}</div>
              )}
            </div>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: dot, marginTop: 5, flexShrink: 0 }} />
          </div>
        );
      })}
    </StepCard>
  );
}

// ”€”€ Step 3: Suppliers ”€”€
function SupplierCard({ suppliers }: { suppliers: SupplierResult[] }) {
  const compliant = suppliers.filter(s => s.status === 'compliant').length;
  const numColor = compliant > 0 ? '#059669' : '#DC2626';
  const badgeType: 'ok' | 'err' = compliant > 0 ? 'ok' : 'err';

  return (
    <StepCard num={3} numColor={numColor} title="Supplier Analysis"
      sub="Pricing tiers · scoring · compliance status"
      badge={`${compliant} COMPLIANT / ${suppliers.length} EVALUATED`} badgeType={badgeType}>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: '#F8FAFC', borderBottom: '1px solid #E2E8F0' }}>
              {['#', 'Supplier', 'Unit', 'Total', 'Lead', 'Quality', 'Status'].map((col, i) => (
                <th key={col} style={{
                  fontSize: 9, letterSpacing: '0.08em', textTransform: 'uppercase',
                  color: '#6B7280', padding: '6px 8px', textAlign: 'left', fontWeight: 600,
                  whiteSpace: 'nowrap', borderBottom: '1px solid #E2E8F0',
                }}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {suppliers.map((s, rowIdx) => {
              const isRestricted = s.restricted || s.status === 'restricted';
              const isRecommended = s.rank === 1 && s.status === 'compliant';
              const rowBg = isRecommended ? 'rgba(5,150,105,0.03)' : 'transparent';
              const opacity = isRestricted ? 0.5 : 1;
              const qColor = s.quality_score >= 85 ? '#059669' : s.quality_score >= 70 ? '#B45309' : '#DC2626';

              const statusBadge = s.status === 'compliant' ? <Badge type="ok">compliant</Badge>
                : s.status === 'restricted' ? <Badge type="err">restricted</Badge>
                : <Badge type="warn">{s.status.replace('_', ' ')}</Badge>;

              return (
                <tr key={s.supplier_id} style={{ background: rowBg, opacity, borderBottom: rowIdx < suppliers.length - 1 ? '1px solid #F1F5F9' : 'none' }}>
                  {/* Rank */}
                  <td style={{ padding: '8px 8px', verticalAlign: 'top' }}>
                    <span style={{
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                      width: 19, height: 19, borderRadius: 3, fontSize: 10, fontWeight: 700,
                      background: isRecommended && !isRestricted ? '#0F172A' : '#F1F5F9',
                      color: isRecommended && !isRestricted ? '#fff' : '#6B7280',
                    }}>
                      {isRestricted ? '✗' : s.rank}
                    </span>
                  </td>
                  {/* Name */}
                  <td style={{ padding: '8px 8px', verticalAlign: 'top', minWidth: 150 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
                      <span style={{ fontWeight: 500, color: '#0F172A' }}>{s.name}</span>
                      {s.preferred && <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 2, background: 'rgba(15,23,42,0.07)', color: '#374151', fontWeight: 600, border: '1px solid rgba(15,23,42,0.12)' }}>PREFERRED</span>}
                      {isRestricted && <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 2, background: 'rgba(220,38,38,0.1)', color: '#DC2626', fontWeight: 600, border: '1px solid rgba(220,38,38,0.2)' }}>RESTRICTED</span>}
                    </div>
                    <div style={{ fontSize: 10, color: '#94A3B8', marginTop: 2, lineHeight: 1.4, maxWidth: 210 }}>
                      {isRestricted ? (s.exclusion_reason || s.rationale) : s.rationale}
                    </div>
                  </td>
                  {/* Unit price */}
                  <td style={{ padding: '8px 8px', verticalAlign: 'top', whiteSpace: 'nowrap', color: '#374151' }}>
                    {s.unit_price != null ? `${Number(s.unit_price).toLocaleString()} ${s.currency}` : '—'}
                  </td>
                  {/* Total */}
                  <td style={{ padding: '8px 8px', verticalAlign: 'top', whiteSpace: 'nowrap', fontWeight: s.total_price ? 600 : 400, color: '#0F172A' }}>
                    {s.total_price != null ? `${Number(s.total_price).toLocaleString()} ${s.currency}` : '—'}
                  </td>
                  {/* Lead time */}
                  <td style={{ padding: '8px 8px', verticalAlign: 'top', whiteSpace: 'nowrap', color: '#374151' }}>
                    {s.lead_time_days > 0 ? `${s.lead_time_days}d` : '—'}
                  </td>
                  {/* Quality bar */}
                  <td style={{ padding: '8px 8px', verticalAlign: 'top', minWidth: 75 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                      <span style={{ fontSize: 11, minWidth: 22, color: qColor, fontWeight: 600 }}>{s.quality_score}</span>
                      <div style={{ flex: 1, height: 3, background: '#E8EDF3', borderRadius: 2, overflow: 'hidden' }}>
                        <div style={{ height: '100%', background: qColor, width: `${s.quality_score}%`, borderRadius: 2 }} />
                      </div>
                    </div>
                  </td>
                  {/* Status */}
                  <td style={{ padding: '8px 8px', verticalAlign: 'top' }}>{statusBadge}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </StepCard>
  );
}

// ”€”€ Step 4: Escalations ”€”€
function EscalationCard({ escalations }: { escalations: Escalation[] }) {
  if (escalations.length === 0) {
    return (
      <StepCard num={4} numColor="#059669" title="Escalation Assessment"
        sub="Human review requirements" badge="NO ESCALATION" badgeType="ok">
        <div style={{ color: '#059669', fontSize: 12, display: 'flex', alignItems: 'center', gap: 5 }}>
          <span>✓</span> No escalation required. Automated decision is permissible.
        </div>
      </StepCard>
    );
  }

  const highCount = escalations.filter(e => e.urgency === 'high').length;
  return (
    <StepCard num={4} numColor={highCount ? '#DC2626' : '#B45309'} title="Escalation Assessment"
      sub="Human review requirements"
      badge={`${escalations.length} ESCALATION${escalations.length > 1 ? 'S' : ''} REQUIRED`}
      badgeType={highCount ? 'err' : 'warn'}>
      {escalations.map((esc, idx) => {
        const isHigh = esc.urgency === 'high';
        const borderColor = isHigh ? 'rgba(220,38,38,0.25)' : 'rgba(180,83,9,0.25)';
        const bg = isHigh ? 'rgba(220,38,38,0.04)' : 'rgba(180,83,9,0.04)';
        const accentColor = isHigh ? '#DC2626' : '#B45309';
        return (
          <div key={esc.rule_id} style={{
            border: `1px solid ${borderColor}`, borderLeft: `3px solid ${accentColor}`,
            background: bg, borderRadius: 3, padding: '10px 12px',
            marginBottom: idx < escalations.length - 1 ? 7 : 0,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 5, flexWrap: 'wrap', gap: 5 }}>
              <span style={{ fontSize: 9, color: '#6B7280', letterSpacing: '0.06em', textTransform: 'uppercase', fontWeight: 600 }}>
                {esc.rule_id} · {esc.urgency.toUpperCase()}
              </span>
              <span style={{
                fontSize: 10, padding: '2px 7px', borderRadius: 3, fontWeight: 600,
                background: isHigh ? 'rgba(220,38,38,0.1)' : 'rgba(180,83,9,0.1)',
                color: accentColor, border: `1px solid ${borderColor}`,
              }}>→ {esc.target}</span>
            </div>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#0F172A', marginBottom: 3 }}>{esc.trigger}</div>
            <div style={{ fontSize: 11, color: '#4B5563', lineHeight: 1.5 }}>{esc.action_required}</div>
            {esc.description && esc.description !== esc.trigger && esc.description !== esc.reason && (
              <div style={{ fontSize: 10.5, color: '#6B7280', marginTop: 5, borderTop: '1px solid rgba(0,0,0,0.05)', paddingTop: 5, lineHeight: 1.5 }}>
                {esc.description}
              </div>
            )}
            {Object.entries(esc).map(([k, v]) => {
              if (['rule_id', 'trigger', 'target', 'urgency', 'description', 'action_required', 'rule', 'reason', 'escalate_to', 'escalation_id'].includes(k)) return null;
              if (v == null || v === '') return null;
              return (
                <div key={k} style={{ fontSize: 10.5, color: '#4B5563', marginTop: 4, padding: '4px 8px', background: 'rgba(0,0,0,0.02)', borderRadius: 3, border: '1px solid rgba(0,0,0,0.04)' }}>
                  <span style={{ fontWeight: 600, textTransform: 'capitalize', color: '#374151' }}>{k.replace(/_/g, ' ')}:</span> {String(v)}
                </div>
              );
            })}
          </div>
        );
      })}
    </StepCard>
  );
}

// ”€”€ Step 5: Recommendation ”€”€
function RecommendationCard({ rec }: { rec: AnalysisResult['recommendation'] }) {
  const decisionMap = { auto_approve: 'AUTO-APPROVE', soft_escalate: 'SOFT ESCALATE', hard_escalate: 'HARD ESCALATE' };
  const decColor = rec.decision === 'auto_approve' ? '#059669' : rec.decision === 'soft_escalate' ? '#B45309' : '#DC2626';
  const badgeType: 'ok' | 'warn' | 'err' = rec.decision === 'auto_approve' ? 'ok' : rec.decision === 'soft_escalate' ? 'warn' : 'err';
  const leftBorder = decColor;
  const bg = rec.decision === 'auto_approve' ? 'rgba(5,150,105,0.04)' : rec.decision === 'soft_escalate' ? 'rgba(180,83,9,0.04)' : 'rgba(220,38,38,0.04)';

  return (
    <StepCard num={5} numColor={decColor} title="Recommendation"
      sub="Final sourcing decision & approval requirements"
      badge={decisionMap[rec.decision] || rec.decision} badgeType={badgeType}>

      {/* Decision box */}
      <div style={{ borderLeft: `4px solid ${leftBorder}`, background: bg, borderRadius: 3, padding: '14px 16px', marginBottom: 12 }}>
        <div style={{ fontSize: 20, fontWeight: 800, color: decColor, letterSpacing: '0.04em', marginBottom: 2 }}>
          {decisionMap[rec.decision] || rec.decision}
        </div>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#0F172A', marginBottom: 12 }}>
          {rec.recommended_supplier_name || 'No supplier recommended'}
        </div>

        {/* Metrics row — no individual card boxes, just columns separated by whitespace */}
        <div style={{ display: 'flex', gap: 24, marginBottom: 10 }}>
          {[
            { label: 'Confidence', val: `${rec.confidence_score ?? 0}%` },
            { label: 'Approval Tier', val: rec.approval_tier ? `Tier ${rec.approval_tier}` : '—' },
            { label: 'Quotes Required', val: String(rec.quotes_required ?? '—') },
          ].map(({ label, val }) => (
            <div key={label}>
              <div style={{ fontSize: 9.5, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#6B7280', marginBottom: 2, fontWeight: 600 }}>{label}</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#0F172A' }}>{val}</div>
            </div>
          ))}
        </div>

        {rec.total_estimated_value != null && (
          <div style={{ fontSize: 11.5, color: '#374151', marginBottom: 5 }}>
            Total Estimated Value: <strong>{Number(rec.total_estimated_value).toLocaleString()} {rec.currency}</strong>
          </div>
        )}
        <div style={{ fontSize: 11.5, color: '#374151', marginBottom: 10 }}>
          Required Approver: <strong>{rec.required_approver}</strong>
        </div>
        <div style={{ fontSize: 11.5, color: '#4B5563', lineHeight: 1.65, borderTop: '1px solid rgba(0,0,0,0.06)', paddingTop: 10 }}>
          {rec.reasoning}
        </div>
      </div>

      {/* Next steps — plain indented list, no cards */}
      {rec.next_steps.length > 0 && (
        <div>
          <div style={{ fontSize: 9.5, letterSpacing: '0.08em', color: '#6B7280', textTransform: 'uppercase', marginBottom: 7, fontWeight: 600 }}>Next Steps</div>
          {rec.next_steps.map((step, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'flex-start', gap: 8,
              fontSize: 11.5, color: '#374151', padding: '5px 0',
              borderBottom: i < rec.next_steps.length - 1 ? '1px solid #F1F5F9' : 'none',
            }}>
              <div style={{ color: '#94A3B8', fontWeight: 600, fontSize: 10, flexShrink: 0, minWidth: 18, marginTop: 2 }}>
                {i + 1}.
              </div>
              <div style={{ lineHeight: 1.5 }}>{step}</div>
            </div>
          ))}
        </div>
      )}
    </StepCard>
  );
}

// ”€”€ Step 6: Audit Log ”€”€
function AuditLogCard({ entries }: { entries: AuditEntry[] }) {
  const resColor = (r: string) => r === 'pass' ? '#059669' : r === 'fail' ? '#DC2626' : r === 'warning' ? '#B45309' : '#1D4ED8';

  return (
    <StepCard num={6} numColor="#374151" title="Audit Log"
      sub="Complete pipeline trace for compliance"
      badge={`${entries.length} ENTRIES`} badgeType="info">
      <div className="audit-log">
        <div style={{ display: 'grid', gridTemplateColumns: '120px 110px 1fr 50px', gap: 8, padding: '5px 10px', borderBottom: '1px solid #E2E8F0', background: '#F8FAFC' }}>
          {['Timestamp', 'Layer', 'Action', 'Result'].map((col, i) => (
            <span key={col} style={{ fontSize: 9, letterSpacing: '0.07em', textTransform: 'uppercase', color: '#6B7280', textAlign: i === 3 ? 'right' : 'left', fontWeight: 600 }}>{col}</span>
          ))}
        </div>
        {entries.map((entry, i) => (
          <div key={i} style={{
            display: 'grid', gridTemplateColumns: '120px 110px 1fr 50px',
            gap: 8, padding: '7px 10px',
            borderBottom: i < entries.length - 1 ? '1px solid #F1F5F9' : 'none',
            fontSize: 10.5, alignItems: 'start',
          }}>
            <div style={{ color: '#94A3B8', fontFamily: 'JetBrains Mono, monospace', fontSize: 9.5 }}>
              {(entry.timestamp || '').replace('T', ' ').split('.')[0]}
            </div>
            <div style={{ color: '#374151', fontWeight: 600, fontSize: 10.5 }}>{entry.layer}</div>
            <div>
              <div style={{ color: '#0F172A', lineHeight: 1.45 }}>{entry.action}</div>
              <div style={{ fontSize: 9.5, color: '#94A3B8', marginTop: 1.5 }}>{entry.details}</div>
            </div>
            <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.06em', color: resColor(entry.result), fontWeight: 700, textAlign: 'right', paddingTop: 2 }}>
              {entry.result}
            </div>
          </div>
        ))}
      </div>
    </StepCard>
  );
}

// ”€”€ Loading view ”€”€
const STEPS = [
  'Parsing request text & extracting fields',
  'Validating completeness & consistency',
  'Evaluating policy rules & restrictions',
  'Scoring & ranking supplier options',
  'Calculating escalation requirements',
  'Generating audit-ready recommendation',
];

function LoadingView({ activeStep }: { activeStep: number }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '60px 20px', gap: 28 }}>
      {/* Spinner — keeps ChainIQ red since it's a brand element in motion, not a status */}
      <div style={{ position: 'relative', width: 56, height: 56 }}>
        <div style={{ position: 'absolute', inset: 0, borderRadius: '50%', border: '2.5px solid #E8EDF3', boxSizing: 'border-box' }} />
        <div style={{
          position: 'absolute', inset: 0, borderRadius: '50%',
          border: '2.5px solid transparent', borderTopColor: '#E30613',
          boxSizing: 'border-box', animation: 'spin 0.8s linear infinite',
        }} />
        <div style={{
          position: 'absolute', inset: 7, borderRadius: '50%',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontWeight: 800, fontSize: 11, color: '#1E293B',
        }}>IQ</div>
      </div>

      <div style={{ fontWeight: 700, fontSize: 13, letterSpacing: '0.1em', color: '#1E293B', textTransform: 'uppercase' }}>
        ARIA PROCESSING
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 9, width: '100%', maxWidth: 320 }}>
        {STEPS.map((step, i) => {
          const done = i < activeStep;
          const active = i === activeStep;
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 9, fontSize: 12, color: done ? '#059669' : active ? '#1E293B' : '#94A3B8', transition: 'all 0.3s' }}>
              <div style={{
                width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                background: done ? '#059669' : active ? '#1E293B' : '#E2E8F0',
                fontSize: 7, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff',
                animation: active ? 'pulse-dot 1s ease-in-out infinite' : 'none',
              }}>
                {done ? '✓' : ''}
              </div>
              {step}
            </div>
          );
        })}
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } } @keyframes pulse-dot { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }`}</style>
    </div>
  );
}

// ”€”€ Empty state ”€”€
function EmptyState() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '70vh', gap: 12, padding: 40, textAlign: 'center' }}>
      <div style={{
        width: 60, height: 60, borderRadius: 8, background: '#F1F5F9',
        border: '1px solid #D1D9E0', display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 24, marginBottom: 2,
      }}>⊙</div>
      <div style={{ fontWeight: 700, fontSize: 17, color: '#0F172A', letterSpacing: '0.03em' }}>ARIA IS READY</div>
      <div style={{ fontSize: 12.5, lineHeight: 1.75, maxWidth: 300, color: '#6B7280' }}>
        Enter a purchase request on the left and click <strong style={{ color: '#0F172A' }}>Analyse Request</strong> to run the full 6-step procurement pipeline.
      </div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', justifyContent: 'center', marginTop: 8, fontSize: 11.5, color: '#94A3B8' }}>
        <span>🔴 Restricted supplier scenarios</span>
        <span>🟡 Missing information detection</span>
        <span>🟢 Auto-approve flows</span>
      </div>
    </div>
  );
}

// ”€”€ Shared helpers ”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€

function SectionHeader({ title }: { title: string }) {
  return (
    <div style={{ fontSize: 9.5, letterSpacing: '0.09em', color: '#6366F1', textTransform: 'uppercase', fontWeight: 700, marginBottom: 8, marginTop: 16, paddingBottom: 4, borderBottom: '1px solid rgba(99,102,241,0.15)' }}>
      {title}
    </div>
  );
}

function KV({ label, val, mono }: { label: string; val: unknown; mono?: boolean }) {
  const display = val == null ? '—' : typeof val === 'boolean' ? (val ? '✓ yes' : '✗ no') : String(val);
  const empty = display === '—';
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 6, padding: '3px 0', borderBottom: '1px solid #F8FAFC', alignItems: 'start' }}>
      <div style={{ fontSize: 10, color: '#6B7280', fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 11, color: empty ? '#CBD5E1' : mono ? '#4338CA' : '#0F172A', fontFamily: mono ? "'JetBrains Mono', monospace" : 'inherit' }}>{display}</div>
    </div>
  );
}

function BoolBadge({ val }: { val: boolean }) {
  return <span style={{ fontSize: 9.5, padding: '1px 6px', borderRadius: 2, fontWeight: 700, background: val ? 'rgba(5,150,105,0.1)' : 'rgba(220,38,38,0.07)', color: val ? '#059669' : '#DC2626', border: `1px solid ${val ? 'rgba(5,150,105,0.25)' : 'rgba(220,38,38,0.2)'}` }}>{val ? 'YES' : 'NO'}</span>;
}

function WeightBar({ label, value }: { label: string; value: number }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '90px 1fr 42px', gap: 7, alignItems: 'center', marginBottom: 5 }}>
      <div style={{ fontSize: 10, color: '#6B7280', textAlign: 'right' }}>{label}</div>
      <div style={{ height: 6, background: '#E8EDF3', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${Math.round(value * 100)}%`, background: 'linear-gradient(90deg, #6366F1, #818CF8)', borderRadius: 3 }} />
      </div>
      <div style={{ fontSize: 10.5, color: '#374151', fontWeight: 700 }}>{(value * 100).toFixed(1)}%</div>
    </div>
  );
}

function SubCard({ title, accent, children }: { title: string; accent?: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(true);
  const color = accent ?? '#6366F1';
  return (
    <div style={{ border: '1px solid #E2E8F0', borderLeft: `3px solid ${color}`, borderRadius: 4, marginBottom: 8, overflow: 'hidden' }}>
      <div onClick={() => setOpen(o => !o)} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 10px', background: '#F8FAFC', cursor: 'pointer', userSelect: 'none' }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: '#0F172A' }}>{title}</span>
        <span style={{ fontSize: 9, color: '#94A3B8', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}>▼</span>
      </div>
      {open && <div style={{ padding: '8px 10px' }}>{children}</div>}
    </div>
  );
}

// ”€”€ Step 7: Full Backend Report ”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€
function BackendDetailsCard({ b }: { b: BackendResult }) {
  const pipe = b._pipeline ?? {} as BackendResult['_pipeline'];
  const at = b.audit_trail ?? {} as BackendResult['audit_trail'];
  const interp = b.request_interpretation ?? {} as BackendResult['request_interpretation'];
  const val = b.validation ?? {} as BackendResult['validation'];
  const pol = b.policy_evaluation ?? {} as BackendResult['policy_evaluation'];
  const rec = b.recommendation ?? {} as BackendResult['recommendation'];
  const suppliers = b.supplier_shortlist ?? [];
  const excluded = (b.suppliers_excluded ?? []) as Array<Record<string, unknown>>;
  const escalations = b.escalations ?? [];

  return (
    <div className="step-card" style={{ borderLeft: '3px solid #6366F1' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 13px', background: 'linear-gradient(135deg, #F0F0FF 0%, #F8FAFC 100%)', borderBottom: '1px solid #E2E8F0' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{ width: 22, height: 22, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10.5, fontWeight: 700, background: '#6366F1', color: '#fff', flexShrink: 0 }}>7</div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 12.5, color: '#0F172A' }}>Full Backend Report</div>
            <div style={{ fontSize: 10, color: '#94A3B8', marginTop: 1 }}>Complete pipeline output — all fields from the Python model</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <span style={{ fontSize: 9.5, padding: '2px 7px', borderRadius: 10, fontWeight: 600, background: 'rgba(99,102,241,0.12)', color: '#6366F1', border: '1px solid rgba(99,102,241,0.25)' }}>v{pipe.pipeline_version ?? '1.0'}</span>
          {b.request_id && <span style={{ fontSize: 9.5, padding: '2px 7px', borderRadius: 10, fontWeight: 600, background: '#F1F5F9', color: '#374151', border: '1px solid #E2E8F0' }}>{b.request_id}</span>}
        </div>
      </div>

      <div style={{ padding: '12px 14px' }}>

        {/* ”€”€ 1. Pipeline Metadata ”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€ */}
        <SectionHeader title="Pipeline Metadata" />
        <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginBottom: 4 }}>
          {[
            { label: 'NLP Layer', val: pipe.nlp_enabled, color: pipe.nlp_enabled ? '#059669' : '#DC2626' },
            { label: 'Rationale AI', val: pipe.rationale_enabled, color: pipe.rationale_enabled ? '#059669' : '#DC2626' },
          ].map(({ label, val, color }) => (
            <div key={label}>
              <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#94A3B8', marginBottom: 3, fontWeight: 600 }}>{label}</div>
              <BoolBadge val={!!val} />
            </div>
          ))}
          <div><div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#94A3B8', marginBottom: 3, fontWeight: 600 }}>Calibration AUC</div><div style={{ fontSize: 15, fontWeight: 800, color: '#6366F1' }}>{pipe.calibration_auc?.toFixed(3) ?? '—'}</div></div>
          <div><div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#94A3B8', marginBottom: 3, fontWeight: 600 }}>Processed At</div><div style={{ fontSize: 11, fontWeight: 600, color: '#374151' }}>{b.processed_at ? new Date(b.processed_at).toLocaleString() : '—'}</div></div>
        </div>

        {/* ”€”€ 2. Request Interpretation ”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€ */}
        <SectionHeader title="Request Interpretation" />
        <SubCard title="Structured Fields" accent="#0EA5E9">
          <KV label="Category L1" val={interp.category_l1} />
          <KV label="Category L2" val={interp.category_l2} />
          <KV label="Quantity" val={interp.quantity != null ? `${interp.quantity} ${interp.unit_of_measure}` : null} />
          <KV label="Budget" val={interp.budget_amount != null ? `${interp.budget_amount} ${interp.currency}` : null} />
          <KV label="Required By" val={interp.required_by_date} />
          <KV label="Days Until Required" val={interp.days_until_required} />
          <KV label="Delivery Country" val={interp.delivery_country} />
          <KV label="Delivery Countries" val={(interp.delivery_countries ?? []).join(', ') || null} />
          <KV label="Delivery Region" val={interp.delivery_region} />
          <KV label="Origin Country" val={interp.origin_country} />
          <KV label="Currency" val={interp.currency} />
          <KV label="ESG Requirement" val={interp.esg_requirement} />
          <KV label="Data Residency Required" val={interp.data_residency_required} />
          <KV label="Expedited Delivery" val={interp.expedited_delivery_required} />
          <KV label="Preferred Supplier Stated" val={interp.preferred_supplier_stated} />
          <KV label="Incumbent Supplier" val={interp.incumbent_supplier} />
          <KV label="Requester Instruction" val={interp.requester_instruction} />
        </SubCard>

        {Object.keys(interp.nlp_filled_fields ?? {}).length > 0 && (
          <SubCard title={`NLP Auto-filled Fields (${Object.keys(interp.nlp_filled_fields ?? {}).length})`} accent="#8B5CF6">
            {Object.entries(interp.nlp_filled_fields ?? {}).map(([field, info]) => (
              <div key={field} style={{ background: 'rgba(139,92,246,0.04)', border: '1px solid rgba(139,92,246,0.15)', borderRadius: 3, padding: '7px 10px', marginBottom: 5 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: '#7C3AED', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{field}</span>
                  <span style={{ fontSize: 10.5, color: '#059669', fontWeight: 700 }}>† {String(info.nlp_value)}{info.unit ? ` ${info.unit}` : ''}</span>
                </div>
                <KV label="Original value" val={info.original_field_value ?? 'null'} />
                <KV label="Source" val={info.source} />
                <KV label="Note" val={info.note} />
              </div>
            ))}
          </SubCard>
        )}

        {/* ”€”€ 3. Validation ”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€ */}
        <SectionHeader title="Validation" />
        <SubCard title="Completeness & Issues" accent={val.completeness === 'pass' ? '#059669' : '#DC2626'}>
          <KV label="Completeness" val={val.completeness} />
          <KV label="Missing Fields" val={(val.missing_fields ?? []).join(', ') || 'none'} />
          <KV label="Issues Detected" val={(val.issues_detected ?? []).join('; ') || 'none'} />
        </SubCard>

        {val.preferred_supplier_status?.supplier && (
          <SubCard title="Preferred Supplier Status" accent="#F59E0B">
            <KV label="Supplier" val={val.preferred_supplier_status.supplier} />
            <KV label="Supplier ID" val={val.preferred_supplier_status.supplier_id} />
            <KV label="Status" val={val.preferred_supplier_status.status} />
            <KV label="On Preferred List" val={val.preferred_supplier_status.is_on_preferred_list} />
            <KV label="Note" val={val.preferred_supplier_status.note} />
          </SubCard>
        )}

        {/* ”€”€ 4. Policy Evaluation ”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€ */}
        <SectionHeader title="Policy Evaluation" />

        {pol.approval_threshold && (
          <SubCard title="Approval Threshold" accent="#E30613">
            <KV label="Tier ID" val={pol.approval_threshold.tier_id} />
            <KV label="Rule Applied" val={pol.approval_threshold.rule_applied} />
            <KV label="Threshold Currency" val={pol.approval_threshold.threshold_currency} />
            <KV label="Effective Contract Value" val={pol.approval_threshold.effective_contract_value != null ? `${pol.approval_threshold.effective_contract_value.toLocaleString()} ${pol.approval_threshold.threshold_currency}` : null} />
            <KV label="Request Currency" val={pol.approval_threshold.request_currency} />
            <KV label="FX Conversion Notes" val={pol.approval_threshold.fx_conversion_notes || 'none'} />
            <KV label="Quotes Required" val={pol.approval_threshold.quotes_required} />
            <KV label="Fast Track Applied" val={pol.approval_threshold.fast_track_applied} />
            <KV label="Approvers" val={(pol.approval_threshold.approvers ?? []).join(', ')} />
            <KV label="Deviation Approval" val={(pol.approval_threshold.deviation_approval ?? []).join(', ') || 'none'} />
            <KV label="Basis" val={pol.approval_threshold.basis} />
            {pol.approval_threshold.note && <KV label="Note" val={pol.approval_threshold.note} />}
          </SubCard>
        )}

        {pol.preferred_supplier?.supplier && (
          <SubCard title="Preferred Supplier Policy" accent="#F59E0B">
            <KV label="Supplier" val={pol.preferred_supplier.supplier} />
            <KV label="Status" val={pol.preferred_supplier.status} />
            <KV label="Is Preferred" val={pol.preferred_supplier.is_preferred} />
            <KV label="Covers Delivery Country" val={pol.preferred_supplier.covers_delivery_country} />
            <KV label="Is Restricted" val={pol.preferred_supplier.is_restricted} />
            <KV label="Policy Note" val={pol.preferred_supplier.policy_note} />
          </SubCard>
        )}

        {Object.keys(pol.restricted_suppliers ?? {}).length > 0 && (
          <SubCard title="Restricted Suppliers" accent="#DC2626">
            {Object.entries(pol.restricted_suppliers ?? {}).map(([id, info]) => (
              <div key={id} style={{ marginBottom: 5 }}>
                <div style={{ fontSize: 10.5, fontWeight: 700, color: '#DC2626' }}>{id}</div>
                <div style={{ fontSize: 10, color: '#6B7280' }}>{JSON.stringify(info)}</div>
              </div>
            ))}
          </SubCard>
        )}

        {(pol.category_rules_applied ?? []).length > 0 && (
          <SubCard title={`Category Rules Applied (${pol.category_rules_applied.length})`} accent="#0EA5E9">
            {pol.category_rules_applied.map(r => (
              <div key={r.rule_id} style={{ padding: '5px 0', borderBottom: '1px solid #F1F5F9' }}>
                <KV label="Rule ID" val={r.rule_id} />
                <KV label="Rule Type" val={r.rule_type} />
                <KV label="Text" val={r.rule_text} />
                <KV label="Context" val={r.context} />
                <KV label="Is Relaxing" val={r.is_relaxing} />
              </div>
            ))}
          </SubCard>
        )}

        {(pol.geography_rules_applied ?? []).length > 0 && (
          <SubCard title={`Geography Rules Applied (${pol.geography_rules_applied.length})`} accent="#0EA5E9">
            {(pol.geography_rules_applied as Array<Record<string, unknown>>).map((r, i) => (
              <div key={i} style={{ fontSize: 11, color: '#374151', padding: '3px 0' }}>{JSON.stringify(r)}</div>
            ))}
          </SubCard>
        )}

        {/* ”€”€ 5. Supplier Shortlist (full detail per supplier) ”€”€”€”€”€”€”€”€”€”€”€”€”€ */}
        <SectionHeader title={`Supplier Shortlist (${suppliers.length})`} />
        {suppliers.map(s => (
          <SubCard key={s.supplier_id} title={`[${s.rank}] ${s.supplier_name} — Score ${s.score?.toFixed(4) ?? '—'}`} accent={s.rank === 1 ? '#059669' : '#6366F1'}>
            {/* Badges row */}
            <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginBottom: 8 }}>
              {s.preferred && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 2, background: 'rgba(15,23,42,0.07)', color: '#374151', fontWeight: 700, border: '1px solid rgba(15,23,42,0.12)' }}>PREFERRED</span>}
              {s.incumbent && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 2, background: 'rgba(99,102,241,0.1)', color: '#4338CA', fontWeight: 700, border: '1px solid rgba(99,102,241,0.2)' }}>INCUMBENT</span>}
              {s.policy_compliant ? <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 2, background: 'rgba(5,150,105,0.1)', color: '#059669', fontWeight: 700, border: '1px solid rgba(5,150,105,0.2)' }}>COMPLIANT</span> : <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 2, background: 'rgba(220,38,38,0.1)', color: '#DC2626', fontWeight: 700 }}>NON-COMPLIANT</span>}
              {s.capacity_flag && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 2, background: 'rgba(245,158,11,0.1)', color: '#B45309', fontWeight: 700, border: '1px solid rgba(245,158,11,0.2)' }}>CAPACITY FLAG</span>}
            </div>

            {/* Pricing */}
            <div style={{ fontSize: 9.5, fontWeight: 700, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 4 }}>Pricing</div>
            <KV label="Supplier ID" val={s.supplier_id} />
            <KV label="Pricing Tier" val={s.pricing_tier} />
            <KV label="Tier Applied" val={s.pricing_tier_applied} />
            <KV label="MOQ" val={s.moq} />
            <KV label="Unit Price (standard)" val={s.unit_price_standard != null ? `${s.unit_price_standard} ${s.pricing_currency}` : null} />
            <KV label="Unit Price (expedited)" val={s.unit_price_expedited != null ? `${s.unit_price_expedited} ${s.pricing_currency}` : null} />
            <KV label="Unit Price (used)" val={s.unit_price != null ? `${s.unit_price} ${s.pricing_currency}` : null} />
            <KV label="Total Price" val={s.total_price != null ? `${s.total_price.toLocaleString()} ${s.pricing_currency}` : null} />
            <KV label="Total (req currency)" val={s.total_price_in_req_currency != null ? `${s.total_price_in_req_currency.toLocaleString()} ${s.req_currency}` : null} />
            <KV label="Savings vs Budget" val={s.savings_pct_vs_budget != null ? `${s.savings_pct_vs_budget.toFixed(2)}%` : null} />
            <KV label="FX Applied" val={s.fx_applied} />
            <KV label="FX Rate" val={s.fx_rate} />
            <KV label="Expedited Used" val={s.expedited_used} />

            {/* Lead time */}
            <div style={{ fontSize: 9.5, fontWeight: 700, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.07em', margin: '8px 0 4px' }}>Lead Time</div>
            <KV label="Standard Lead Time" val={`${s.standard_lead_time_days} days`} />
            <KV label="Expedited Lead Time" val={`${s.expedited_lead_time_days} days`} />
            <KV label="Lead Time Used" val={`${s.lead_time_days} days`} />
            <KV label="Lead Time Feasible" val={s.lead_time_feasible} />
            {s.lead_time_note && <KV label="Lead Time Note" val={s.lead_time_note} />}

            {/* Quality / Risk / ESG */}
            <div style={{ fontSize: 9.5, fontWeight: 700, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.07em', margin: '8px 0 4px' }}>Scores</div>
            {[
              { label: 'Quality Score', val: s.quality_score, color: s.quality_score >= 80 ? '#059669' : s.quality_score >= 60 ? '#B45309' : '#DC2626' },
              { label: 'Risk Score', val: s.risk_score, color: s.risk_score <= 20 ? '#059669' : s.risk_score <= 40 ? '#B45309' : '#DC2626' },
              { label: 'ESG Score', val: s.esg_score, color: s.esg_score >= 70 ? '#059669' : s.esg_score >= 50 ? '#B45309' : '#DC2626' },
            ].map(({ label, val: sv, color }) => (
              <div key={label} style={{ display: 'grid', gridTemplateColumns: '160px 1fr 40px', gap: 6, alignItems: 'center', padding: '3px 0' }}>
                <div style={{ fontSize: 10, color: '#6B7280', fontWeight: 600 }}>{label}</div>
                <div style={{ height: 5, background: '#E8EDF3', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${sv}%`, background: color, borderRadius: 3 }} />
                </div>
                <div style={{ fontSize: 11, fontWeight: 700, color }}>{sv}</div>
              </div>
            ))}

            {/* Capacity & Coverage */}
            <div style={{ fontSize: 9.5, fontWeight: 700, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.07em', margin: '8px 0 4px' }}>Capacity & Coverage</div>
            <KV label="Capacity/Month" val={s.capacity_per_month?.toLocaleString()} />
            <KV label="Capacity Flag" val={s.capacity_flag} />
            <KV label="Budget Sufficient" val={s.budget_sufficient} />
            {s.budget_note && <KV label="Budget Note" val={s.budget_note} />}
            <KV label="Covers Delivery Country" val={s.covers_delivery_country} />
            <KV label="Data Residency Supported" val={s.data_residency_supported} />

            {/* Composite score & weights */}
            <div style={{ fontSize: 9.5, fontWeight: 700, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.07em', margin: '8px 0 6px' }}>Composite Score: <span style={{ color: '#6366F1' }}>{s.score?.toFixed(4)}</span></div>
            {Object.entries(s.score_weights ?? {}).map(([k, v]) => <WeightBar key={k} label={k} value={v} />)}

            {s.recommendation_note && (
              <div style={{ marginTop: 6, fontSize: 11, color: '#374151', background: 'rgba(99,102,241,0.04)', border: '1px solid rgba(99,102,241,0.15)', borderRadius: 3, padding: '6px 8px' }}>
                {s.recommendation_note}
              </div>
            )}
          </SubCard>
        ))}

        {/* ”€”€ 6. Excluded Suppliers ”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€ */}
        {excluded.length > 0 && (
          <>
            <SectionHeader title={`Excluded Suppliers (${excluded.length})`} />
            {excluded.map((s, i) => (
              <SubCard key={i} title={String(s.supplier_name ?? s.supplier_id ?? `Supplier ${i + 1}`)} accent="#DC2626">
                {Object.entries(s).map(([k, v]) => <KV key={k} label={k} val={v} />)}
              </SubCard>
            ))}
          </>
        )}

        {/* — 7. Escalations (raw) —————————————————————————————————————————————————————— */}
        {escalations.length > 0 && (
          <>
            <SectionHeader title={`Escalations — Raw (${escalations.length})`} />
            {escalations.map((e, i) => (
              <SubCard key={i} title={`${e.rule ?? 'ESC'} → ${e.escalate_to ?? '?'}`} accent="#DC2626">
                {Object.entries(e).map(([k, v]) => <KV key={k} label={k} val={v} />)}
              </SubCard>
            ))}
          </>
        )}

        {/* ── 8. Recommendation (all fields) ── */}
        <SectionHeader title="Recommendation — Full Detail" />
        <SubCard title="Decision Fields" accent={rec.status === 'proceed' ? '#059669' : '#DC2626'}>
          <KV label="Status" val={rec.status} />
          <KV label="Shortlist Count" val={rec.shortlist_count} />
          <KV label="Quotes Required" val={rec.quotes_required} />
          <KV label="Top Supplier" val={rec.top_supplier} />
          <KV label="Top Supplier Total" val={rec.top_supplier_total != null ? rec.top_supplier_total.toLocaleString() : null} />
          <KV label="All Infeasible Lead Time" val={rec.all_infeasible_lead_time} />
          <KV label="All Over Budget" val={rec.all_over_budget} />
          <KV label="Preferred Supplier (if resolved)" val={rec.preferred_supplier_if_resolved} />
          <KV label="Preferred Supplier Rationale" val={rec.preferred_supplier_rationale || 'none'} />
          <KV label="Minimum Budget Required" val={rec.minimum_budget_required != null ? `${rec.minimum_budget_required} ${rec.minimum_budget_currency}` : null} />
          <div style={{ marginTop: 8, padding: 8, background: 'rgba(5,150,105,0.04)', border: '1px solid rgba(5,150,105,0.15)', borderRadius: 3, fontSize: 11, color: '#0F172A', lineHeight: 1.6 }}>
            <span style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#94A3B8', fontWeight: 700 }}>Reason: </span>{rec.reason}
          </div>
        </SubCard>

        {/* ”€”€ 9. Audit Trail ”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€ */}
        <SectionHeader title="Audit Trail — Full Detail" />
        <SubCard title="Policies & Suppliers Evaluated" accent="#374151">
          <KV label="Policies Checked" val={(at.policies_checked ?? []).join(', ')} />
          <KV label="Supplier IDs Evaluated" val={(at.supplier_ids_evaluated ?? []).join(', ')} />
          <KV label="Pricing Region" val={at.pricing_region_used} />
          <KV label="Pricing Tiers Applied" val={at.pricing_tiers_applied} />
          <KV label="Expedited Evaluated" val={at.expedited_evaluated} />
        </SubCard>
        <SubCard title="NLP & Calibration" accent="#8B5CF6">
          <KV label="NLP Used" val={at.nlp_used} />
          <KV label="Translation Applied" val={at.nlp_translation_applied} />
          <KV label="Contradictions Detected" val={at.nlp_contradictions_detected} />
          <KV label="Qty Override Applied" val={at.nlp_qty_override_applied} />
          <KV label="NLP Fields Filled" val={(at.nlp_fields_filled ?? []).join(', ') || 'none'} />
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 9.5, fontWeight: 700, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 6 }}>Calibrated Scoring Weights</div>
            {Object.entries(at.scoring_weights_used ?? {}).map(([k, v]) => <WeightBar key={k} label={k} value={v} />)}
          </div>
        </SubCard>
        <SubCard title="FX Rates & Data Sources" accent="#0EA5E9">
          <KV label="FX Rates" val={Object.entries(at.fx_rates_used ?? {}).map(([k, v]) => `${k}=${v}`).join(' · ')} />
          <KV label="Data Sources" val={(at.data_sources_used ?? []).join(', ')} />
          <KV label="Historical Awards Consulted" val={at.historical_awards_consulted} />
          {at.historical_award_note && <KV label="Award Note" val={at.historical_award_note} />}
        </SubCard>
        {at.historical_context && (
          <SubCard title="Historical Context" accent="#0EA5E9">
            <KV label="Has Direct History" val={at.historical_context.has_direct_history} />
            <KV label="Prior Awards Count" val={at.historical_context.prior_awards?.length ?? 0} />
            <KV label="Note" val={at.historical_context.note} />
          </SubCard>
        )}
      </div>
    </div>
  );
}

// ”€”€ Main Output Panel ”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€”€
interface OutputPanelProps {
  view: 'empty' | 'loading' | 'results';
  result: AnalysisResult | null;
  backendRaw?: BackendResult | null;
  loadingStep: number;
  error: string | null;
}

export default function OutputPanel({ view, result, backendRaw, loadingStep, error }: OutputPanelProps) {
  return (
    <div style={{ padding: '16px 18px', overflowY: 'auto', height: '100%' }}>
      {view === 'empty' && <EmptyState />}
      {view === 'loading' && <LoadingView activeStep={loadingStep} />}
      {view === 'results' && error && (
        <div style={{ background: 'rgba(220,38,38,0.04)', border: '1px solid rgba(220,38,38,0.25)', borderLeft: '3px solid #DC2626', borderRadius: 4, padding: 16 }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: '#DC2626', marginBottom: 6 }}>Analysis Failed</div>
          <div style={{ fontSize: 11.5, color: '#374151', lineHeight: 1.6, marginBottom: 8, wordBreak: 'break-all' }}>{error}</div>
          <div style={{ fontSize: 11, color: '#6B7280', lineHeight: 1.6, background: '#F8FAFC', padding: 9, borderRadius: 3, border: '1px solid #E2E8F0' }}>
            <strong>Tip:</strong> Make sure the Python backend is running on <strong>port 8000</strong>, then try again.
          </div>
        </div>
      )}
      {view === 'results' && result && !error && (
        <div>
          <ParsedRequestCard data={result.request_parsed} compat={result.compatibility} />
          <PolicyCard rules={result.policy_evaluation} />
          <SupplierCard suppliers={result.suppliers} />
          <EscalationCard escalations={result.escalations} />
          <RecommendationCard rec={result.recommendation} />
          <AuditLogCard entries={result.audit_log} />
          {backendRaw && <BackendDetailsCard b={backendRaw} />}
        </div>
      )}
    </div>
  );
}
