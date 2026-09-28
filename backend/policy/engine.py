"""Small deterministic *synthetic* policy, separate from prompts and providers.

This is intentionally conservative phrase/context recognition, not a clinical
NLP system. Unknown facts remain unknown. All dispositions come from the frozen
policy fixture; no vital-sign threshold or additional escalation rule is added.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import re

from backend.domain.contracts import (
    AssertionStatus, ContextEvent, Disposition, Fact, FactGraph,
    ModelSynthesis, RationaleClaim, ReadinessState, RetrievalManifest,
    SafetyAssessment, TriageRequest,
)


@dataclass
class Extraction:
    facts: FactGraph
    safety: SafetyAssessment
    missing: list[str]
    exact_home: bool
    broad_uncertainty: bool


@dataclass
class PolicyPlan:
    disposition: Disposition
    readiness: ReadinessState
    catalogue: list[RationaleClaim]
    codes: list[str]
    can_synthesize: bool


class PolicyEngine:
    def __init__(self, policy_path: Path | None = None):
        self.policy = json.loads((policy_path or Path(__file__).resolve().parents[1] / "fixtures" / "policy.json").read_text())

    @staticmethod
    def _context(clause: str, start: int, end: int):
        lower = clause.lower()
        prefix = lower[:start]
        suffix = lower[end:]
        # An explicit other-person subject must never become a patient event.
        subjects = list(re.finditer(r"\b(i|patient|father|mother|parent|brother|sister|husband|wife|son|daughter|grandmother|grandfather|friend|uncle|aunt|family|someone else)\b", prefix))
        family = bool(subjects and subjects[-1].group() not in {"i", "patient"})
        subject = "FAMILY_OTHER" if family else "PATIENT"
        if re.search(r"\b(he|she|they|someone)\b", prefix) and not family and not re.search(r"\b(patient|i|my|me)\b", prefix):
            subject = "UNCERTAIN"
        uncertain = bool(re.search(r"\b(maybe|possibly|possible|unsure|uncertain|might|perhaps|not sure|cannot tell|can't tell|could be|rule out|question of)\b", lower))
        if "?" in clause:
            uncertain = True
        negated = bool(re.search(r"\b(no|not|denies|denied|without|never|don't have|do not have|does not have|doesn't have)\b", prefix))
        # Negation in 'not sure' indicates uncertainty, not symptom absence.
        assertion = "UNCERTAIN" if uncertain else ("NEGATED" if negated else "AFFIRMED")
        historical = bool(re.search(r"\b(history of|historical|previously|last month|last year|last week|years ago|months ago|yesterday|used to|had|resolved)\b", lower))
        current = bool(re.search(r"\b(now|right now|today|currently|this morning|ongoing|still|have|has|is)\b", lower))
        if historical and current and not re.search(r"\b(no longer|resolved)\b", lower):
            temporality = "UNCERTAIN"
        elif historical:
            temporality = "HISTORICAL"
        else:
            temporality = "CURRENT"
        if re.search(r"\b(not sure when|unclear when|unknown timing)\b", lower):
            temporality = "UNCERTAIN"
        if re.search(r"\b(no longer|resolved)\b", suffix):
            temporality = "HISTORICAL"
        return assertion, temporality, subject

    def extract(self, request: TriageRequest) -> Extraction:
        d = request.patientDemographics
        supported = d.ageInMonths >= self.policy["adultMinMonths"] and d.isPregnant is False
        facts = [
            Fact(factId="F-age", factType="AGE_MONTHS", normalizedValue=str(d.ageInMonths), assertionStatus=AssertionStatus.PRESENT, source="verified patient context"),
            Fact(factId="F-pregnancy", factType="PREGNANCY", normalizedValue="unknown" if d.isPregnant is None else str(d.isPregnant).lower(),
                 assertionStatus=AssertionStatus.UNKNOWN_NOT_STATED if d.isPregnant is None else (AssertionStatus.PRESENT if d.isPregnant else AssertionStatus.ABSENT), source="verified patient context"),
        ]
        # Clause boundaries stop negation/history from bleeding into a new event.
        # Questions retain the marker so an interrogative never becomes affirmed.
        segments = []
        for source, text in (("symptomDescription", request.symptomDescription), ("nurseNotes", request.nurseNotes or "")):
            for clause in re.split(r"(?<=[.!?;])\s+|[\n;]|\s+but\s+|\s+however\s+|,?\s+and\s+(?=(?:i|the patient|patient|he|she|they)\b)", text, flags=re.I):
                if clause.strip():
                    segments.append((source, clause.strip()))
        events = []
        matched_rules = []
        required = None
        priority = {Disposition.EMERGENCY_911: 0, Disposition.EMERGENCY_DEPARTMENT: 1}
        for rule in self.policy["rules"]:
            for source, clause in segments:
                for pattern in rule["patterns"]:
                    for match in re.finditer(r"\b" + re.escape(pattern) + r"\b", clause, flags=re.I):
                        assertion, temporality, subject = self._context(clause, match.start(), match.end())
                        fact_id = f"F-event-{len(events) + 1}"
                        events.append(ContextEvent(eventId=f"event-{len(events) + 1}", category=rule["category"],
                                                   assertion=assertion, temporality=temporality, subject=subject,
                                                   sourceText=clause, factId=fact_id))
                        status = {"AFFIRMED": AssertionStatus.PRESENT, "NEGATED": AssertionStatus.ABSENT,
                                  "UNCERTAIN": AssertionStatus.UNKNOWN_NOT_STATED}[assertion]
                        facts.append(Fact(factId=fact_id, factType=f"CONTEXT_EVENT:{rule['category']}",
                                          normalizedValue=f"{subject}; {temporality}; {assertion}; {pattern}",
                                          assertionStatus=status, source=source))
                        if (assertion, temporality, subject) == ("AFFIRMED", "CURRENT", "PATIENT"):
                            if rule["ruleId"] not in matched_rules:
                                matched_rules.append(rule["ruleId"])
                            disposition = Disposition(rule["disposition"])
                            if required is None or priority[disposition] < priority[required]:
                                required = disposition
        context_certain = all("UNCERTAIN" not in (e.assertion, e.temporality, e.subject) for e in events)
        # Contradictory current statements are uncertain, not resolved by recency.
        for rule in self.policy["rules"]:
            current_events = [e for e in events if e.category.value == rule["category"] and e.temporality == "CURRENT" and e.subject == "PATIENT"]
            assertions = {e.assertion for e in current_events}
            if {"AFFIRMED", "NEGATED"} <= assertions:
                context_certain = False
            if "AFFIRMED" in assertions:
                status = AssertionStatus.PRESENT
            elif "NEGATED" in assertions and "UNCERTAIN" not in assertions:
                status = AssertionStatus.ABSENT
            else:
                status = AssertionStatus.UNKNOWN_NOT_STATED
            facts.append(Fact(factId=f"F-safety-{rule['category'].lower()}", factType=f"CURRENT_SAFETY:{rule['category']}",
                              normalizedValue=rule["category"], assertionStatus=status,
                              source="explicit context events" if current_events else "not stated"))
        # A direct negation of chest pain also negates the more specific severe
        # chest-pain category; it never negates unrelated safety categories.
        by_id = {f.factId: f for f in facts}
        if by_id["F-safety-chest_pain"].assertionStatus == AssertionStatus.ABSENT and by_id["F-safety-severe_chest_pain"].assertionStatus == AssertionStatus.UNKNOWN_NOT_STATED:
            by_id["F-safety-severe_chest_pain"].assertionStatus = AssertionStatus.ABSENT
            by_id["F-safety-severe_chest_pain"].source = "explicit absence of chest pain"
        mild = AssertionStatus.UNKNOWN_NOT_STATED
        for source, clause in segments:
            match = re.search(re.escape(self.policy["normalRule"]["pattern"]), clause, re.I)
            if match:
                a, t, s = self._context(clause, match.start(), match.end())
                if (a, t, s) == ("AFFIRMED", "CURRENT", "PATIENT"):
                    mild = AssertionStatus.PRESENT
                elif a == "NEGATED" and t == "CURRENT" and s == "PATIENT":
                    mild = AssertionStatus.ABSENT
                else:
                    context_certain = False
        facts.append(Fact(factId="F-mild-headache", factType="MILD_HEADACHE", normalizedValue="mild headache", assertionStatus=mild, source="symptom assessment" if mild != AssertionStatus.UNKNOWN_NOT_STATED else "not stated"))
        combined = request.symptomDescription + "\n" + (request.nurseNotes or "")
        cardiac = AssertionStatus.UNKNOWN_NOT_STATED
        if re.search(r"\b(no cardiac history|denies cardiac history)\b", combined, re.I):
            cardiac = AssertionStatus.ABSENT
        if re.search(r"\b(i have (?:a )?cardiac history|patient has (?:a )?cardiac history)\b", combined, re.I):
            cardiac = AssertionStatus.PRESENT if cardiac != AssertionStatus.ABSENT else AssertionStatus.UNKNOWN_NOT_STATED
        facts.append(Fact(factId="F-cardiac-history", factType="CARDIAC_HISTORY", normalizedValue="cardiac history", assertionStatus=cardiac,
                          source="explicit symptom assessment" if cardiac != AssertionStatus.UNKNOWN_NOT_STATED else "not stated"))
        known_onset = bool(re.search(r"\b(for one day|started this morning|began this morning|started today)\b", combined, re.I))
        facts.append(Fact(factId="F-onset", factType="SYMPTOM_ONSET", normalizedValue="explicitly stated" if known_onset else "unknown",
                          assertionStatus=AssertionStatus.PRESENT if known_onset else AssertionStatus.UNKNOWN_NOT_STATED, source="symptomDescription" if known_onset else "not stated"))
        exact_home = request.symptomDescription == self.policy["homeGate"]["requiredExactAssessment"]
        notes_supported = not (request.nurseNotes or "").strip() or request.nurseNotes in self.policy["homeGate"]["allowedNonclinicalNotes"]
        exact_home = exact_home and notes_supported
        facts.append(Fact(factId="F-complete-assessment", factType="CURATED_COMPLETE_ASSESSMENT", normalizedValue="exact assessment matched" if exact_home else "not established",
                          assertionStatus=AssertionStatus.PRESENT if exact_home else AssertionStatus.UNKNOWN_NOT_STATED, source="synthetic home policy exact assessment gate"))
        broad_uncertainty = bool(re.search(r"\b(maybe|possibly|unsure|uncertain|not sure|cannot tell|can't tell)\b", combined, re.I))
        missing = []
        if not known_onset:
            missing.append("Symptom onset and duration")
        if cardiac == AssertionStatus.UNKNOWN_NOT_STATED:
            missing.append("Patient cardiac history")
        unknown_categories = [f.normalizedValue.replace("_", " ").lower() for f in facts if f.factType.startswith("CURRENT_SAFETY:") and f.assertionStatus == AssertionStatus.UNKNOWN_NOT_STATED]
        if unknown_categories:
            missing.append("Explicit safety assessment: " + ", ".join(unknown_categories))
        if d.isPregnant is None:
            missing.append("Confirmed pregnancy status")
        if not context_certain:
            missing.append("Clarify symptom assertion, timing, and whose symptom is described")
        if request.vitalSigns and any(v is not None for v in request.vitalSigns.model_dump().values()):
            # No numeric clinical escalation thresholds exist in the fixtures.
            # Preserve observations and request human interpretation instead.
            context_certain = False
            missing.append("Clinician interpretation of supplied vital signs; numeric thresholds are outside the synthetic policy.")
            for key, value in request.vitalSigns.model_dump().items():
                if value is not None:
                    facts.append(Fact(factId=f"F-vital-{key}", factType=f"VITAL:{key}", normalizedValue=str(value),
                        assertionStatus=AssertionStatus.PRESENT, source="nurse-entered vital signs"))
        codes = []
        if not supported:
            codes.append("UNSUPPORTED_POPULATION" if d.isPregnant is not None else "PREGNANCY_STATUS_UNKNOWN")
        if not context_certain:
            codes.append("CONTEXT_UNCERTAIN")
        if matched_rules:
            codes.append("DETERMINISTIC_SAFETY_RULE_MATCHED")
        safety = SafetyAssessment(supportedPopulation=supported, contextCertain=context_certain,
                                  safetyLocked=bool(matched_rules), requiredDisposition=required,
                                  matchedRuleIds=matched_rules, events=events, validationCodes=codes)
        return Extraction(FactGraph(facts=facts), safety, missing, exact_home, broad_uncertainty)

    def plan(self, request: TriageRequest, extracted: Extraction, manifest: RetrievalManifest) -> PolicyPlan:
        safety = extracted.safety
        codes = list(safety.validationCodes)
        evidence_by_guideline = {e.chunk.guidelineId: e.alias for e in manifest.evidence}
        by_id = {f.factId: f for f in extracted.facts.facts}
        def manual(code: str, readiness=ReadinessState.INCOMPLETE):
            return PolicyPlan(Disposition.MANUAL_ESCALATION,
                              ReadinessState.SAFETY_LOCKED if safety.safetyLocked and readiness != ReadinessState.UNGROUNDED else readiness, [],
                              list(dict.fromkeys(codes + [code])), False)
        if (manifest.sessionId, manifest.turnId, manifest.stateVersion) != (request.sessionId, request.turnId, request.baseStateVersion + 1):
            return manual("MANIFEST_BINDING_INVALID", ReadinessState.UNGROUNDED)
        if not safety.supportedPopulation:
            return manual("UNSUPPORTED_POPULATION")
        if not safety.contextCertain:
            return manual("CONTEXT_UNCERTAIN")
        if not manifest.evidence:
            return manual("NO_ELIGIBLE_EVIDENCE", ReadinessState.UNGROUNDED)
        if manifest.integrityViolations:
            # Any observed integrity violation prevents lower-acuity automation.
            return manual("EVIDENCE_INTEGRITY_FAILURE", ReadinessState.UNGROUNDED)
        if safety.safetyLocked:
            claims = []
            for rule in self.policy["rules"]:
                if rule["ruleId"] not in safety.matchedRuleIds or rule["disposition"] != safety.requiredDisposition.value:
                    continue
                guideline_id = "DEMO-CURRENT-CHEST-PAIN" if rule["ruleId"] == "DEMO-CHEST-CURRENT" else rule["ruleId"]
                alias = evidence_by_guideline.get(guideline_id)
                if not alias:
                    continue
                supporting = [e.factId for e in safety.events if e.category.value == rule["category"] and (e.assertion, e.temporality, e.subject) == ("AFFIRMED", "CURRENT", "PATIENT")]
                claims.append(RationaleClaim(claimId=f"claim-{rule['ruleId'].lower()}",
                                             claim=f"The assessment explicitly describes a current patient event in the {rule['category'].replace('_', ' ').lower()} category. The synthetic {rule['ruleId']} fixture requires {rule['disposition']} and prevents lower-acuity automation.",
                                             factRefs=supporting, evidenceRefs=[alias]))
            if not claims:
                return manual("SAFETY_EVIDENCE_MISSING", ReadinessState.UNGROUNDED)
            return PolicyPlan(safety.requiredDisposition, ReadinessState.SAFETY_LOCKED, claims, codes + ["SAFETY_GATE_PASSED"], True)
        home_clear = (extracted.exact_home and not extracted.broad_uncertainty
                      and all(f.assertionStatus == AssertionStatus.ABSENT for f in extracted.facts.facts if f.factType.startswith("CURRENT_SAFETY:"))
                      and by_id["F-cardiac-history"].assertionStatus != AssertionStatus.UNKNOWN_NOT_STATED)
        if home_clear:
            alias = evidence_by_guideline.get("DEMO-HOME-MONITORING")
            if not alias:
                return manual("HOME_EVIDENCE_MISSING", ReadinessState.UNGROUNDED)
            refs = ["F-age", "F-pregnancy", "F-complete-assessment", "F-cardiac-history"] + [f.factId for f in extracted.facts.facts if f.factType.startswith("CURRENT_SAFETY:")]
            claim = RationaleClaim(claimId="claim-complete-home-assessment",
                                   claim="The assessment exactly matches the curated low-acuity fixture, explicitly negates every required safety category, and records cardiac history. Verified adult, nonpregnant context and approved synthetic guidance satisfy all home-monitoring gates.",
                                   factRefs=refs, evidenceRefs=[alias])
            return PolicyPlan(Disposition.HOME_MONITORING, ReadinessState.READY, [claim], codes + ["ALL_HOME_GATES_PASSED"], True)
        if by_id["F-mild-headache"].assertionStatus == AssertionStatus.PRESENT:
            alias = evidence_by_guideline.get("DEMO-MILD-HEADACHE")
            if not alias:
                return manual("APPLICABLE_EVIDENCE_MISSING", ReadinessState.UNGROUNDED)
            claim = RationaleClaim(claimId="claim-mild-headache-review",
                                   claim="An affirmed current mild headache in this verified adult, nonpregnant assessment matches the synthetic clinician-within-24-hours fixture. No affirmed current patient safety event was identified; any unstated findings remain unknown.",
                                   factRefs=["F-mild-headache", "F-age", "F-pregnancy"], evidenceRefs=[alias])
            return PolicyPlan(Disposition(self.policy["normalRule"]["disposition"]),
                              ReadinessState.INCOMPLETE if extracted.missing else ReadinessState.READY,
                              [claim], codes + ["SYNTHETIC_NORMAL_RULE_PASSED", "HOME_GATES_NOT_MET"], True)
        return manual("CLARIFICATION_REQUIRED")

    def validate(self, synthesis: ModelSynthesis, plan: PolicyPlan, extracted: Extraction,
                 manifest: RetrievalManifest) -> list[str]:
        errors = []
        if synthesis.recommendedDisposition != plan.disposition:
            errors.append("DISPOSITION_POLICY_MISMATCH")
        allowed = {c.claimId: c for c in plan.catalogue}
        fact_ids = {f.factId for f in extracted.facts.facts}
        aliases = {e.alias for e in manifest.evidence}
        seen = set()
        for claim in synthesis.rationale:
            if claim.claimId in seen:
                errors.append("DUPLICATE_CLAIM")
            seen.add(claim.claimId)
            if not set(claim.factRefs) <= fact_ids:
                errors.append("FACT_REFERENCE_INVALID")
            if not set(claim.evidenceRefs) <= aliases:
                errors.append("EVIDENCE_REFERENCE_INVALID")
            expected = allowed.get(claim.claimId)
            if expected is None or claim.model_dump() != expected.model_dump():
                # Exact text+fact+evidence binding prevents a true reference ID
                # from laundering an invented patient fact or unrelated claim.
                errors.append("CLAIM_NOT_IN_TURN_CATALOGUE")
        return list(dict.fromkeys(errors))
