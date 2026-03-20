"""
main.py  —  ChainIQ FastAPI Server
====================================
Exposes the 4-layer procurement pipeline as a REST API.

Endpoints
---------
POST /analyze
    Accepts either:
      • application/json        – single request dict (or array, first item used)
      • multipart/form-data     – uploaded .json file (field name: "file")

GET  /health
    Returns {"status": "ok"} once the pipeline is ready.
"""

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

# ── add src/ to sys.path so pipeline imports work ──────────────────────────
SRC_DIR = Path(__file__).parent / "src"
sys.path.insert(0, str(SRC_DIR))

from pipeline import Pipeline  # noqa: E402  (after sys.path insert)
from historical_analytics import ConcentrationRiskMonitor, EscalationCycleAnalyzer

DATA_DIR = Path(__file__).parent / "data"


# ══════════════════════════════════════════════════════════════════════════════
# LIFESPAN — initialise pipeline once at startup
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Initialising ChainIQ pipeline…")
    app.state.pipeline = Pipeline(data_dir=SRC_DIR, enable_nlp=True, enable_rationale=True)
    print("Initialising Historical Analytics…")
    app.state.cycle_analyzer = EscalationCycleAnalyzer(data_dir=DATA_DIR)
    app.state.concentration_monitor = ConcentrationRiskMonitor(data_dir=DATA_DIR)
    print("Pipeline ready — server accepting requests.")
    yield
    print("Shutting down.")


# ══════════════════════════════════════════════════════════════════════════════
# APP
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="ChainIQ Procurement API",
    description="4-layer AI procurement pipeline: NLP → Rules → Calibration → Rationale",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _run_pipeline(app_state, request_dict: dict) -> dict:
    """Run the pipeline and wrap any exception into an HTTPException."""
    try:
        return app_state.pipeline.run(request_dict)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc


def _parse_json_bytes(raw: bytes) -> dict:
    """Parse JSON bytes, handling UTF-8 BOM, UTF-16, and various encodings."""
    # Try encodings in order of likelihood
    for enc in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    else:
        raise HTTPException(status_code=422, detail="Could not decode request body as text.")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid JSON: {exc}") from exc

    if isinstance(data, list):
        if not data:
            raise HTTPException(status_code=422, detail="JSON array is empty.")
        return data[0]
    if isinstance(data, dict):
        return data
    raise HTTPException(status_code=422, detail="JSON must be an object or non-empty array.")


async def _extract_request_dict(request: Request, file: UploadFile | None = None) -> dict:
    """Read request payload from uploaded file or JSON body."""
    content_type = request.headers.get("content-type", "")

    if file is not None:
        return _parse_json_bytes(await file.read())
    if "application/json" in content_type:
        return _parse_json_bytes(await request.body())

    raise HTTPException(
        status_code=415,
        detail="Unsupported content type. Use application/json or multipart/form-data with a .json file.",
    )


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health", tags=["meta"])
async def health_check():
    return {"status": "ok"}


@app.get("/analytics", tags=["analytics"])
async def get_analytics(request: Request):
    """
    Returns historical analytics: cycle time profiles and portfolio concentration.
    """
    cycle_analyzer: EscalationCycleAnalyzer = request.app.state.cycle_analyzer
    concentration: ConcentrationRiskMonitor = request.app.state.concentration_monitor

    profiles = {k: asdict(v) for k, v in cycle_analyzer.profiles().items()}
    segments = [asdict(s) for s in concentration.segments()]

    return {
        "cycle_profiles": profiles,
        "concentration_segments": segments
    }


@app.post("/analyze", tags=["pipeline"])
async def analyze(request: Request, file: UploadFile | None = File(default=None)):
    """
    Analyze a single procurement request.

    Accepts:
    - JSON body  (Content-Type: application/json)
    - Uploaded .json file  (multipart/form-data, field="file")
    """
    request_dict = await _extract_request_dict(request, file)
    return _run_pipeline(request.app.state, request_dict)

@app.post("/analyze-stream", tags=["pipeline"])
async def analyze_stream(request: Request, file: UploadFile | None = File(default=None)):
    """
    Analyze a single procurement request, streaming the execution steps back to the client.
    """
    request_dict = await _extract_request_dict(request, file)

    async def event_generator():
        try:
            for step in request.app.state.pipeline.run_stream(request_dict):
                yield f"data: {json.dumps(step)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/bundle", tags=["pipeline"])
async def bundle_requests(request: Request):
    """
    Accepts a list of JSON requests and returns bundle opportunities.
    """
    raw = await request.body()
    try:
        text = raw.decode("utf-8")
        data = json.loads(text)
        if not isinstance(data, list):
            raise HTTPException(status_code=422, detail="Expected JSON array")
        from dataclasses import asdict
        opps = request.app.state.pipeline.aggregator.find_opportunities(data)
        return [asdict(o) for o in opps]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Keep single-process startup by default on Windows to avoid stale reloader
    # workers accumulating and intermittently hanging requests on port 8000.
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
