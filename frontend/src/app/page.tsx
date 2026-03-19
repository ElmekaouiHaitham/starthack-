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

export default function HomePage() {
  const [view, setView] = useState<'empty' | 'loading' | 'results'>('empty');
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [backendRaw, setBackendRaw] = useState<BackendResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingStep, setLoadingStep] = useState(0);
  const [loading, setLoading] = useState(false);
  const [thinkingSteps, setThinkingSteps] = useState<ThinkingStep[]>([]);
  const stepInterval = useRef<ReturnType<typeof setInterval> | null>(null);

  const startAnimation = () => {
    setLoadingStep(0);
    if (stepInterval.current) clearInterval(stepInterval.current);
    let i = 0;
    stepInterval.current = setInterval(() => {
      i++;
      setLoadingStep(i);
      if (i >= 5) {
        if (stepInterval.current) clearInterval(stepInterval.current);
      }
    }, 620);
  };

  const stopAnimation = () => {
    if (stepInterval.current) clearInterval(stepInterval.current);
    setLoadingStep(6);
  };

  useEffect(() => () => { if (stepInterval.current) clearInterval(stepInterval.current); }, []);

  const handleAnalyze = async (req: PurchaseRequest, demoKey?: string, uploadedFile?: File) => {
    setLoading(true);
    setError(null);
    setBackendRaw(null);
    setView('loading');
    startAnimation();

    // Demo scenarios use local pre-computed results (no backend call)
    const demoResult = demoKey ? DEMO_RESULTS[demoKey] : null;
    if (demoResult) {
      await new Promise(r => setTimeout(r, 3800));
      stopAnimation();
      await new Promise(r => setTimeout(r, 350));
      setResult(demoResult);
      setView('results');
      setLoading(false);
      return;
    }

    // Real backend call
    try {
      setThinkingSteps([]);
      let res: Response;
      let raw: BackendResult | undefined;
      
      if (uploadedFile) {
        res = await analyzeStreamFileFromBackend(uploadedFile);
      } else {
        // Build a request dict matching the pipeline's expected shape
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
               const dataStr = part.slice(6);
               try {
                 const ev = JSON.parse(dataStr);
                 if (ev.type === 'step') {
                   setThinkingSteps(prev => [...prev, { title: ev.title, description: ev.description }]);
                 } else if (ev.type === 'result') {
                   raw = ev.data;
                 } else if (ev.type === 'error') {
                   throw new Error(ev.detail);
                 }
               } catch (e) {
                 console.error('Failed to parse SSE', dataStr);
               }
            }
          }
        }
      }

      if (!raw) {
        throw new Error('Pipeline completed without returning a result.');
      }
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
        <OutputPanel view={view} result={result} backendRaw={backendRaw} loadingStep={loadingStep} error={error} thinkingSteps={thinkingSteps} />
      </main>
    </div>
  );
}

