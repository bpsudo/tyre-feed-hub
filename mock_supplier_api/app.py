"""Fake API of the supplier Reifen Handel. It serves the JSON files written by the generator.

Run it with: uvicorn mock_supplier_api.app:app --port 8001
"""
import json
import os
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "generated" / "reif"
DEFAULT_API_KEY = "demo-key"


def export_path(data_dir, export_date):
    return data_dir / f"offers_{export_date:%Y%m%d}.json"


def create_app(data_dir=DATA_DIR, api_key=None, rate_limit_every=5, retry_after=1):
    """Every rate_limit_every-th request is refused with HTTP 429, to test the client."""
    api_key = api_key or os.environ.get("REIF_API_KEY", DEFAULT_API_KEY)
    app = FastAPI(title="Reifen Handel API (test)")
    app.state.requests = 0
    app.state.refused = 0

    def check_request(x_api_key):
        if x_api_key != api_key:
            raise HTTPException(status_code=401, detail="invalid API key")
        app.state.requests += 1
        if rate_limit_every and app.state.requests % rate_limit_every == 0:
            app.state.refused += 1
            raise HTTPException(
                status_code=429, detail="too many requests", headers={"Retry-After": str(retry_after)}
            )

    @app.get("/api/v1/exports")
    def list_exports(x_api_key: str | None = Header(None)):
        check_request(x_api_key)
        dates = []
        for path in sorted(Path(data_dir).glob("offers_*.json")):
            dates.append(json.loads(path.read_text(encoding="utf-8"))["datum"])
        return {"exports": dates}

    @app.get("/api/v1/exports/{export_date}/artikel")
    def list_items(
        export_date: date,
        page: int = Query(1, ge=1),
        per_page: int = Query(100, ge=1, le=200),
        x_api_key: str | None = Header(None),
    ):
        check_request(x_api_key)
        path = export_path(Path(data_dir), export_date)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"no export for {export_date}")
        items = json.loads(path.read_text(encoding="utf-8"))["artikel"]
        start = (page - 1) * per_page
        return {
            "datum": export_date.isoformat(),
            "page": page,
            "per_page": per_page,
            "total": len(items),
            "artikel": items[start:start + per_page],
        }

    return app


app = create_app()
