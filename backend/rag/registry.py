"""Trusted registry loaded independently from untrusted discovery records."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from backend.domain.contracts import GuidelineRegistryEntry, PatientDemographics


class RegistryError(ValueError):
    pass


def load_registry(path: str | Path) -> dict[str, GuidelineRegistryEntry]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schemaVersion") != 1 or not isinstance(data.get("entries"), list):
        raise RegistryError("Invalid registry envelope")
    result: dict[str, GuidelineRegistryEntry] = {}
    identities: set[tuple[str, str, int]] = set()
    for raw in data["entries"]:
        entry = GuidelineRegistryEntry.model_validate(raw)
        identity = (entry.guidelineId, entry.guidelineVersion, entry.chunkIndex)
        if entry.chunkId in result or identity in identities:
            raise RegistryError("Ambiguous registry identity")
        if not re.fullmatch(r"[0-9a-f]{64}", entry.chunkHash):
            raise RegistryError("Invalid registry content hash")
        if entry.minAgeMonths < 0 or entry.minAgeMonths > entry.maxAgeMonths or entry.maxAgeMonths > 1560:
            raise RegistryError("Invalid registry age range")
        if entry.chunkIndex < 0:
            raise RegistryError("Invalid registry chunk index")
        if entry.expiryDate is not None and entry.expiryDate < entry.effectiveDate:
            raise RegistryError("Invalid registry validity interval")
        result[entry.chunkId] = entry
        identities.add(identity)
    return result


def eligibility_reasons(entry: GuidelineRegistryEntry, patient: PatientDemographics, today: date) -> list[str]:
    """Only trusted registry facts can authorize evidence eligibility.

    This prototype supports adults with pregnancy explicitly false. An unknown
    pregnancy value remains ineligible even if a candidate claims ANY.
    """
    reasons: list[str] = []
    if entry.approvalStatus != "APPROVED":
        reasons.append("NOT_APPROVED")
    if entry.population != "ADULT" or patient.ageInMonths < 216:
        reasons.append("UNSUPPORTED_POPULATION")
    if not entry.minAgeMonths <= patient.ageInMonths <= entry.maxAgeMonths:
        reasons.append("AGE_RANGE")
    if patient.isPregnant is not False:
        reasons.append("NONPREGNANCY_NOT_CONFIRMED")
    if today < entry.effectiveDate:
        reasons.append("NOT_YET_EFFECTIVE")
    if entry.expiryDate is not None and today > entry.expiryDate:
        reasons.append("EXPIRED")
    return reasons
