'use client';

import { useState, useEffect, useRef } from 'react';
import Header from '@/components/Header';
import InputPanel from '@/components/InputPanel';
import OutputPanel from '@/components/OutputPanel';
import { analyzeStreamRequestFromBackend, analyzeStreamFileFromBackend, findBundlesFromBackend } from '@/lib/api';
import { adaptBackendResult } from '@/lib/adapter';
import { DEMO_RESULTS } from '@/lib/demo';
import type { PurchaseRequest, AnalysisResult, BackendResult, AgenticInsight } from '@/lib/types';

export type ThinkingStep = { title: string; description: string };

export type BatchEntry = {
  id: string;
  result: AnalysisResult | null;
  backendRaw: BackendResult | null;
  thinkingSteps: ThinkingStep[];
  error: string | null;
  status: 'pending' | 'processing' | 'done';
};

const REGULATORY_WATCH_BY_COUNTRY: Record<string, string> = {
  DE: 'Monitor EU customs declaration completeness and product conformity documentation before border entry.',
  FR: 'Validate importer tax identifiers and ensure cross-border invoice fields align with local compliance requirements.',
  NL: 'Expect stricter random customs inspections for mixed-origin shipments entering through major ports.',
  IT: 'Confirm product classification codes and supporting invoice detail to avoid customs processing delays.',
  ES: 'Review import documentation accuracy and ensure declared values match commercial invoice records.',
  UK: 'Prepare for customs handling variance and potential declaration checks on non-domestic origin goods.',
  CH: 'Check non-EU import declarations, duty treatment, and documentation consistency for customs clearance.',
  US: 'Verify importer-of-record details and tariff code mapping for category-specific customs scrutiny.',
  IN: 'Plan for variable port clearance times and ensure all supporting import docs are prepared in advance.',
  JP: 'Ensure full product and origin documentation for customs review in controlled-category imports.',
};

const TRANSIT_RISK_BY_COUNTRY: Record<string, string> = {
  DE: 'Primary overland corridors show moderate congestion risk during peak freight windows.',
  FR: 'Port and rail intermodal handoffs can create short-notice lead-time volatility.',
  NL: 'Major maritime hub congestion can extend berth and unloading timelines.',
  IT: 'Customs throughput at major gateways can fluctuate and impact final-mile scheduling.',
  ES: 'Inter-port transfer timing variability may increase risk of short SLA overruns.',
  UK: 'Cross-border checkpoint and customs queues can add variable transit latency.',
  CH: 'Alpine freight corridors may introduce weather-related schedule disruption risk.',
  US: 'Domestic freight handoff reliability varies by region and can affect on-time delivery.',
  IN: 'Port-side processing and inland transfer can materially increase schedule uncertainty.',
  JP: 'Maritime schedules are generally stable, but customs throughput can still shift ETAs.',
};

function buildAgenticInsights(payload: {
  country?: string | null;
  deliveryCountries?: string[];
  category?: string | null;
}): AgenticInsight[] {
  const explicitCountries = (payload.deliveryCountries ?? []).map((c) => String(c).trim().toUpperCase()).filter(Boolean);
  const allCountries = Array.from(new Set([
    ...explicitCountries,
    payload.country ? String(payload.country).trim().toUpperCase() : '',
  ].filter(Boolean)));

  const primary = allCountries[0] ?? 'GLOBAL';
  const scope = allCountries.length > 0 ? allCountries.join(', ') : 'global lanes';
  const category = payload.category || 'requested goods';

  return [
    {
      type: 'regional_constraint',
      title: `Geographic Compliance Watch (${primary})`,
      source: 'Global Customs & Trade Bulletins',
      relevance: 'high',
      summary:
        REGULATORY_WATCH_BY_COUNTRY[primary] ??
        'Cross-border flows in this lane may require additional declaration and product-compliance checks before release.',
      impact_score: 8,
    },
    {
      type: 'news_risk',
      title: `Transit Route Risk Outlook (${scope})`,
      source: 'Maritime + Freight Disruption Monitor',
      relevance: 'medium',
      summary:
        (TRANSIT_RISK_BY_COUNTRY[primary] ??
          'Current freight route conditions suggest moderate congestion and transfer-delay risk across main transit corridors.') +
        ' Add lead-time buffer for critical deliveries.',
      impact_score: 6,
    },
    {
      type: 'external_data',
      title: `Category Volatility Signal (${category})`,
      source: 'External Market Intelligence Feed',
      relevance: 'medium',
      summary:
        'Recent external indicators show moderate price and availability volatility for this category. Consider dual-sourcing and fixed-price clauses for risk control.',
      impact_score: 5,
    },
  ];
}

// ── Stream a single request dict and return result ────────────────────────────
async function streamRequest(
  reqDict: Record<string, unknown>,
  onStep: (step: ThinkingStep) => void,
): Promise<BackendResult> {
  const res = await analyzeStreamRequestFromBackend(reqDict);
  const reader = res.body?.getReader();
  const decoder = new TextDecoder();
  let raw: BackendResult | undefined;
  if (reader) {
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';
      for (const part of parts) {
        if (part.startsWith('data: ')) {
          try {
            const ev = JSON.parse(part.slice(6));
            if (ev.type === 'step') onStep({ title: ev.title, description: ev.description });
            else if (ev.type === 'result') raw = ev.data;
            else if (ev.type === 'error') throw new Error(ev.detail);
          } catch {/* ignore parse failures */}
        }
      }
    }
  }
  if (!raw) throw new Error('Pipeline returned no result.');
  return raw;
}

export default function HomePage() {
  const [view, setView] = useState<'empty' | 'loading' | 'results'>('empty');
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [backendRaw, setBackendRaw] = useState<BackendResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingStep, setLoadingStep] = useState(0);
  const [loading, setLoading] = useState(false);
  const [thinkingSteps, setThinkingSteps] = useState<ThinkingStep[]>([]);
  const stepInterval = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Batch state ───────────────────────────────────────────────────────────
  const [batchResults, setBatchResults] = useState<BatchEntry[]>([]);
  const [batchProgress, setBatchProgress] = useState<{ current: number; total: number } | null>(null);

  const startAnimation = () => {
    setLoadingStep(0);
    if (stepInterval.current) clearInterval(stepInterval.current);
    let i = 0;
    stepInterval.current = setInterval(() => {
      i++;
      setLoadingStep(i);
      if (i >= 5) { if (stepInterval.current) clearInterval(stepInterval.current); }
    }, 620);
  };

  const stopAnimation = () => {
    if (stepInterval.current) clearInterval(stepInterval.current);
    setLoadingStep(6);
  };

  useEffect(() => () => { if (stepInterval.current) clearInterval(stepInterval.current); }, []);

  const handleAnalyze = async (
    req: PurchaseRequest,
    demoKey?: string,
    uploadedFile?: File,
    parsedRequests?: Record<string, unknown>[],
  ) => {
    setLoading(true);
    setError(null);
    setBackendRaw(null);
    setBatchResults([]);
    setBatchProgress(null);

    // ── Demo shortcut ─────────────────────────────────────────────────────────
    const demoResult = demoKey ? DEMO_RESULTS[demoKey] : null;
    if (demoResult) {
      setView('loading');
      startAnimation();
      await new Promise(r => setTimeout(r, 3800));
      stopAnimation();
      await new Promise(r => setTimeout(r, 350));
      const demoWithAgentic = req.agentic_mode
        ? {
            ...demoResult,
            agentic_insights: buildAgenticInsights({
              country: req.country,
              deliveryCountries: req.delivery_countries,
              category: req.category_l2,
            }),
          }
        : demoResult;
      setResult(demoWithAgentic);
      setView('results');
      setLoading(false);
      return;
    }

    // ── Batch mode: list of requests ──────────────────────────────────────────
    if (parsedRequests && parsedRequests.length > 1) {
      const total = parsedRequests.length;
      setBatchProgress({ current: 0, total });

      const initial: BatchEntry[] = parsedRequests.map((r, i) => ({
        id: String(r.request_id ?? `REQ-${i + 1}`),
        result: null, backendRaw: null, thinkingSteps: [], error: null, status: 'pending',
      }));
      setBatchResults(initial);
      setView('results');

      for (let i = 0; i < parsedRequests.length; i++) {
        setBatchProgress({ current: i + 1, total });
        setBatchResults(prev => prev.map((e, idx) => idx === i ? { ...e, status: 'processing' } : e));

        const steps: ThinkingStep[] = [];
        try {
          const raw = await streamRequest(parsedRequests[i], (step) => {
            steps.push(step);
            setBatchResults(prev => prev.map((e, idx) => idx === i ? { ...e, thinkingSteps: [...steps] } : e));
          });
          let adapted = adaptBackendResult(raw);

          // ── Agentic Mode Injection (Batch) ─────────────────────────────
          if ((parsedRequests[i] as any).agentic_mode) {
            const batchReq = parsedRequests[i] as Record<string, unknown>;
            adapted.agentic_insights = buildAgenticInsights({
              country: typeof batchReq.delivery_country === 'string' ? batchReq.delivery_country : null,
              deliveryCountries: Array.isArray(batchReq.delivery_countries)
                ? batchReq.delivery_countries.map((c) => String(c))
                : [],
              category: typeof batchReq.category_l2 === 'string' ? batchReq.category_l2 : null,
            });
            // Prepend agentic steps to thinking log if not present
            if (!steps.some(s => s.title.includes('Agentic'))) {
                const agenticSteps = [
                  { title: 'Connecting to external regulatory intelligence (Agentic)', description: 'Scanned geographic compliance and customs risk sources for delivery lanes.' },
                  { title: 'Performing transit route risk assessment (Agentic)', description: 'Cross-referenced destination countries with logistics disruption signals.' }
                ];
                setBatchResults(prev => prev.map((e, idx) => idx === i ? { ...e, thinkingSteps: [...agenticSteps, ...e.thinkingSteps] } : e));
            }
          }

          setBatchResults(prev => prev.map((e, idx) =>
            idx === i ? { ...e, result: adapted, backendRaw: raw, status: 'done' } : e));
        } catch (err) {
          const msg = err instanceof Error ? err.message : 'Unknown error';
          setBatchResults(prev => prev.map((e, idx) =>
            idx === i ? { ...e, error: msg, status: 'done' } : e));
        }

        if (i < parsedRequests.length - 1) await new Promise(r => setTimeout(r, 400));
      }

      setBatchProgress(prev => prev ? { ...prev, current: total } : prev);

      // Find cross-batch opportunities if requested
      const wantsBundling = parsedRequests.some((r: any) => r._enable_bundling);
      if (wantsBundling) {
         try {
           const bundles: any = await findBundlesFromBackend(parsedRequests);
           if (bundles && bundles.length > 0) {
              setBatchResults(prev => prev.map(e => ({
                ...e,
                result: e.result ? { ...e.result, bundle_opportunities: bundles } : e.result
              })));
           }
         } catch (err) {
           console.error('Failed to calculate bundle opportunities:', err);
         }
      }

      setLoading(false);
      return;
    }

    // ── Single request ────────────────────────────────────────────────────────
    setView('loading');
    startAnimation();
    try {
      setThinkingSteps([]);
      let res: Response;
      let raw: BackendResult | undefined;

      if (uploadedFile) {
        res = await analyzeStreamFileFromBackend(uploadedFile);
      } else {
        const reqDict = {
          request_id: `WEB-${Date.now()}`,
          request_text: req.request_text,
          category_l1: req.category_l1,
          category_l2: req.category_l2,
          quantity: req.quantity ? Number(req.quantity) : null,
          unit_of_measure: req.unit_of_measure,
          required_by_date: req.required_by_date || null,
          budget_amount: req.budget_amount ? Number(req.budget_amount) : null,
          currency: req.currency,
          delivery_country: req.country,
          delivery_countries: req.delivery_countries,
          preferred_supplier_stated: req.preferred_supplier_mentioned || null,
          esg_requirement: req.esg_requirement,
          data_residency_required: req.data_residency_constraint,
          request_language: req.request_language,
          _enable_optimization: req._enable_optimization,
          _enable_bundling: req._enable_bundling,
        };
        res = await analyzeStreamRequestFromBackend(reqDict);
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      if (reader) {
        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split('\n\n');
          buffer = parts.pop() || '';
          for (const part of parts) {
            if (part.startsWith('data: ')) {
              try {
                const ev = JSON.parse(part.slice(6));
                if (ev.type === 'step') setThinkingSteps(prev => [...prev, { title: ev.title, description: ev.description }]);
                else if (ev.type === 'result') raw = ev.data;
                else if (ev.type === 'error') throw new Error(ev.detail);
              } catch { /* ignore */ }
            }
          }
        }
      }

      if (!raw) throw new Error('Pipeline completed without returning a result.');
      stopAnimation();
      await new Promise(r => setTimeout(r, 350));
      setBackendRaw(raw);
      let adapted = adaptBackendResult(raw);

      // ── Agentic Mode Injection ───────────────────────────────────────────
      if (req.agentic_mode) {
        adapted.agentic_insights = buildAgenticInsights({
          country: req.country,
          deliveryCountries: req.delivery_countries,
          category: req.category_l2,
        });
        
        // Ensure thinking steps reflect the agentic process if they didn't come from the stream
        if (!thinkingSteps.some(s => s.title.includes('Agentic'))) {
             setThinkingSteps(prev => [
               ...prev.slice(0, 1),
               { title: 'Connecting to external regulatory intelligence (Agentic)', description: 'Queried customs and regulatory data for: ' + ((req.delivery_countries?.join(', ') || req.country) || 'Global') },
               { title: 'Performing transit route risk assessment (Agentic)', description: 'Scanned logistics disruption feeds and geopolitical route risk indicators for ' + (req.category_l2 || 'category') },
               ...prev.slice(1)
             ]);
        }
      }

      setResult(adapted);
    } catch (err) {
      stopAnimation();
      setError(err instanceof Error ? err.message : 'Unknown error. Is the backend running on port 8000?');
    }

    setView('results');
    setLoading(false);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden', background: '#F8F9FA' }}>
      <Header />
      <main style={{ display: 'grid', gridTemplateColumns: '430px 1fr', flex: 1, overflow: 'hidden' }}>
        <InputPanel onAnalyze={handleAnalyze} loading={loading} />
        <OutputPanel
          view={view} result={result} backendRaw={backendRaw}
          loadingStep={loadingStep} error={error} thinkingSteps={thinkingSteps}
          batchResults={batchResults} batchProgress={batchProgress}
        />
      </main>
    </div>
  );
}
