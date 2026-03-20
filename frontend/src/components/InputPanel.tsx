'use client';

import { useState, useRef } from 'react';
import { CAT2 } from '@/lib/data';
import { EXAMPLE_REQUESTS } from '@/lib/demo';
import type { PurchaseRequest } from '@/lib/types';

interface InputPanelProps {
  onAnalyze: (req: PurchaseRequest, demoKey?: string, uploadedFile?: File, parsedRequests?: Record<string, unknown>[]) => void;
  loading: boolean;
}

const DEFAULT_FORM = {
  text: '', cat1: '', cat2: '', qty: '', unit: 'units', date: '',
  budget: '', currency: 'EUR', country: '', supplier: '', bu: '',
  delivery: '', esg: false, drc: false, channel: 'portal', lang: 'en',
  optNeg: true, optBun: true, agenticMode: false,
};

type FormState = typeof DEFAULT_FORM & { esg: boolean; drc: boolean; optNeg: boolean; optBun: boolean; agenticMode: boolean };

export default function InputPanel({ onAnalyze, loading }: InputPanelProps) {
  const [activeTab, setActiveTab] = useState<'manual' | 'json'>('manual');
  const [form, setForm] = useState<FormState>(DEFAULT_FORM as FormState);
  const [jsonText, setJsonText] = useState('');
  const [fileName, setFileName] = useState('');
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [requestCount, setRequestCount] = useState<number | null>(null);
  const [parsedRequests, setParsedRequests] = useState<Record<string, unknown>[] | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const cat2Options = CAT2[form.cat1] || [];

  const setField = (key: keyof FormState, val: string | boolean) => {
    setForm(prev => ({
      ...prev,
      [key]: val,
      ...(key === 'cat1' ? { cat2: '' } : {}),
    }));
  };

  const loadExample = (key: 'restricted' | 'missing' | 'standard') => {
    const ex = EXAMPLE_REQUESTS[key];
    setForm({
      text: ex.text, cat1: ex.cat1, cat2: ex.cat2, qty: ex.qty,
      unit: ex.unit, date: ex.date, budget: ex.budget, currency: ex.currency,
      country: ex.country, supplier: ex.supplier, bu: ex.bu, delivery: ex.delivery,
      esg: ex.esg, drc: ex.drc, channel: ex.channel, lang: ex.lang,
      optNeg: true, optBun: true, agenticMode: form.agenticMode || false,
    });
    setActiveTab('manual');
  };

  const handleManualSubmit = () => {
    if (!form.text.trim()) { alert('Please enter a request description.'); return; }
    const demoKey = Object.entries(EXAMPLE_REQUESTS).find(
      ([, ex]) => ex.text === form.text
    )?.[0];
    const req: PurchaseRequest = {
      request_text: form.text,
      category_l1: form.cat1,
      category_l2: form.cat2,
      quantity: form.qty || null,
      unit_of_measure: form.unit,
      required_by_date: form.date || null,
      budget_amount: form.budget || null,
      currency: form.currency,
      country: form.country,
      preferred_supplier_mentioned: form.supplier || null,
      business_unit: form.bu || null,
      delivery_countries: form.delivery.split(',').map(s => s.trim()).filter(Boolean),
      esg_requirement: form.esg,
      data_residency_constraint: form.drc,
      request_channel: form.channel,
      request_language: form.lang,
      _enable_optimization: form.optNeg,
      _enable_bundling: form.optBun,
      agentic_mode: form.agenticMode,
    };
    onAnalyze(req, demoKey);
  };

  const handleJsonSubmit = () => {
    if (!uploadedFile && !jsonText.trim()) { alert('Please paste or upload a JSON request.'); return; }
    // Batch mode: file with multiple requests
    if (parsedRequests && parsedRequests.length > 1) {
      const empty: PurchaseRequest = {
         request_text: '', category_l1: '', category_l2: '', quantity: null, unit_of_measure: '', required_by_date: null, budget_amount: null, currency: 'EUR', country: '', preferred_supplier_mentioned: null, business_unit: null, delivery_countries: [], esg_requirement: false, data_residency_constraint: false, request_channel: '', request_language: '',
         _enable_bundling: form.optBun 
      };
      
      const requestsWithFlags = parsedRequests.map((r) => ({
        ...r, _enable_bundling: form.optBun, _enable_optimization: form.optNeg, agentic_mode: form.agenticMode
      }));

      onAnalyze(empty, undefined, undefined, requestsWithFlags);
      return;
    }
    // Single file upload: apply UI flags directly to the parsed JSON request
    if (uploadedFile && parsedRequests && parsedRequests.length === 1) {
      const parsed = parsedRequests[0] as PurchaseRequest;
      parsed._enable_optimization = form.optNeg;
      parsed._enable_bundling = form.optBun;
      parsed.agentic_mode = form.agenticMode;
      onAnalyze(parsed);
      return;
    }
    let parsed: PurchaseRequest;
    try { 
      const raw = JSON.parse(jsonText); 
      parsed = Array.isArray(raw) ? raw[0] : raw; 
      parsed._enable_optimization = form.optNeg;
      parsed._enable_bundling = form.optBun;
      parsed.agentic_mode = form.agenticMode;
    }
    catch { alert('Invalid JSON.'); return; }
    onAnalyze(parsed);
  };

  const readFile = (file: File) => {
    setUploadedFile(file);
    setFileName(file.name);
    setParsedRequests(null);
    setRequestCount(null);
    const reader = new FileReader();
    reader.onload = ev => {
      try {
        const data = JSON.parse(ev.target?.result as string);
        if (Array.isArray(data)) {
          setParsedRequests(data);
          setRequestCount(data.length);
          setJsonText(JSON.stringify(data[0], null, 2));
        } else {
          setParsedRequests([data]);
          setRequestCount(1);
          setJsonText(JSON.stringify(data, null, 2));
        }
      } catch { alert('Invalid JSON file'); }
    };
    reader.readAsText(file);
  };

  const inputStyle = {
    width: '100%', background: '#fff', border: '1px solid #D1D9E0',
    borderRadius: 4, color: '#0F172A', fontFamily: 'Inter, sans-serif',
    fontSize: 12.5, padding: '7px 10px', outline: 'none',
  };

  const labelStyle = {
    display: 'block', fontSize: 10, fontWeight: 600, letterSpacing: '0.08em',
    textTransform: 'uppercase' as const, color: '#374151', marginBottom: 4,
  };

  const FG = ({ children }: { children: React.ReactNode }) => (
    <div style={{ marginBottom: 10 }}>{children}</div>
  );

  return (
    <div style={{
      background: '#fff',
      borderRight: '1px solid #E2E8F0',
      padding: 18,
      overflowY: 'auto',
      height: '100%',
    }}>
      {/* Tabs */}
      <div className="tab-nav">
        <button className={`tab-btn ${activeTab === 'manual' ? 'active' : ''}`}
          onClick={() => setActiveTab('manual')}>Manual Entry</button>
        <button className={`tab-btn ${activeTab === 'json' ? 'active' : ''}`}
          onClick={() => setActiveTab('json')}>Upload JSON</button>
      </div>

      {/* Manual Tab */}
      {activeTab === 'manual' && (
        <div>
          {/* Request text */}
          <div className="section-label">Request Description</div>
          <FG>
            <textarea
              className="field-textarea"
              rows={4}
              placeholder="Describe the purchase request in natural language…"
              value={form.text}
              onChange={e => setField('text', e.target.value)}
            />
          </FG>

          {/* Category */}
          <div className="section-label">Classification</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <FG>
              <label style={labelStyle}>Category L1</label>
              <select className="field-select" value={form.cat1}
                onChange={e => setField('cat1', e.target.value)}>
                <option value="">— Select —</option>
                {Object.keys(CAT2).map(c => <option key={c}>{c}</option>)}
              </select>
            </FG>
            <FG>
              <label style={labelStyle}>Category L2</label>
              <select className="field-select" value={form.cat2}
                onChange={e => setField('cat2', e.target.value)}>
                <option value="">— Select —</option>
                {cat2Options.map(c => <option key={c}>{c}</option>)}
              </select>
            </FG>
          </div>

          {/* Quantity & Timeline */}
          <div className="section-label">Quantity &amp; Timeline</div>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: 7 }}>
            <FG>
              <label style={labelStyle}>Quantity</label>
              <input type="number" className="field-input" placeholder="e.g. 500" min="1"
                value={form.qty} onChange={e => setField('qty', e.target.value)} />
            </FG>
            <FG>
              <label style={labelStyle}>Unit</label>
              <select className="field-select" value={form.unit}
                onChange={e => setField('unit', e.target.value)}>
                <option>units</option><option>licences</option>
                <option>days</option><option>months</option>
              </select>
            </FG>
            <FG>
              <label style={labelStyle}>Required By</label>
              <input type="date" className="field-input" value={form.date}
                onChange={e => setField('date', e.target.value)} />
            </FG>
          </div>

          {/* Budget & Location */}
          <div className="section-label">Budget &amp; Location</div>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: 7 }}>
            <FG>
              <label style={labelStyle}>Budget Amount</label>
              <input type="number" className="field-input" placeholder="e.g. 400000"
                value={form.budget} onChange={e => setField('budget', e.target.value)} />
            </FG>
            <FG>
              <label style={labelStyle}>Currency</label>
              <select className="field-select" value={form.currency}
                onChange={e => setField('currency', e.target.value)}>
                <option>EUR</option><option>CHF</option><option>USD</option>
              </select>
            </FG>
            <FG>
              <label style={labelStyle}>Country</label>
              <select className="field-select" value={form.country}
                onChange={e => setField('country', e.target.value)}>
                <option value="">—</option>
                {['DE','FR','NL','BE','AT','IT','ES','PL','UK','CH','US','CA','BR','MX','SG','AU','IN','JP','UAE','ZA'].map(c =>
                  <option key={c}>{c}</option>
                )}
              </select>
            </FG>
          </div>

          {/* Stakeholder */}
          <div className="section-label">Stakeholder Info</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <FG>
              <label style={labelStyle}>Preferred Supplier</label>
              <input type="text" className="field-input" placeholder="e.g. RestrictedTech SA"
                value={form.supplier} onChange={e => setField('supplier', e.target.value)} />
            </FG>
            <FG>
              <label style={labelStyle}>Business Unit</label>
              <input type="text" className="field-input" placeholder="e.g. Engineering"
                value={form.bu} onChange={e => setField('bu', e.target.value)} />
            </FG>
          </div>
          <FG>
            <label style={labelStyle}>Delivery Countries (comma-separated)</label>
            <input type="text" className="field-input" placeholder="e.g. DE, FR, NL"
              value={form.delivery} onChange={e => setField('delivery', e.target.value)} />
          </FG>

          {/* Special requirements */}
          <FG>
            <label style={labelStyle}>Special Requirements</label>
            <div style={{ display: 'flex', gap: 20, marginTop: 4 }}>
              {[
                { id: 'esg', label: 'ESG / Sustainability', key: 'esg' as const },
                { id: 'drc', label: 'Data Residency', key: 'drc' as const },
              ].map(({ id, label, key }) => (
                <label key={id} style={{ display: 'flex', alignItems: 'center', gap: 7, cursor: 'pointer', fontSize: 12, color: '#475569' }}>
                  <input type="checkbox" checked={!!form[key]} onChange={e => setField(key, e.target.checked)}
                    style={{ width: 15, height: 15, accentColor: '#E30613', cursor: 'pointer' }} />
                  {label}
                </label>
              ))}
            </div>
          </FG>

          {/* AI Optimizer Add-ons */}
          <FG>
            <label style={labelStyle}>AI Optimizer Extra Modules</label>
            <div style={{ display: 'flex', gap: 15, marginTop: 4, flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 11, color: '#334155', background: '#F1F5F9', padding: '4px 8px', borderRadius: 4, border: '1px solid #E2E8F0' }}>
                <input type="checkbox" checked={!!form.optNeg} onChange={e => setField('optNeg', e.target.checked)}
                  style={{ width: 13, height: 13, accentColor: '#4F46E5', cursor: 'pointer' }} />
                Negotiation Advisor (Single)
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 11, color: '#334155', background: '#F1F5F9', padding: '4px 8px', borderRadius: 4, border: '1px solid #E2E8F0' }}>
                <input type="checkbox" checked={!!form.optBun} onChange={e => setField('optBun', e.target.checked)}
                  style={{ width: 13, height: 13, accentColor: '#4F46E5', cursor: 'pointer' }} />
                Demand Aggregator (Batch)
              </label>
              <label style={{ 
                display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 11, 
                color: '#fff', background: 'linear-gradient(135deg, #4F46E5, #7C3AED)', 
                padding: '4px 10px', borderRadius: 4, border: '1px solid #4338CA',
                boxShadow: '0 2px 4px rgba(79, 70, 229, 0.2)'
              }}>
                <input type="checkbox" checked={!!form.agenticMode} onChange={e => setField('agenticMode', e.target.checked)}
                  style={{ width: 13, height: 13, accentColor: '#fff', cursor: 'pointer' }} />
                ✨ Agentic Mode (External Data)
              </label>
            </div>
          </FG>

          {/* Channel & Language */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <FG>
              <label style={labelStyle}>Channel</label>
              <select className="field-select" value={form.channel}
                onChange={e => setField('channel', e.target.value)}>
                <option>portal</option><option>email</option><option>teams</option>
              </select>
            </FG>
            <FG>
              <label style={labelStyle}>Language</label>
              <select className="field-select" value={form.lang}
                onChange={e => setField('lang', e.target.value)}>
                <option value="en">English</option><option value="fr">French</option>
                <option value="de">German</option><option value="es">Spanish</option>
                <option value="pt">Portuguese</option><option value="ja">Japanese</option>
              </select>
            </FG>
          </div>

          {/* Submit */}
          <button className="btn-primary" onClick={handleManualSubmit} disabled={loading}>
            {loading ? (
              <>
                <span style={{ width: 16, height: 16, border: '2px solid rgba(255,255,255,0.3)', borderTopColor: '#fff', borderRadius: '50%', display: 'inline-block', animation: 'spin 0.7s linear infinite' }} />
                Analysing…
              </>
            ) : '▶  Analyse Request'}
          </button>

          {/* Examples */}
          <div style={{ margin: '12px 0 5px', fontSize: 9, color: '#94A3B8', textAlign: 'center', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
            — Load Example Scenario —
          </div>
          <button className="btn-secondary" onClick={() => loadExample('restricted')}>
            🔴&nbsp; Restricted Supplier + Tight Deadline
          </button>
          <button className="btn-secondary" onClick={() => loadExample('missing')}>
            🟡&nbsp; Missing Budget &amp; Quantity
          </button>
          <button className="btn-secondary" onClick={() => loadExample('standard')}>
            🟢&nbsp; Standard Clean Request
          </button>
        </div>
      )}

      {/* JSON Tab */}
      {activeTab === 'json' && (
        <div>
          <div className="section-label">Upload or Paste a Request Object</div>
          <div
            className={`upload-zone ${isDragging ? 'drag' : ''}`}
            onClick={() => fileInputRef.current?.click()}
            onDragOver={e => { e.preventDefault(); setIsDragging(true); }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={e => {
              e.preventDefault(); setIsDragging(false);
              if (e.dataTransfer.files[0]) readFile(e.dataTransfer.files[0]);
            }}
          >
            <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.4 }}>⬆</div>
            <div style={{ fontSize: 13 }}>Drop <strong>requests.json</strong> here</div>
            <div style={{ fontSize: 11, marginTop: 5, color: '#94A3B8' }}>or click to browse · accepts .json</div>
            {fileName && (
              <div style={{ marginTop: 10, fontSize: 11, color: '#E30613' }}>
                📄 {fileName}
                {requestCount != null && requestCount > 1 && (
                  <span style={{ marginLeft: 8, background: '#1E293B', color: '#fff', borderRadius: 3, padding: '1px 7px', fontSize: 10, fontWeight: 700 }}>
                    📋 {requestCount} requests — batch mode
                  </span>
                )}
                {requestCount === 1 && (
                  <span style={{ marginLeft: 8, color: '#059669', fontSize: 10, fontWeight: 600 }}>✓ 1 request</span>
                )}
              </div>
            )}
          </div>
          <input type="file" ref={fileInputRef} accept=".json" style={{ display: 'none' }}
            onChange={e => { if (e.target.files?.[0]) readFile(e.target.files[0]); }} />

          <div style={{ marginTop: 14 }}>
            <label style={labelStyle}>Or paste a single request object</label>
            <textarea
              className="field-textarea"
              style={{ minHeight: 140, fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}
              placeholder={'{"request_id":"REQ-000001","request_text":"...","quantity":500,...}'}
              value={jsonText}
              onChange={e => setJsonText(e.target.value)}
            />
          </div>

          <FG>
            <label style={labelStyle}>AI Optimizer (Batch Options)</label>
             <div style={{ display: 'flex', gap: 15, marginTop: 4, flexWrap: 'wrap' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 11, color: '#334155', background: '#F1F5F9', padding: '4px 8px', borderRadius: 4, border: '1px solid #E2E8F0' }}>
                <input type="checkbox" checked={!!form.optBun} onChange={e => setField('optBun', e.target.checked)}
                  style={{ width: 13, height: 13, accentColor: '#4F46E5', cursor: 'pointer' }} />
                Run Demand Aggregator (Bundling)
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 11, color: '#334155', background: '#F1F5F9', padding: '4px 8px', borderRadius: 4, border: '1px solid #E2E8F0' }}>
                <input type="checkbox" checked={!!form.optNeg} onChange={e => setField('optNeg', e.target.checked)}
                  style={{ width: 13, height: 13, accentColor: '#4F46E5', cursor: 'pointer' }} />
                Run Negotiation Advisor
              </label>
              <label style={{ 
                display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 11, 
                color: '#fff', background: 'linear-gradient(135deg, #4F46E5, #7C3AED)', 
                padding: '4px 10px', borderRadius: 4, border: '1px solid #4338CA',
                boxShadow: '0 2px 4px rgba(79, 70, 229, 0.2)'
              }}>
                <input type="checkbox" checked={!!form.agenticMode} onChange={e => setField('agenticMode', e.target.checked)}
                  style={{ width: 13, height: 13, accentColor: '#fff', cursor: 'pointer' }} />
                ✨ Agentic Mode (External Data)
              </label>
            </div>
          </FG>

          <button className="btn-primary" onClick={handleJsonSubmit} disabled={loading}>
            {loading ? 'Analysing…' : '▶  Analyse JSON'}
          </button>
        </div>
      )}

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
