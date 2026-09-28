import pytest
from pydantic import ValidationError
from backend.domain.contracts import ModelSynthesis, TriageRequest


@pytest.mark.parametrize("payload", [
    {},
    {"recommendedDisposition": "HOME_MONITORING"},
    {"recommendedDisposition": "HOME_MONITORING", "rationale": []},
    {"recommendedDisposition": "HOME_MONITORING", "rationale": [{"claimId": "c", "claim": "safe", "factRefs": ["f"], "evidenceRefs": []}]},
    {"recommendedDisposition": "HOME_MONITORING", "rationale": [{"claimId": "c", "claim": "safe", "factRefs": [], "evidenceRefs": ["Ref-1"]}]},
    {"recommendedDisposition": "LOOKS_FINE", "rationale": []},
])
def test_required_clinical_fields_are_not_repaired(payload):
    with pytest.raises(ValidationError):
        ModelSynthesis.model_validate(payload)


def test_request_never_accepts_client_declared_authority():
    with pytest.raises(ValidationError):
        TriageRequest.model_validate({
            "sessionId": "s", "turnId": "t", "baseStateVersion": 0,
            "patientId": "p", "symptomDescription": "Synthetic symptoms",
            "patientDemographics": {"ageInMonths": 400, "isPregnant": False, "biologicalSex": "UNKNOWN"},
            "tenantId": "meridian", "canOverride": True,
        })
