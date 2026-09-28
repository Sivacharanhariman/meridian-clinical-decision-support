"""Bounded five-node workflow; no agent loop, streaming, or model retries."""
from datetime import datetime, timezone
from time import monotonic, perf_counter
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from backend.domain.contracts import (
    Disposition, FactGraph, ModelSynthesis, ReadinessState, RetrievalManifest,
    SafetyAssessment, StageTimings, SystemRecommendation, TriageResponse,
)
from backend.models.providers import ProviderFailure, SynthesisContext
from backend.policy.engine import Extraction, PolicyEngine


class WorkState(TypedDict, total=False):
    request: Any
    scenario: str
    deadline: float
    timings: dict
    extracted: Extraction
    manifest: RetrievalManifest
    plan: Any
    raw: Any
    errors: list[str]
    synthesis: ModelSynthesis | None


class Workflow:
    def __init__(self, retriever, provider, settings, diagnostics):
        self.retriever, self.provider, self.settings, self.diagnostics = retriever, provider, settings, diagnostics
        self.policy = PolicyEngine()
        builder = StateGraph(WorkState)
        for name, fn in [("extract", self.extract), ("retrieve", self.retrieve), ("plan", self.plan), ("synthesize", self.synthesize), ("validate", self.validate)]:
            builder.add_node(name, fn)
        builder.add_edge(START, "extract")
        builder.add_edge("extract", "retrieve")
        builder.add_edge("retrieve", "plan")
        builder.add_edge("plan", "synthesize")
        builder.add_edge("synthesize", "validate")
        builder.add_edge("validate", END)
        self.graph = builder.compile()

    def extract(self, state):
        start = perf_counter()
        extracted = self.policy.extract(state["request"])
        return {"extracted": extracted, "timings": {**state["timings"], "extractionMs": (perf_counter() - start) * 1000}}

    def retrieve(self, state):
        start = perf_counter()
        request = state["request"]
        try:
            manifest = self.retriever.retrieve(request, scenario_mode=state["scenario"])
        except Exception:
            # A software or store failure is a visible fail-closed state, never a
            # substitute for verified evidence. Raw exception text is not logged.
            manifest = RetrievalManifest(manifestId=f"manifest-failed-{uuid4().hex}", sessionId=request.sessionId,
                turnId=request.turnId, stateVersion=request.baseStateVersion + 1,
                evidence=[], integrityViolations=["RETRIEVAL_EXECUTION_FAILED"])
        return {"manifest": manifest, "timings": {**state["timings"], "retrievalMs": (perf_counter() - start) * 1000}}

    def plan(self, state):
        start = perf_counter()
        plan = self.policy.plan(state["request"], state["extracted"], state["manifest"])
        return {"plan": plan, "timings": {**state["timings"], "policyValidationMs": (perf_counter() - start) * 1000}}

    def synthesize(self, state):
        if not state["plan"].can_synthesize:
            return {"raw": None}
        start = perf_counter()
        errors, raw = [], None
        try:
            if monotonic() >= state["deadline"]:
                raise ProviderFailure("DEADLINE_EXCEEDED")
            raw = self.provider.synthesize(SynthesisContext(state["request"], state["extracted"].facts,
                state["manifest"], state["plan"], state["scenario"], state["deadline"]))
            if monotonic() >= state["deadline"]:
                raise ProviderFailure("DEADLINE_EXCEEDED")
        except ProviderFailure as exc:
            errors.append(exc.code)
        except TimeoutError:
            errors.append("PROVIDER_TIMEOUT")
        except Exception:
            errors.append("SYNTHESIS_EXECUTION_FAILED")
        return {"raw": raw, "errors": errors, "timings": {**state["timings"], "synthesisMs": (perf_counter() - start) * 1000}}

    def validate(self, state):
        start = perf_counter()
        errors = list(state["errors"])
        synthesis = None
        if state["plan"].can_synthesize and not errors:
            try:
                raw = state["raw"]
                synthesis = ModelSynthesis.model_validate_json(raw) if isinstance(raw, str) else ModelSynthesis.model_validate(raw)
                errors.extend(self.policy.validate(synthesis, state["plan"], state["extracted"], state["manifest"]))
            except (ValidationError, TypeError, ValueError):
                errors.append("MODEL_SCHEMA_INVALID")
        if errors:
            synthesis = None
        return {"synthesis": synthesis, "errors": errors, "timings": {**state["timings"], "policyValidationMs": state["timings"]["policyValidationMs"] + (perf_counter() - start) * 1000}}

    def run(self, request, scenario, authorization_ms, started, correlation_id):
        timings = dict(extractionMs=0., retrievalMs=0., synthesisMs=0., policyValidationMs=0.,
                       authorizationMs=authorization_ms, databaseCommitMs=0., totalMs=0.)
        state = self.graph.invoke({"request": request, "scenario": scenario,
            "deadline": monotonic() + self.settings.request_deadline_ms / 1000,
            "timings": timings, "errors": [], "synthesis": None}, config={"recursion_limit": 8})
        extracted, plan, synthesis = state["extracted"], state["plan"], state["synthesis"]
        manual = synthesis is None
        disposition = Disposition.MANUAL_ESCALATION if manual else synthesis.recommendedDisposition
        readiness = plan.readiness
        if state["errors"]:
            readiness = ReadinessState.SAFETY_LOCKED if extracted.safety.safetyLocked else ReadinessState.UNGROUNDED
        rationale = [] if manual else synthesis.rationale
        alerts = []
        if state["errors"]:
            alerts.append("AI synthesis unavailable — manual clinical review required.")
        if not extracted.safety.supportedPopulation:
            alerts.append("Unsupported or unconfirmed population — manual clinical review required.")
        if extracted.safety.safetyLocked:
            alerts.append("A confirmed synthetic safety rule blocks lower-acuity automation.")
        if not state["manifest"].evidence:
            alerts.append("No eligible approved evidence — manual clinical review required.")
        if manual and not alerts:
            alerts.append("Context requires clarification or manual clinical review.")
        codes = list(dict.fromkeys(plan.codes + state["errors"] + (["VALIDATED_SYNTHESIS"] if synthesis else ["MANUAL_TRIAGE_REQUIRED"])))
        version = request.baseStateVersion + 1
        recommendation = SystemRecommendation(recommendationId=f"recommendation-{uuid4().hex}",
            recommendedDisposition=disposition, readinessState=readiness, safetyLocked=extracted.safety.safetyLocked,
            validatedRationale=rationale, computedStateVersion=version, timestamp=datetime.now(timezone.utc), supersedesRecommendationId=None)
        state["timings"]["totalMs"] = (perf_counter() - started) * 1000
        response = TriageResponse(responseId=f"response-{uuid4().hex}", sessionId=request.sessionId,
            turnId=request.turnId, stateVersion=version, readinessState=readiness,
            recommendation=recommendation, rationale=rationale, evidence=state["manifest"].evidence,
            missingInformation=extracted.missing, systemAlerts=alerts, factGraph=extracted.facts,
            safety=extracted.safety, retrievalManifest=state["manifest"],
            timings=StageTimings(**state["timings"]), mode="MANUAL" if manual else ("DETERMINISTIC" if self.settings.provider_mode == "deterministic" else "PROVIDER"),
            validationCodes=codes)
        self.diagnostics.write(correlation_id, {"transcript": request.symptomDescription, "modelOutput": state["raw"].model_dump(mode="json") if hasattr(state["raw"], "model_dump") else state["raw"]})
        return response

    def failure_response(self, request, started, authorization_ms):
        """No usable safety state: only a visibly ungrounded manual response."""
        version = request.baseStateVersion + 1
        safety = SafetyAssessment(supportedPopulation=False, contextCertain=False, safetyLocked=False,
            requiredDisposition=None, matchedRuleIds=[], events=[], validationCodes=["SAFETY_STATE_UNAVAILABLE"])
        manifest = RetrievalManifest(manifestId=f"manifest-failed-{uuid4().hex}", sessionId=request.sessionId,
            turnId=request.turnId, stateVersion=version, evidence=[], integrityViolations=["WORKFLOW_EXECUTION_FAILED"])
        rec = SystemRecommendation(recommendationId=f"recommendation-{uuid4().hex}", recommendedDisposition=Disposition.MANUAL_ESCALATION,
            readinessState=ReadinessState.UNGROUNDED, safetyLocked=False, validatedRationale=[], computedStateVersion=version,
            timestamp=datetime.now(timezone.utc), supersedesRecommendationId=None)
        return TriageResponse(responseId=f"response-{uuid4().hex}", sessionId=request.sessionId, turnId=request.turnId,
            stateVersion=version, readinessState=ReadinessState.UNGROUNDED, recommendation=rec, rationale=[], evidence=[],
            missingInformation=["Manual assessment required: safety state could not be validated."],
            systemAlerts=["AI synthesis unavailable — manual clinical review required."], factGraph=FactGraph(facts=[]), safety=safety,
            retrievalManifest=manifest, timings=StageTimings(extractionMs=0, retrievalMs=0, synthesisMs=0, policyValidationMs=0,
                authorizationMs=authorization_ms, databaseCommitMs=0, totalMs=(perf_counter()-started)*1000),
            mode="MANUAL", validationCodes=["SAFETY_STATE_UNAVAILABLE", "WORKFLOW_EXECUTION_FAILED", "MANUAL_TRIAGE_REQUIRED"])
