"""Domain models. Every extracted object carries a Provenance pointing at an exact span.

Enums are the API vocabulary; the UI maps them to plain-language labels (design-review D18).
"""

from __future__ import annotations

import datetime as _dt
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class DocType(StrEnum):
    contract = "contract"
    amendment = "amendment"
    sow = "sow"
    proposal = "proposal"
    policy = "policy"
    audit_report = "audit_report"
    evidence = "evidence"
    report = "report"
    other = "other"


EVIDENCE_TYPES = {DocType.audit_report, DocType.evidence, DocType.report}


class CommitmentType(StrEnum):
    obligation = "obligation"
    entitlement = "entitlement"
    prohibition = "prohibition"
    condition = "condition"
    deadline = "deadline"
    consequence = "consequence"
    service_level = "service_level"


class Modality(StrEnum):
    must = "must"
    must_not = "must_not"
    may = "may"
    reasonable_efforts = "reasonable_efforts"


class DocumentEffect(StrEnum):
    """What later documents did to this commitment (derived, recomputed after each analysis)."""

    in_force = "in_force"
    replaced = "replaced"
    deleted = "deleted"


class Lifecycle(StrEnum):
    """Real-world state. Only a human sets this (design-review D2)."""

    open = "open"
    fulfilled = "fulfilled"
    disputed = "disputed"
    unknown = "unknown"


class CommitmentStatus(StrEnum):
    """The brief's single status, derived from DocumentEffect + Lifecycle + origin."""

    stated = "stated"
    amended = "amended"
    superseded = "superseded"
    open = "open"
    fulfilled = "fulfilled"
    disputed = "disputed"
    unknown = "unknown"


class Confidence(StrEnum):
    """Categorical and rule-derived; never a probability. See docs/commitment-model.md."""

    high = "high"
    medium = "medium"
    low = "low"
    unknown = "unknown"


CONFIDENCE_ORDER = {Confidence.unknown: 0, Confidence.low: 1, Confidence.medium: 2, Confidence.high: 3}


def cap_confidence(c: Confidence, ceiling: Confidence) -> Confidence:
    return c if CONFIDENCE_ORDER[c] <= CONFIDENCE_ORDER[ceiling] else ceiling


class AnswerStatus(StrEnum):
    stated = "stated"
    implied = "implied"
    contradicted = "contradicted"
    not_addressed = "not_addressed"
    ambiguous = "ambiguous"
    needs_human_review = "needs_human_review"


class Verdict(StrEnum):
    consistent = "consistent"
    contradicted = "contradicted"
    partially_supported = "partially_supported"
    not_addressed = "not_addressed"
    ambiguous = "ambiguous"
    needs_human_review = "needs_human_review"


class Severity(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class EdgeType(StrEnum):
    made_by = "made_by"
    owed_to = "owed_to"
    requires = "requires"
    conditioned_on = "conditioned_on"
    amends = "amends"
    supersedes = "supersedes"
    supports = "supports"
    contradicts = "contradicts"
    qualifies = "qualifies"
    depends_on = "depends_on"
    duplicates = "duplicates"
    references = "references"
    evidence_for = "evidence_for"


class ReviewDecisionKind(StrEnum):
    accept = "accept"
    reject = "reject"
    request_evidence = "request_evidence"
    note = "note"
    resolve = "resolve"


class ReviewStatus(StrEnum):
    unreviewed = "unreviewed"
    accepted = "accepted"
    rejected = "rejected"
    needs_evidence = "needs_evidence"
    resolved = "resolved"


DECISION_TO_STATUS = {
    ReviewDecisionKind.accept: ReviewStatus.accepted,
    ReviewDecisionKind.reject: ReviewStatus.rejected,
    ReviewDecisionKind.request_evidence: ReviewStatus.needs_evidence,
    ReviewDecisionKind.resolve: ReviewStatus.resolved,
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Span(_Model):
    """An exact location in a document's stored normalised text."""

    document_id: str
    passage_id: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    quote: str
    page: int | None = None
    section: str | None = None
    document_title: str | None = None
    document_version: str | None = None
    locator: str | None = None  # finer location inside the section, e.g. "table 1, row 3"


class Provenance(_Model):
    source_document_id: str
    document_version: str
    span: Span
    extraction_method: str  # e.g. "rules", "llm"
    extractor_version: str
    model: str | None = None
    endpoint_host: str | None = None
    prompt_version: str | None = None
    extracted_at: datetime = Field(default_factory=utcnow)
    confidence: Confidence
    review_status: ReviewStatus = ReviewStatus.unreviewed


class Document(_Model):
    id: str
    title: str
    version_label: str = "v1"
    doc_type: DocType = DocType.other
    source: str = "upload"
    author: str | None = None
    filename: str | None = None
    uploaded_at: datetime = Field(default_factory=utcnow)
    checksum_sha256: str
    text_sha256: str
    normalizer_version: str
    page_count: int | None = None
    status: str = "parsed"  # parsed | analyzing | analyzed | failed
    warnings: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    amends_document_id: str | None = None
    allow_external_llm: bool = False


class Passage(_Model):
    id: str
    document_id: str
    ordinal: int
    page: int | None
    section_number: str | None
    section_title: str | None
    char_start: int
    char_end: int
    text: str
    hidden_text: str | None = None  # why (part of) this passage is invisible to a reader; excluded from model prompts
    ocr_confidence: float | None = None  # mean OCR word confidence (0-100) of the page, when the text came from OCR
    locator: str | None = None  # e.g. "table 1, row 3": a DOCX table row, cells joined with " | "


OCR_LOW_CONFIDENCE = 70.0  # below this, items from an OCR page carry a caveat and need review


def excluded_from_llm(p: Passage) -> bool:
    """Passages never sent to a language model: hidden text or instruction-like text (see docs/security.md)."""
    from .text import looks_like_injection

    return bool(p.hidden_text) or looks_like_injection(p.text)


class Party(_Model):
    id: str
    document_id: str
    name: str
    alias: str | None = None
    provenance: Provenance


class Definition(_Model):
    id: str
    document_id: str
    term: str
    definition_text: str
    provenance: Provenance


class Deadline(_Model):
    kind: str  # absolute | relative | recurring | vague | none
    raw: str | None = None
    date: _dt.date | None = None
    offset_days: int | None = None
    business_days: bool = False
    anchor: str | None = None
    ambiguous_format: bool = False


class Commitment(_Model):
    id: str
    document_id: str
    text: str
    type: CommitmentType
    modality: Modality
    obliging_party: str | None
    performer_party: str | None = None
    beneficiary_party: str | None
    action: str
    deadline: Deadline | None = None
    conditions: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)  # clause numbers mentioned, e.g. "6.1"
    section_number: str | None = None
    document_effect: DocumentEffect = DocumentEffect.in_force
    lifecycle: Lifecycle = Lifecycle.unknown
    amends_section: str | None = None  # set when this commitment is replacement text from an amendment
    status: CommitmentStatus = CommitmentStatus.stated
    confidence: Confidence
    needs_review: bool
    review_reasons: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    provenance: Provenance


class Claim(_Model):
    id: str
    document_id: str
    text: str
    claim_type: str  # control | measurement | event | statement | scope_limit
    section_number: str | None
    confidence: Confidence
    needs_review: bool
    provenance: Provenance


class AmendmentInstruction(_Model):
    id: str
    document_id: str
    # a clause number ("4.2"), a schedule ("Schedule 2"), a heading ("title:Confidentiality"),
    # "*" for an amended-and-restated document, or "after 4.3"/"before 4.1" for an unnumbered insert
    target_section: str
    action: str  # replace | delete | insert | modify | renumber | restate
    new_text: str | None
    old_text: str | None = None  # modify: the words being changed
    anchor_section: str | None = None  # insert: the clause it goes after/before
    position: str | None = None  # insert: "after" | "before"
    renumber_to: str | None = None  # renumber: the new clause number
    # set by apply_amendments once the target is looked up in the amended document
    resolved_section: str | None = None
    needs_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    provenance: Provenance


class Edge(_Model):
    id: str
    src_id: str
    dst_id: str
    type: EdgeType
    document_id: str | None = None
    provenance: Provenance | None = None
    created_at: datetime = Field(default_factory=utcnow)


class GraphStep(_Model):
    node: str
    edge: str | None = None  # edge leading to the next step


class Citation(_Model):
    span: Span
    role: str = "supports"  # supports | conflicts | checked_not_supporting | context
    verified: bool
    note: str | None = None


class Answer(_Model):
    id: str
    question: str
    document_ids: list[str]
    status: AnswerStatus
    answer_text: str
    confidence: Confidence
    citations: list[Citation]
    graph_path: list[GraphStep] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.unreviewed
    needs_review: bool = False
    run_manifest: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class Finding(_Model):
    id: str
    run_id: str
    verdict: Verdict
    subject_id: str | None
    subject_text: str
    subject_span: Span | None
    supporting: list[Span] = Field(default_factory=list)
    conflicting: list[Span] = Field(default_factory=list)
    explanation: str
    severity: Severity
    recommended_action: str
    sufficiency: str | None = None  # "reviewer_judgement_required" for evidence checks (D6)
    review_status: ReviewStatus = ReviewStatus.unreviewed


class VerificationRun(_Model):
    id: str
    base_document_id: str
    other_document_id: str
    mode: str  # amendment | evidence | version | general
    findings: list[Finding]
    summary: dict[str, int]
    run_manifest: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class ReviewDecision(_Model):
    id: str
    target_kind: str  # commitment | answer | finding
    target_id: str
    decision: ReviewDecisionKind
    note: str | None = None
    reviewer: str
    reviewer_verified: bool = False  # v0.1 has no auth: names are self-declared
    prior_status: ReviewStatus
    target_hash: str
    at: datetime = Field(default_factory=utcnow)


class AnalysisRun(_Model):
    id: str
    document_id: str
    extractor_version: str
    status: str  # queued | running | done | failed
    error: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    run_manifest: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


def derive_status(c: Commitment) -> CommitmentStatus:
    if c.document_effect in (DocumentEffect.replaced, DocumentEffect.deleted):
        return CommitmentStatus.superseded
    if c.lifecycle == Lifecycle.fulfilled:
        return CommitmentStatus.fulfilled
    if c.lifecycle == Lifecycle.disputed:
        return CommitmentStatus.disputed
    if c.amends_section:
        return CommitmentStatus.amended
    if c.lifecycle == Lifecycle.open:
        return CommitmentStatus.open
    return CommitmentStatus.stated
