# ARIA — Backend

> FastAPI server powering the 4-layer AI procurement pipeline.

---

## Overview

The backend is a **Python / FastAPI** application that exposes the ARIA pipeline as a REST API. It orchestrates four layers of intelligence — LLM extraction, a deterministic rule engine, ML-calibrated scoring, and LLM rationale generation — and streams each step back to the frontend in real time via Server-Sent Events (SSE).

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         FastAPI  (main.py)                       │
│   POST /analyze           POST /analyze-stream     GET /analytics│
└────────────────────────┬─────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Pipeline  (pipeline.py)                     │
│                                                                  │
│  Layer 1: NLPExtractor         (nlp_extractor.py)                │
│    • Gemini 2.5 Pro call                                         │
│    • Language detection + full English translation               │
│    • Quantity / budget extraction from free text                 │
│    • Policy-refusal phrase detection                             │
│    • Contradiction detection (deterministic Python)              │
│    • Results cached in nlp_cache.json                            │
│                         │                                        │
│  Layer 2: ProcurementRuleEngine  (rule_engine_v3.py)             │
│    • Supplier eligibility: geography, MOQ, ESG, data residency   │
│    • Pricing tier selection with FX normalization                │
│    • Approval threshold routing (L0–L4 tiers)                   │
│    • Escalation generation with blocking flags                   │
│    • Multi-criteria scoring: quality, risk, ESG, lead time       │
│                         │                                        │
│  Layer 3: ScoringCalibrator    (scoring_calibrator.py)           │
│    • Logistic regression trained on historical_awards.csv        │
│    • Cross-validated AUC: 0.991                                  │
│    • Re-ranks shortlist with data-driven weights                 │
│    • Separate weight sets: ESG-required vs standard              │
│                         │                                        │
│  Layer 4: RationaleGenerator   (rationale_generator.py)          │
│    • Gemini 2.5 Pro call                                         │
│    • Few-shot examples pulled from same-category historical awards│
│    • Generates per-supplier recommendation_notes                 │
│    • Generates overall recommendation.reason paragraph           │
│    • Results cached in rationale_cache.json                      │
│                         │                                        │
│  Ancillary: EscalationCycleAnalyzer / ConcentrationRiskMonitor   │
│             (historical_analytics.py) — serves /analytics        │
└──────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
backend/
├── main.py                    # FastAPI app, lifespan, routes
├── requirements.txt           # Python dependencies
├── .env                       # GOOGLE_API_KEY (not committed)
│
├── src/                       # Pipeline modules
│   ├── pipeline.py            # Orchestrator — wires all 4 layers
│   ├── nlp_extractor.py       # Layer 1 — Gemini LLM extraction
│   ├── rule_engine_v3.py      # Layer 2 — deterministic rule engine
│   ├── scoring_calibrator.py  # Layer 3 — ML score calibration
│   ├── rationale_generator.py # Layer 4 — LLM rationale prose
│   └── historical_analytics.py# Analytics: cycle profiles & concentration risk
│
├── data/
│   ├── requests.json          # 304 raw procurement requests (hackathon dataset)
│   ├── policies.json          # Approval tier definitions and policy rules
│   ├── suppliers.csv          # Supplier master data
│   ├── pricing.csv            # Supplier × category pricing tiers
│   ├── categories.csv         # Category taxonomy (L1 / L2)
│   ├── historical_awards.csv  # Past award decisions (training data)
│   ├── merged_v2.csv          # Merged feature set for calibration training
│   ├── nlp_cache.json         # NLP extraction cache (keyed by request_id)
│   └── rationale_cache.json   # Rationale generation cache
│
└── notebookes/                # Exploration & testing notebooks
    └── test_gaps.py
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Returns `{"status": "ok"}` once pipeline is ready |
| `POST` | `/analyze` | Process a single request, return full JSON output |
| `POST` | `/analyze-stream` | Same as `/analyze` but streams thinking steps via SSE |
| `POST` | `/bundle` | Accept a JSON array, return demand-bundling opportunities |
| `GET` | `/analytics` | Return cycle profiles and concentration risk data |

### `/analyze` — Request Format

Accepts `application/json` **or** `multipart/form-data` (upload a `.json` file):

```json
{
  "request_id": "REQ-000042",
  "request_text": "We need 200 laptops for our Geneva office...",
  "quantity": 200,
  "budget_amount": 180000,
  "currency": "CHF",
  "category_l1": "IT Hardware",
  "category_l2": "Laptops",
  "required_by_date": "2026-07-01",
  "delivery_region": "EMEA",
  "esg_requirement": true,
  "preferred_supplier_mentioned": "Dell"
}
```

### `/analyze` — Response Format (abbreviated)

```json
{
  "request_id": "REQ-000042",
  "recommendation": {
    "status": "approved",
    "reason": "Dell Technologies meets all policy requirements...",
    "preferred_supplier_rationale": "..."
  },
  "supplier_shortlist": [
    {
      "rank": 1,
      "supplier_name": "Dell Technologies",
      "score": 0.8732,
      "total_price_in_req_currency": 172000,
      "lead_time_days": 14,
      "recommendation_note": "Ranked first due to..."
    }
  ],
  "escalations": [],
  "audit_trail": { },
  "_pipeline": {
    "nlp_enabled": true,
    "rationale_enabled": true,
    "calibration_auc": 0.991,
    "pipeline_version": "v1.0"
  }
}
```

### `/analyze-stream` — SSE Event Format

Events are emitted as `data: <JSON>\n\n` in this sequence:

```
data: {"type": "step", "title": "Request Received", "description": "..."}
data: {"type": "step", "title": "Reading the Request", "description": "..."}
data: {"type": "step", "title": "Checking Policies", "description": "..."}
data: {"type": "step", "title": "Finding Best Options", "description": "..."}
data: {"type": "step", "title": "Writing Recommendation", "description": "..."}
data: {"type": "result", "data": { <full output JSON> }}
```

---

## Layer Deep-Dives

### Layer 1 — NLP Extractor (`nlp_extractor.py`)

Uses **Gemini 2.5 Pro** with `response_mime_type="application/json"` for structured output.

**What it extracts:**
- Language detection (ISO 639-1) + full English translation
- Quantity: primary, per-location vs total rollout, unit
- Budget: amount + currency (handles European number formats: `360.000` = 360,000)
- Policy-refusal signals: `no_exception_mandate`, `skip_competitive_tender`, `single_supplier_waiver`, `waive_review`
- Product specification (e.g. `MacBook Pro 16-inch`) + budget gap flag
- ESG and data residency signals
- Urgency level

**Contradiction detection (deterministic — no LLM):**

| Type | Severity | Trigger |
|------|----------|---------|
| `QUANTITY_MISMATCH` | critical | Text qty differs from field qty by > 10% |
| `BUDGET_MISMATCH` | critical | Text budget differs from field by > 5% |
| `POLICY_REFUSAL_SINGLE_SUP` | critical | Single-supplier mandate in text |
| `POLICY_REFUSAL_SKIP_TENDER` | critical | Request to skip competitive tender |
| `SPEC_BUDGET_GAP` | high | Named spec implies cost > budget |
| `ROLLOUT_QTY_AMBIGUITY` | high | Per-location qty ≠ total rollout qty |
| `PREFERRED_SUPPLIER_MISMATCH` | warning | Text supplier ≠ field preferred supplier |
| `LANGUAGE_MISMATCH` | warning | Detected language ≠ `request_language` field |

**Caching:** Results stored in `data/nlp_cache.json` keyed by `request_id`. Pass `force_refresh=True` to bypass.

---

### Layer 2 — Rule Engine (`rule_engine_v3.py`)

A fully deterministic engine — no LLM, no randomness.

**Processing steps:**
1. **Category lookup** — resolves `category_l1/l2` from taxonomy
2. **Supplier filtering** — applies geographic, ESG, data residency, and capacity restrictions
3. **Pricing tier selection** — selects the correct volume/pricing tier for each eligible supplier
4. **FX normalization** — converts all prices to the request currency
5. **MOQ validation** — checks minimum order quantities
6. **Lead time feasibility** — checks against `required_by_date`
7. **Budget sufficiency** — marks each supplier's `budget_sufficient` flag
8. **Approval threshold routing** — maps total value to L0–L4 approval tiers
9. **Escalation generation** — any policy violation creates a structured escalation with a `blocking` flag
10. **Shortlist ranking** — initial score computed from weighted criteria

**Approval tiers:**

| Tier | Value | Quotes required |
|------|-------|-----------------|
| L0 | < €5,000 | 1 |
| L1 | €5k–€25k | 2 |
| L2 | €25k–€100k | 3 |
| L3 | €100k–€500k | 3 + manager sign-off |
| L4 | > €500k | Full tender |

---

### Layer 3 — Scoring Calibrator (`scoring_calibrator.py`)

Replaces the rule engine's fixed scoring weights with **data-driven weights** learned from `historical_awards.csv`.

**Training:**
- Features: `savings_pct`, `quality_score`, `risk_score`, `esg_score`, `lead_time_days`, `preferred`, `incumbent`
- Target: `awarded` (binary)
- Model: logistic regression with cross-validation
- Cross-validated AUC: **0.991**
- Two weight sets: `esg_required=True` and `esg_required=False`

**At inference:**
- Computes `savings_pct = (budget - total_price) / budget * 100`
- Applies calibrated weights to re-score each shortlisted supplier
- Sorts shortlist by new `score`; writes `score_weights` and `savings_pct_vs_budget` to output

---

### Layer 4 — Rationale Generator (`rationale_generator.py`)

Uses **Gemini 2.5 Pro** to generate human-readable, audit-quality prose.

**Prompt strategy:**
- System prompt: act as a senior procurement analyst, no invention of numbers
- Few-shot examples: 3 real `decision_rationale` strings pulled from `historical_awards.csv` in the same category
- Input: compact structured summary of shortlist, exclusions, escalations, policy context
- Output: `supplier_notes` (per supplier), `excluded_summary`, `recommendation_reason`, `preferred_supplier_rationale`

**Fallback:** If the API call fails, a deterministic template string is generated from the structured data — the pipeline never breaks.

**Caching:** Results stored in `data/rationale_cache.json` keyed by `rationale_{request_id}`.

---

## Setup & Running

### 1. Environment

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Create a `.env` file in `backend/`:

```
GOOGLE_API_KEY=your_gemini_api_key_here
```

### 2. Start the server

```bash
uvicorn main:app --reload --port 8000
```

Interactive API docs: `http://localhost:8000/docs`

### 3. CLI — run the pipeline directly

```bash
# Process all 304 requests
python src/pipeline.py

# First 10 only
python src/pipeline.py --n 10

# Single request by ID
python src/pipeline.py --id REQ-000004

# Offline mode (skip LLM layers)
python src/pipeline.py --no-nlp --no-rationale

# Force re-run ignoring caches
python src/pipeline.py --refresh
```

---

## Dependencies

```
fastapi              # API framework
uvicorn[standard]    # ASGI server
python-multipart     # File upload support
google-genai         # Gemini API client (Layer 1 & 4)
langchain            # LLM orchestration utilities
langchain-google-genai
python-dotenv        # .env loading
pandas               # Data processing
scikit-learn         # Logistic regression (Layer 3)
pydantic             # Data validation
```

---

## Data Files

| File | Description |
|------|-------------|
| `requests.json` | 304 procurement requests — the hackathon challenge dataset |
| `policies.json` | Approval tier thresholds, quote requirements, fast-track rules |
| `suppliers.csv` | ~50 suppliers with country, ESG score, risk score, certifications |
| `pricing.csv` | Supplier × category × volume pricing tiers |
| `categories.csv` | L1 / L2 category taxonomy |
| `historical_awards.csv` | Past procurement awards with outcome, savings, rationale |
| `merged_v2.csv` | Feature-engineered dataset used for calibrator training |

---

## Authors

**Haitham Elmekaoui** — [github.com/ElmekaouiHaitham](https://github.com/ElmekaouiHaitham) · [LinkedIn](https://linkedin.com/in/haitham-elmekaoui)

**Nizar Elyamani** — Backend & AI pipeline engineering

Built at START Hack 2026 · ChainIQ challenge · 36 hours.
