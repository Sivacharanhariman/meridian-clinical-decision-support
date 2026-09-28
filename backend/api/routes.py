"""Frozen HTTP surface; all application writes pass through Service."""
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from backend.domain.contracts import *
from backend.errors import ApiFailure

router = APIRouter(prefix="/api", responses={400:{"model":ApiError},401:{"model":ApiError},403:{"model":ApiError},404:{"model":ApiError},409:{"model":ApiError},503:{"model":ApiError}})
bearer = HTTPBearer(auto_error=False)

def actor(request, token):
    if token is None:
        raise ApiFailure(401, "AUTHENTICATION_REQUIRED", "A valid synthetic demo identity is required.")
    return request.app.state.auth.authenticate(token.credentials)

def correlation(request):
    return request.state.correlation_id

@router.get("/health", response_model=HealthResponse, operation_id="getHealth")
def health(request: Request):
    return HealthResponse(status="ok", app="Meridian Patient Navigation & Triage Copilot", mode=request.app.state.settings.provider_mode, syntheticOnly=True)

@router.get("/demo", response_model=DemoCatalog, operation_id="getDemoCatalog")
def demo_catalog(request: Request):
    return request.app.state.service.catalog()

@router.post("/auth/demo", response_model=DemoLoginResponse, operation_id="demoLogin")
def demo_login(body: DemoLoginRequest, request: Request):
    return request.app.state.auth.login(body.actorId)

@router.get("/sessions", response_model=list[SessionSummary], operation_id="listSessions")
def list_sessions(request: Request, token: HTTPAuthorizationCredentials = Depends(bearer)):
    return request.app.state.service.list(actor(request, token))

@router.post("/sessions", response_model=SessionView, operation_id="createSession")
def create_session(body: SessionCreateRequest, request: Request, token: HTTPAuthorizationCredentials = Depends(bearer)):
    return request.app.state.service.create(actor(request, token), body, correlation(request))

@router.get("/sessions/{sessionId}", response_model=SessionView, operation_id="getSession")
def get_session(sessionId: str, request: Request, token: HTTPAuthorizationCredentials = Depends(bearer)):
    return request.app.state.service.view(actor(request, token), sessionId, correlation(request))

@router.post("/triage", response_model=TriageResponse, operation_id="runTriage")
def triage(body: TriageRequest, request: Request, token: HTTPAuthorizationCredentials = Depends(bearer)):
    return request.app.state.service.triage(actor(request, token), body, correlation(request))

@router.post("/sessions/{sessionId}/actions", response_model=SessionView, operation_id="recordNurseAction")
def record_action(sessionId: str, body: NurseActionRequest, request: Request, token: HTTPAuthorizationCredentials = Depends(bearer)):
    return request.app.state.service.action(actor(request, token), sessionId, body, correlation(request))

@router.get("/sessions/{sessionId}/audit", response_model=AuditResponse, operation_id="getAudit")
def audit(sessionId: str, request: Request, token: HTTPAuthorizationCredentials = Depends(bearer)):
    return request.app.state.service.audit(actor(request, token), sessionId, correlation(request))

@router.get("/metrics", response_model=MetricsResponse, operation_id="getMetrics")
def metrics(request: Request, token: HTTPAuthorizationCredentials = Depends(bearer)):
    actor(request, token)
    return request.app.state.metrics.snapshot()

@router.post("/metrics/render", response_model=MessageResponse, operation_id="recordSafeRender")
def render_metric(body: RenderMetricRequest, request: Request, token: HTTPAuthorizationCredentials = Depends(bearer)):
    request.app.state.service.render(actor(request, token), body, correlation(request))
    return MessageResponse(message="Committed response render recorded.")
