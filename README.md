# ARIA - Audit-Ready Intelligence Agent

ARIA is an AI-assisted procurement decision platform built for the ChainIQ START Hack context.
It helps teams analyze purchase requests, evaluate policy compliance, shortlist suppliers, trigger escalations, and produce audit-ready outputs.

The solution has:
- A **FastAPI backend** for rule engine, analytics, streaming analysis, and optimization modules
- A **Next.js frontend** for request submission, live reasoning stream, results visualization, and analytics dashboard

## What the Project Does

- Parses and evaluates procurement requests (manual form or JSON)
- Applies deterministic policy and supplier logic
- Produces recommendation outcomes with escalation paths
- Streams intermediate thinking/processing steps to the UI
- Supports batch request processing
- Provides analytics views from historical data
- Exports audit-style report output

## Repository Structure

- `backend/` - FastAPI service and procurement pipeline logic
- `frontend/` - Next.js web app

## Prerequisites

- **Python** 3.10+ (recommended 3.11)
- **Node.js** 20+ and npm
- PowerShell or any terminal

Optional (for richer NLP/rationale layers):
- `GOOGLE_API_KEY` in environment (or `.env` in backend runtime context)

If no API key is provided, the pipeline still runs with deterministic logic and fallbacks.

## Quick Start

### 1) Start Backend

Open a terminal in `backend/`:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Backend runs on:
- `http://localhost:8000`
- Health check: `http://localhost:8000/health`

### 2) Start Frontend

Open a second terminal in `frontend/`:

```powershell
cd frontend
npm install
npm run dev
```

Frontend runs on:
- `http://localhost:3000`

By default, frontend API calls target `http://localhost:8000`.
You can override with:
- `NEXT_PUBLIC_API_URL`

## Main API Endpoints

- `GET /health` - service health
- `POST /analyze` - single request analysis
- `POST /analyze-stream` - streaming analysis events + final result
- `POST /bundle` - bundle opportunity analysis for request arrays
- `GET /analytics` - historical cycle and concentration analytics

## Typical Demo Flow

1. Start backend and frontend
2. Open `http://localhost:3000`
3. Submit a request from the manual form or upload JSON
4. Watch the streamed reasoning steps
5. Review policy evaluation, supplier shortlist, recommendation, and audit trail
6. Open Analytics page from top navigation

## Notes for Pitch / Demo

- The core deterministic procurement pipeline is operational end-to-end
- Some advanced modules are dependency-gated (API keys / data availability)
- Demo scenarios are available in the frontend for stable walkthroughs

## Troubleshooting

- If UI cannot connect, verify backend is running on port `8000`
- If PowerShell blocks venv activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

- If `python` maps to a different version, use `py`:

```powershell
py -m venv .venv
py main.py
```

