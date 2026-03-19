'use client';

import { useState, useEffect, useRef } from 'react';
import Header from '@/components/Header';
import InputPanel from '@/components/InputPanel';
import OutputPanel from '@/components/OutputPanel';
import { analyzeStreamRequestFromBackend, analyzeStreamFileFromBackend } from '@/lib/api';
import { adaptBackendResult } from '@/lib/adapter';
import { DEMO_RESULTS } from '@/lib/demo';
import type { PurchaseRequest, AnalysisResult, BackendResult } from '@/lib/types';

export type ThinkingStep = { title: string; description: string };

export type BatchEntry = {
  id: string;
  result: AnalysisResult | null;
  backendRaw: BackendResult | null;
  thinkingSteps: ThinkingStep[];
  error: string | null;
  status: 'pending' | 'processing' | 'done';
};

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
      setResult(demoResult);
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
          const adapted = adaptBackendResult(raw);
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
          request_channel: req.request_channel,
          request_language: req.request_language,
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
      setResult(adaptBackendResult(raw));
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
