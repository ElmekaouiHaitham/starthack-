# ARIA — Audit-Ready Intelligence Agent

> **Where procurement meets proof.**

Built in **36 hours** at [START Hack 2026](https://www.starthack.eu/) · Saint-Gallen, Switzerland  
Challenge sponsor: **ChainIQ Group AG**  
One of two teams representing Morocco and ENSAM Rabat at this pan-European hackathon.

---

## What is ARIA?

ARIA is an AI-enhanced procurement analysis and decision-support platform designed to automate, evaluate, and optimize purchasing workflows.

Organizations receive hundreds of procurement requests by email — unstructured, inconsistent, often missing key data. ARIA transforms this chaos into structured, auditable purchasing decisions. Every decision is traceable, every escalation is logged, and every cycle produces a downloadable audit report.

**Slogan:** *Where procurement meets proof.*

---

## The Problem

Procurement teams waste hours manually parsing emails, checking budgets, verifying supplier compliance, and escalating edge cases. There is no audit trail. Decisions are inconsistent. Strategic opportunities (bulk discounts, demand bundling) go unnoticed.

## The Solution

ARIA ingests raw procurement emails — single or in batch — and runs them through a **4-layer intelligent pipeline**:

```
Raw Email(s)
     │
     ▼
┌─────────────────────────┐
│  1. LLM Extraction      │  ← Parses quantity, budget, language, policy signals
└─────────────────────────┘
     │
     ▼
┌─────────────────────────┐
│  2. Rule Engine         │  ← Policy checks, currency normalization,
│                         │    supplier eligibility, threshold validation
└─────────────────────────┘
     │
     ▼
┌─────────────────────────┐
│  3. ML Score Calibrator │  ← Re-ranks suppliers using logistic regression
│                         │    trained on historical award data (CV AUC 0.991)
└─────────────────────────┘
     │
     ▼
┌─────────────────────────┐
│  4. Rationale Generator │  ← LLM writes audit-quality prose for each decision
└─────────────────────────┘
     │
     ├──── Within policy ──────────────────► Auto-approved + full audit log
     │
     └──── Ambiguous / Out-of-policy ──────► Human escalation queue
                                                      │
                                                      ▼
                                            Decision logged + audit trail
```

---

## Key Features

### 🧠 Intelligent Extraction
- LLM-powered parsing of unstructured procurement emails using **Gemini 2.5 Pro**
- Extracts: **Quantity**, **Budget**, **Currency**, **Deadlines**, **Supplier**, **Item spec**
- Multi-language support — detects request language and auto-translates to English
- Detects policy-refusal phrases and contradictions between free text and structured fields

### ⚙️ Deterministic Rule Engine
- Policy compliance checks against configurable approval thresholds
- Multi-currency normalization (EUR, CHF, USD, and more)
- Supplier eligibility: geographic restrictions, MOQ, ESG, data residency
- Demand-bundling opportunity detection across batch requests

### 📊 ML-Calibrated Scoring
- Logistic regression trained on historical award data — **CV AUC 0.991**
- Re-ranks supplier shortlist with data-driven weights instead of hard-coded values
- Adapts automatically to ESG-required vs. standard procurement scenarios

### 🔁 Human-in-the-Loop Escalation
- Ambiguous or policy-violating requests flagged with structured reasoning
- Every escalation includes "why?" — attached to the audit trail
- Human decisions are permanently logged

### 📡 Real-Time Streaming UI
- Live "thinking steps" streamed via Server-Sent Events
- Users see each pipeline layer execute in real time — no black box

### 📈 Analytics Dashboard
- Historical procurement cycle analytics and KPIs
- Supplier concentration risk monitoring
- Downloadable audit reports per procurement cycle

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | Python · FastAPI · Uvicorn |
| AI / LLM | Google Gemini 2.5 Pro · LangChain |
| Data Science | Pandas · scikit-learn · Pydantic |
| Frontend | Next.js 16 · React 19 · TypeScript · Tailwind CSS |
| Streaming | Server-Sent Events (SSE) |

---

## Project Structure

```
starthack-/
├── backend/              # FastAPI application + 4-layer AI pipeline
│   ├── main.py           # API entry point & routes
│   ├── src/              # Core pipeline modules
│   │   ├── pipeline.py           # Main orchestrator
│   │   ├── nlp_extractor.py      # LLM extraction layer (Gemini)
│   │   ├── rule_engine_v3.py     # Deterministic rule engine
│   │   ├── scoring_calibrator.py # ML-based score calibration
│   │   └── rationale_generator.py# LLM rationale generation
│   └── data/             # CSVs, policies JSON, historical awards
│
└── frontend/             # Next.js dashboard
    └── src/
        ├── app/          # Pages & routing
        ├── components/   # Header, InputPanel, OutputPanel
        └── lib/          # API client, types & data adapters
```

---

## Getting Started

### Prerequisites
- Python 3.10+
- Node.js 18+
- Google Gemini API key (`GOOGLE_API_KEY`)

### Backend

```bash
cd backend
pip install -r requirements.txt
# Create a .env file:  GOOGLE_API_KEY=your_key_here
uvicorn main:app --reload
```

API docs available at `http://localhost:8000/docs`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard available at `http://localhost:3000`

---

## Demo

📹 [Watch the demo video](https://canva.link/2uzlodycthnd11q)

---

## Hackathon Context

- **Event:** START Hack 2026 — Europe's most entrepreneurial student hackathon
- **Location:** University of St. Gallen, Switzerland
- **Duration:** 36 hours non-stop
- **Challenge:** ChainIQ Group AG — Audit-Ready Autonomous Sourcing Agent
- **Team:** 2 engineers representing Morocco at this pan-European event

---

## Status & Roadmap

The core pipeline — email ingestion, LLM extraction, rule engine, calibrated scoring, escalation, and audit trail — is **fully functional**.

- [ ] Full agentic mode (autonomous multi-step decision chains)
- [ ] Complete TypeScript type coverage on frontend
- [ ] Persistent database layer (currently in-memory)
- [ ] Production deployment

---

## Team

Built with ❤️ under pressure at START Hack 2026.

**Haitham Elmekaoui** — [github.com/ElmekaouiHaitham](https://github.com/ElmekaouiHaitham) · [LinkedIn](https://linkedin.com/in/haitham-elmekaoui)

**Nizar Elyamani** — Backend & AI pipeline engineering
