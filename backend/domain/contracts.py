"""The authoritative API and domain schemas. Generate clients; never copy DTOs.

Clinical fields are required. Defaults exist only for transport-optional notes
and vitals, never for readiness, disposition, safety, or model claims.
"""
from datetime import datetime, date
from enum import StrEnum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Disposition(StrEnum):
    EMERGENCY_911 = "EMERGENCY_911"
    EMERGENCY_DEPARTMENT = "EMERGENCY_DEPARTMENT"
    CLINICIAN_WITHIN_24H = "CLINICIAN_WITHIN_24H"
    HOME_MONITORING = "HOME_MONITORING"
    MANUAL_ESCALATION = "MANUAL_ESCALATION"


class ProcessingStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ReadinessState(StrEnum):
    READY = "READY"
    INCOMPLETE = "INCOMPLETE"
    UNGROUNDED = "UNGROUNDED"
    SAFETY_LOCKED = "SAFETY_LOCKED"


class AssertionStatus(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN_NOT_STATED = "UNKNOWN_NOT_STATED"


class BiologicalSex(StrEnum):
    FEMALE = "FEMALE"
    MALE = "MALE"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class PatientDemographics(Contract):
    ageInMonths: Annotated[int, Field(strict=True, ge=0, le=1560)]
    isPregnant: Annotated[bool, Field(strict=True)] | None
    biologicalSex: BiologicalSex


class VitalSigns(Contract):
    heartRate: Annotated[float, Field(gt=0, le=350, allow_inf_nan=False)] | None = None
    respiratoryRate: Annotated[float, Field(gt=0, le=120, allow_inf_nan=False)] | None = None
    oxygenSaturation: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] | None = None
    temperatureC: Annotated[float, Field(ge=25, le=45, allow_inf_nan=False)] | None = None


Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")]


class TriageRequest(Contract):
    sessionId: Identifier
    turnId: Identifier
    baseStateVersion: Annotated[int, Field(strict=True, ge=0)]
    patientId: Identifier
    symptomDescription: Annotated[str, Field(min_length=1, max_length=12000)]
    patientDemographics: PatientDemographics
    vitalSigns: VitalSigns | None = None
    nurseNotes: Annotated[str, Field(max_length=6000)] | None = None


class TriageState(Contract):
    sessionId: str
    processingStatus: ProcessingStatus
    readinessState: ReadinessState
    currentStateVersion: int
    activeTurnId: str | None


class Fact(Contract):
    factId: str
    factType: str
    normalizedValue: str
    assertionStatus: AssertionStatus
    source: str


class FactGraph(Contract):
    facts: list[Fact]


class EventCategory(StrEnum):
    POSSIBLE_STROKE = "POSSIBLE_STROKE"
    SEVERE_RESPIRATORY_DISTRESS = "SEVERE_RESPIRATORY_DISTRESS"
    SEVERE_CHEST_PAIN = "SEVERE_CHEST_PAIN"
    ANAPHYLAXIS = "ANAPHYLAXIS"
    UNCONTROLLED_BLEEDING = "UNCONTROLLED_BLEEDING"
    ALTERED_CONSCIOUSNESS = "ALTERED_CONSCIOUSNESS"
    IMMEDIATE_SELF_HARM = "IMMEDIATE_SELF_HARM"
    CHEST_PAIN = "CHEST_PAIN"


class ContextEvent(Contract):
    eventId: str
    category: EventCategory
    assertion: Literal["AFFIRMED", "NEGATED", "UNCERTAIN"]
    temporality: Literal["CURRENT", "HISTORICAL", "UNCERTAIN"]
    subject: Literal["PATIENT", "FAMILY_OTHER", "UNCERTAIN"]
    sourceText: str
    factId: str


class SafetyAssessment(Contract):
    supportedPopulation: bool
    contextCertain: bool
    safetyLocked: bool
    requiredDisposition: Disposition | None
    matchedRuleIds: list[str]
    events: list[ContextEvent]
    validationCodes: list[str]


class EvidenceChunk(Contract):
    chunkId: str
    guidelineId: str
    guidelineVersion: str
    chunkIndex: int
    text: str
    sourceHash: str
    retrievalScore: float


class GuidelineRegistryEntry(Contract):
    chunkId: str
    guidelineId: str
    guidelineVersion: str
    chunkIndex: int
    approvalStatus: Literal["APPROVED", "REJECTED", "RETIRED"]
    population: Literal["ADULT", "PEDIATRIC"]
    minAgeMonths: int
    maxAgeMonths: int
    pregnancyApplicability: Literal["NON_PREGNANT_ONLY", "ANY"]
    effectiveDate: date
    expiryDate: date | None
    chunkHash: str
    title: str


class ManifestEvidence(Contract):
    alias: str
    chunk: EvidenceChunk


class RetrievalManifest(Contract):
    manifestId: str
    sessionId: str
    turnId: str
    stateVersion: int
    evidence: list[ManifestEvidence]
    integrityViolations: list[str]


class RationaleClaim(Contract):
    claimId: str
    claim: Annotated[str, Field(min_length=1, max_length=1500)]
    factRefs: Annotated[list[str], Field(min_length=1)]
    evidenceRefs: Annotated[list[str], Field(min_length=1)]


class ModelSynthesis(Contract):
    recommendedDisposition: Disposition
    rationale: Annotated[list[RationaleClaim], Field(min_length=1)]


class SystemRecommendation(Contract):
    recommendationId: str
    recommendedDisposition: Disposition
    readinessState: ReadinessState
    safetyLocked: bool
    validatedRationale: list[RationaleClaim]
    computedStateVersion: int
    timestamp: datetime
    supersedesRecommendationId: str | None


class StageTimings(Contract):
    extractionMs: float
    retrievalMs: float
    synthesisMs: float
    policyValidationMs: float
    authorizationMs: float
    databaseCommitMs: float
    totalMs: float


class TriageResponse(Contract):
    responseId: str
    sessionId: str
    turnId: str
    stateVersion: int
    readinessState: ReadinessState
    recommendation: SystemRecommendation
    rationale: list[RationaleClaim]
    evidence: list[ManifestEvidence]
    missingInformation: list[str]
    systemAlerts: list[str]
    factGraph: FactGraph
    safety: SafetyAssessment
    retrievalManifest: RetrievalManifest
    timings: StageTimings
    mode: Literal["DETERMINISTIC", "PROVIDER", "MANUAL"]
    validationCodes: list[str]


class ActionType(StrEnum):
    ACCEPT_RECOMMENDATION = "ACCEPT_RECOMMENDATION"
    CLINICIAN_OVERRIDE = "CLINICIAN_OVERRIDE"
    DOCUMENT_PATIENT_REFUSAL = "DOCUMENT_PATIENT_REFUSAL"
    ESCALATE_TO_CLINICIAN = "ESCALATE_TO_CLINICIAN"


class PatientResponseType(StrEnum):
    CONSENTED = "CONSENTED"
    REFUSED_RECOMMENDED_CARE = "REFUSED_RECOMMENDED_CARE"
    UNABLE_TO_CONSENT = "UNABLE_TO_CONSENT"


class PatientResponse(Contract):
    responseId: str
    responseType: PatientResponseType
    statedPreference: str
    timestamp: datetime


class NurseAction(Contract):
    actionId: str
    targetRecommendationId: str
    actorId: str
    actionType: ActionType
    rationale: str
    timestamp: datetime
    overrideDisposition: Disposition | None
    patientResponse: PatientResponse | None


class NurseActionRequest(Contract):
    actionId: Identifier
    targetRecommendationId: Identifier
    baseStateVersion: Annotated[int, Field(strict=True, ge=0)]
    actionType: ActionType
    rationale: Annotated[str, Field(min_length=3, max_length=3000)]
    overrideDisposition: Disposition | None = None
    statedPreference: Annotated[str, Field(max_length=2000)] | None = None


class Actor(Contract):
    actorId: str
    displayName: str
    tenantId: str
    role: Literal["NURSE", "CLINICIAN"]


class PatientContext(Contract):
    patientId: str
    displayName: str
    demographics: PatientDemographics
    history: list[str]
    medications: list[str]
    allergies: list[str]
    synthetic: Literal[True]


class SessionPermissions(Contract):
    canView: bool
    canAccept: bool
    canDocumentRefusal: bool
    canEscalate: bool
    canOverride: bool
    authorizationServiceAvailable: bool


class SessionView(Contract):
    sessionId: str
    caseId: str
    careTeamId: str
    patient: PatientContext
    originalTranscript: str
    nurseNotes: str
    state: TriageState
    latestResponse: TriageResponse | None
    recommendations: list[SystemRecommendation]
    actions: list[NurseAction]
    patientResponses: list[PatientResponse]
    recommendationStatus: Literal["AWAITING_REVIEW", "ACCEPTED", "DECLINED_BY_PATIENT", "ESCALATED", "OVERRIDDEN"]
    patientOutcome: Literal["UNRECORDED", "CARE_ACCEPTED", "REMAINS_HOME", "CLINICIAN_REVIEW"]
    permissions: SessionPermissions


class SessionSummary(Contract):
    sessionId: str
    patientName: str
    caseId: str
    stateVersion: int
    readinessState: ReadinessState


class SessionCreateRequest(Contract):
    caseId: Identifier


class DemoCase(Contract):
    caseId: str
    label: str
    description: str
    category: Literal["NORMAL", "SAFETY", "FAILURE", "CONTEXT", "POPULATION", "SECURITY"]


class DemoCatalog(Contract):
    cases: list[DemoCase]
    actors: list[Actor]
    disclaimer: str
    defaultCaseId: str


class DemoLoginRequest(Contract):
    actorId: Identifier


class DemoLoginResponse(Contract):
    accessToken: str
    tokenType: Literal["bearer"]
    actor: Actor
    expiresAt: datetime


class AuditEvent(Contract):
    eventId: str
    timestamp: datetime
    eventType: str
    sessionId: str
    turnId: str | None
    stateVersion: int
    correlationId: str
    actorId: str
    resource: str
    action: str
    outcome: str
    policyVersion: str
    authoritySource: str
    rule: str
    modelIdentifier: str | None
    promptHash: str | None
    factIds: list[str]
    manifestId: str | None
    sourceHashes: list[str]
    validationCodes: list[str]
    recommendationId: str | None
    nurseActionId: str | None
    patientResponseId: str | None


class AuditResponse(Contract):
    sessionId: str
    events: list[AuditEvent]


class MetricSummary(Contract):
    samples: int
    p50Ms: float
    p95Ms: float
    p99Ms: float


class MetricsResponse(Contract):
    requestCount: int
    stages: dict[str, MetricSummary]
    provider429Rate: float
    deadlineExceededRate: float
    degradedModeRate: float
    timeToSafeRender: MetricSummary
    targetP95Ms: int
    targetIsGuarantee: Literal[False]


class RenderMetricRequest(Contract):
    sessionId: Identifier
    responseId: Identifier
    durationMs: Annotated[float, Field(ge=0, le=300000, allow_inf_nan=False)]


class HealthResponse(Contract):
    status: Literal["ok"]
    app: str
    mode: str
    syntheticOnly: Literal[True]


class ApiError(Contract):
    code: str
    message: str
    correlationId: str


class MessageResponse(Contract):
    message: str
