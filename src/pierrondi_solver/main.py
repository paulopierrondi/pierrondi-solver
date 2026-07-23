"""FastAPI app: POST /solve, GET /health, GET /metrics."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .chain import SolverChain, build_default_chain
from .config import load_config
from .models import SolveRequest, UnsolvedError


def create_app(chain: SolverChain | None = None) -> FastAPI:
    app = FastAPI(title="pierrondi-solver", version="0.1.0")
    app.state.chain = chain or build_default_chain(load_config())

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "providers": app.state.chain.config.chain()}

    @app.get("/metrics")
    def metrics(window_s: int = 86400) -> dict:
        return app.state.chain.telemetry.summary(since_s=window_s)

    @app.post("/solve")
    def solve(request: SolveRequest):
        result, error = app.state.chain.solve(request)
        if error is not None:
            return JSONResponse(status_code=422, content=error.model_dump())
        return result.model_dump()

    return app


app = create_app()
