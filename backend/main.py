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
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

# ── add src/ to sys.path so pipeline imports work ──────────────────────────
SRC_DIR = Path(__file__).parent / "src"
sys.path.insert(0, str(SRC_DIR))

from pipeline import Pipeline  # noqa: E402  (after sys.path insert)

DATA_DIR = Path(__file__).parent / "data"


# ══════════════════════════════════════════════════════════════════════════════
# LIFESPAN — initialise pipeline once at startup
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Initialising ChainIQ pipeline…")
    app.state.pipeline = Pipeline(data_dir=SRC_DIR, enable_nlp=True, enable_rationale=True)
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


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health", tags=["meta"])
async def health_check():
    return {"status": "ok"}


@app.post("/analyze", tags=["pipeline"])
async def analyze(request: Request, file: UploadFile | None = File(default=None)):
    """
    Analyze a single procurement request.

    Accepts:
    - JSON body  (Content-Type: application/json)
    - Uploaded .json file  (multipart/form-data, field="file")
    """
    content_type = request.headers.get("content-type", "")

    if file is not None:
        # ── File upload path ──────────────────────────────────────────────────
        raw = await file.read()
        request_dict = _parse_json_bytes(raw)

    elif "application/json" in content_type:
        # ── JSON body path ─────────────────────────────────────────────────
        raw = await request.body()
        request_dict = _parse_json_bytes(raw)

    else:
        raise HTTPException(
            status_code=415,
            detail="Unsupported content type. Use application/json or multipart/form-data with a .json file.",
        )

    return _run_pipeline(request.app.state, request_dict)

@app.post("/analyze-stream", tags=["pipeline"])
async def analyze_stream(request: Request, file: UploadFile | None = File(default=None)):
    """
    Analyze a single procurement request, streaming the execution steps back to the client.
    """
    content_type = request.headers.get("content-type", "")

    if file is not None:
        raw = await file.read()
        request_dict = _parse_json_bytes(raw)
    elif "application/json" in content_type:
        raw = await request.body()
        request_dict = _parse_json_bytes(raw)
    else:
        raise HTTPException(
            status_code=415,
            detail="Unsupported content type. Use application/json or multipart/form-data with a .json file.",
        )

    async def event_generator():
        try:
            for step in request.app.state.pipeline.run_stream(request_dict):
                yield f"data: {json.dumps(step)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
