"""Deterministic vector discovery and defensive ingestion.

No vector-store field is an approval or policy authority. Registry validation in
``retriever`` is required even for records produced by this module.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


DIMENSIONS = 384
EMBEDDING_ALGORITHM = "sha256-unigram-bigram-384-v1"

# Token hashing is deterministic across Python processes; Python's salted hash()
# is deliberately not used. Stop words limit common demo boilerplate matches.
_STOP_WORDS = frozenset(
    "a an and are as at be been but by can could demonstration demo do does for "
    "from has have i if in is it its may me my of on only or our patient policy "
    "record synthetic that the their these this to training use was we were will "
    "with would you your not no current confirmed affirmed fixture fixtures "
    "guidance clinical validated protocol real care disposition recommendation "
    "adult adults pregnant nonpregnant non pregnant eligible evidence supported "
    "assessment information required requires known must one".split()
)

_INSTRUCTION_PATTERNS = (
    ("ROLE_DELIMITER", r"(?:<\|(?:im_start|system|assistant|developer)|\[(?:INST|SYSTEM)\]|</?(?:system|assistant|developer)(?:\s|>))"),
    ("ROLE_OVERRIDE", r"(?:^|\n)\s*(?:system|developer|assistant)\s*(?:message|prompt)?\s*:"),
    ("IGNORE_INSTRUCTIONS", r"\b(?:ignore|disregard|forget|bypass|override)\b.{0,90}\b(?:instructions?|prompts?|guardrails?|safety\s*(?:rules?|policy|gates?)|system|validation)\b"),
    ("OUTPUT_OVERRIDE", r"\b(?:always|must|instead|only)\s+(?:return|output|respond|recommend)\b.{0,70}\b(?:home_monitoring|home monitoring|json|disposition)\b"),
    ("FIELD_OVERRIDE", r"\b(?:set|force|replace|change)\s+(?:the\s+)?(?:recommendedDisposition|readinessState|safetyLocked|evidenceRefs|system\s+prompt)\b"),
    ("SECRET_REQUEST", r"\b(?:reveal|print|exfiltrate|send)\b.{0,70}\b(?:secrets?|api\s*keys?|system\s*prompts?|credentials?|access\s*tokens?)\b"),
)


def content_hash(text: str) -> str:
    """Hash exact UTF-8 source bytes, without whitespace normalization."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def instruction_signals(text: str) -> list[str]:
    """Identify source text that attempts to control the application/model.

    This is a narrow quarantine heuristic, not a complete injection detector.
    Safety also depends on registry hashes, exact claim validation, and policy.
    """
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(c for c in normalized if unicodedata.category(c) != "Cf")
    return [
        code
        for code, pattern in _INSTRUCTION_PATTERNS
        if re.search(pattern, normalized, flags=re.IGNORECASE | re.DOTALL)
    ]


def hashed_embedding(text: str) -> list[float]:
    """Small signed, normalized bag-of-words/bigrams embedding, no API calls."""
    words = [
        token
        for token in re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", text).lower())
        if token not in _STOP_WORDS
    ]
    counts: Counter[str] = Counter(words)
    counts.update(f"{left}:{right}" for left, right in zip(words, words[1:]))
    vector = [0.0] * DIMENSIONS
    for token, count in sorted(counts.items()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % DIMENSIONS
        sign = 1.0 if digest[4] & 1 else -1.0
        weight = 0.6 if ":" in token else 1.0
        vector[index] += sign * (1.0 + math.log(count)) * weight
    norm = math.sqrt(sum(value * value for value in vector))
    return [round(value / norm, 10) for value in vector] if norm else vector


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != DIMENSIONS or len(right) != DIMENSIONS:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right)) / left_norm / right_norm))


class DiscoveryMetadata(BaseModel):
    """Untrusted search hints. Every field is independently checked later."""

    model_config = ConfigDict(extra="forbid", strict=True)
    approvalStatus: Literal["APPROVED", "REJECTED", "RETIRED"]
    population: Literal["ADULT", "PEDIATRIC"]
    minAgeMonths: Annotated[int, Field(ge=0, le=1560)]
    maxAgeMonths: Annotated[int, Field(ge=0, le=1560)]
    pregnancyApplicability: Literal["NON_PREGNANT_ONLY", "ANY"]
    effectiveDate: str
    expiryDate: str | None

    @field_validator("effectiveDate", "expiryDate")
    @classmethod
    def iso_date(cls, value: str | None) -> str | None:
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError("Date must be YYYY-MM-DD")
        return value


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    chunkId: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")]
    guidelineId: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")]
    guidelineVersion: Annotated[str, Field(min_length=1, max_length=100)]
    chunkIndex: Annotated[int, Field(ge=0)]
    text: Annotated[str, Field(min_length=1, max_length=30000)]
    metadata: DiscoveryMetadata


class VectorRecord(SourceRecord):
    sourceHash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    embedding: Annotated[list[float], Field(min_length=DIMENSIONS, max_length=DIMENSIONS)]

    @field_validator("embedding")
    @classmethod
    def finite_embedding(cls, values: list[float]) -> list[float]:
        if not all(math.isfinite(value) and abs(value) <= 1.0 for value in values):
            raise ValueError("Embedding must contain finite normalized values")
        return values


def safe_record_id(raw: Any) -> str:
    candidate = raw.get("chunkId") if isinstance(raw, dict) else None
    if isinstance(candidate, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", candidate):
        return candidate
    return "invalid-record"


def ingest_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Build an *untrusted* vector index, quarantining suspicious source text.

    No registry entry is created or updated here: approval is independent.
    Quarantine contains reason codes and a digest, never instruction payloads.
    """
    output: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in records:
        identifier = safe_record_id(raw)
        try:
            record = SourceRecord.model_validate(raw)
        except (ValidationError, TypeError, ValueError):
            quarantined.append({"chunkId": identifier, "reasonCodes": ["INVALID_SOURCE_SCHEMA"]})
            continue
        signals = instruction_signals(record.text)
        if record.chunkId in seen:
            signals.append("DUPLICATE_CHUNK_ID")
        seen.add(record.chunkId)
        if signals:
            quarantined.append({
                "chunkId": record.chunkId,
                "reasonCodes": signals,
                "contentHash": content_hash(record.text),
            })
            # Ambiguous identities are removed in full, not resolved by ordering.
            if "DUPLICATE_CHUNK_ID" in signals:
                output = [item for item in output if item["chunkId"] != record.chunkId]
            continue
        output.append({
            **record.model_dump(),
            "sourceHash": content_hash(record.text),
            "embedding": hashed_embedding(record.text),
        })
    return {
        "schemaVersion": 1,
        "syntheticOnly": True,
        "embeddingAlgorithm": EMBEDDING_ALGORITHM,
        "dimensions": DIMENSIONS,
        "records": output,
        "quarantined": quarantined,
    }


def ingest_file(source_path: str | Path, store_path: str | Path) -> dict[str, Any]:
    """Regenerate discovery data only; never rewrites the trusted registry."""
    source = json.loads(Path(source_path).read_text(encoding="utf-8"))
    result = ingest_records(source["records"])
    Path(store_path).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
