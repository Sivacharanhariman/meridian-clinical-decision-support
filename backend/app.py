"""Local synthetic app factory and production-shaped dependency boundaries."""
import json
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from backend.api.routes import router
from backend.audit.diagnostics import RestrictedDiagnostics
from backend.audit.metrics import Metrics
from backend.auth.service import AuthService
from backend.config import Settings
from backend.domain.contracts import ApiError
from backend.errors import ApiFailure
from backend.models.providers import DeterministicProvider, OpenAIProvider
from backend.orchestration.workflow import Workflow
from backend.persistence.repository import Repository
from backend.rag.retriever import Retriever
from backend.service import Service


class RequestContextMiddleware:
    """Pure ASGI header middleware preserves the nonstreaming response body."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        correlation_id = f"episode-{uuid4().hex}"
        scope.setdefault("state", {})["correlation_id"] = correlation_id
        async def with_headers(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": list(message.get("headers", [])) + [
                    (b"x-correlation-id", correlation_id.encode()),
                    (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]}
            await send(message)
        await self.app(scope, receive, with_headers)


def create_app(settings=None):
    settings = settings or Settings()
    app = FastAPI(title="Meridian Patient Navigation & Triage Copilot", version="1.0.0", description="Synthetic demonstration only. Not a medical device or real clinical guidance.")
    repository = Repository(settings.database_path)
    fixtures = json.loads((Path(__file__).parent / "fixtures/cases.json").read_text())
    auth = AuthService(repository, fixtures["actors"], settings)
    retriever = Retriever()
    provider = DeterministicProvider() if settings.provider_mode == "deterministic" else OpenAIProvider(settings)
    diagnostics = RestrictedDiagnostics(settings)
    metrics = Metrics()
    workflow = Workflow(retriever, provider, settings, diagnostics)
    service = Service(repository, auth, workflow, metrics, settings)
    for name, value in dict(settings=settings, repository=repository, auth=auth, retriever=retriever, provider=provider,
                            diagnostics=diagnostics, metrics=metrics, workflow=workflow, service=service).items():
        setattr(app.state, name, value)

    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(ApiFailure)
    async def api_failure(request: Request, exc: ApiFailure):
        body = ApiError(code=exc.code, message=exc.message, correlationId=request.state.correlation_id)
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

    @app.exception_handler(Exception)
    async def unexpected_failure(request: Request, exc: Exception):
        # Exception detail may contain clinical input. Never echo it to a user.
        return JSONResponse(status_code=503, content=ApiError(code="SYSTEM_UNAVAILABLE",
            message="System unavailable — manual clinical review required.",
            correlationId=getattr(request.state, "correlation_id", "unavailable")).model_dump())

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type"])
    app.include_router(router)
    return app


app = create_app()
