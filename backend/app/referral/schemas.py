from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DocumentType = Literal[
    "referral",
    "lab",
    "report",
    "attachment",
    "coverage_attachment",
    "medication_list",
    "imaging",
    "nursing_transfer",
    "consult_request",
    "unknown",
]
OcrStatus = Literal["ok", "low", "failed", "unknown"]
Sex = Literal["male", "female", "diverse", "unknown"]
AttachmentStatus = Literal["present", "missing", "unclear"]
Urgency = Literal["normal", "timely", "human_review", "unknown"]
Severity = Literal["blocking", "recommended", "info"]


def _truncate_text(value: Any, max_chars: int) -> Any:
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars].rstrip()
    return value


def _truncate_text_list(value: Any, *, max_items: int, max_chars: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    result: list[str] = []
    for item in value[:max_items]:
        if item is None:
            continue
        result.append(str(_truncate_text(str(item), max_chars)))
    return result


class Patient(BaseModel):
    name: str | None = None
    birth_date: date | None = None
    sex: Sex = "unknown"
    phone: str | None = None
    insurance_id: str | None = None
    address: str | None = None


class ReferringParty(BaseModel):
    physician_name: str | None = None
    organization: str | None = None
    phone: str | None = None
    email: str | None = None
    zsr_or_gln: str | None = None


class ClinicalContext(BaseModel):
    reason_for_referral: str | None = None
    suspected_or_known_conditions: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    medication_list_mentioned: bool = False
    lab_or_imaging_mentioned: bool = False
    requested_service: str | None = None


class Attachments(BaseModel):
    lab: AttachmentStatus = "unclear"
    imaging: AttachmentStatus = "unclear"
    medication_list: AttachmentStatus = "unclear"
    prior_reports: AttachmentStatus = "unclear"
    consent_form: AttachmentStatus = "unclear"


class RoutingProposal(BaseModel):
    department: str | None = None
    routing_target: str | None = None
    administrative_urgency: Urgency = "unknown"
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class ModelSuggestedDestination(BaseModel):
    label: str | None = None
    reason: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    mapped_to_routing_target: str | None = None

    @field_validator("label", "reason", "mapped_to_routing_target", mode="before")
    @classmethod
    def cap_text(cls, value: Any) -> Any:
        return _truncate_text(value, 240)


class SecondaryRoutingSuggestion(BaseModel):
    routing_target: str | None = None
    department: str | None = None
    label: str | None = None
    reason: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("routing_target", "department", "label", "reason", mode="before")
    @classmethod
    def cap_text(cls, value: Any) -> Any:
        return _truncate_text(value, 240)


class UnmappedFinding(BaseModel):
    label: str
    value: str | None = None
    reason: str | None = None

    @field_validator("label", "value", "reason", mode="before")
    @classmethod
    def cap_text(cls, value: Any) -> Any:
        return _truncate_text(value, 240)


class MissingItem(BaseModel):
    field: str
    reason: str
    severity: Severity


class EvidenceItem(BaseModel):
    claim: str
    quote: str
    page: int | None = None
    source_span: str | None = None

    @field_validator("claim", "quote", "source_span", mode="before")
    @classmethod
    def cap_text(cls, value: Any) -> Any:
        return _truncate_text(value, 280)


class CompactClinicalContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reason_for_referral: str | None = None
    conditions: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    medication_list_mentioned: bool = False
    lab_or_imaging_mentioned: bool = False
    requested_service: str | None = None

    @field_validator("reason_for_referral", "requested_service", mode="before")
    @classmethod
    def cap_text(cls, value: Any) -> Any:
        return _truncate_text(value, 240)

    @field_validator("conditions", "symptoms", mode="before")
    @classmethod
    def cap_lists(cls, value: Any) -> list[str]:
        return _truncate_text_list(value, max_items=8, max_chars=80)


class CompactRouting(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target: str | None = None
    administrative_urgency: Urgency = "unknown"
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)

    @field_validator("target", mode="before")
    @classmethod
    def cap_target(cls, value: Any) -> Any:
        return _truncate_text(value, 120)


class CompactEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field: str
    quote: str

    @field_validator("field", mode="before")
    @classmethod
    def cap_field(cls, value: Any) -> Any:
        return _truncate_text(value, 120)

    @field_validator("quote", mode="before")
    @classmethod
    def cap_quote(cls, value: Any) -> Any:
        return _truncate_text(value, 280)


class CompactReferralModelOutput(BaseModel):
    """Model-facing extraction schema kept smaller than ReferralAnalysis."""

    model_config = ConfigDict(extra="ignore")

    document_type: DocumentType = "unknown"
    language: str = "de"
    patient: Patient = Field(default_factory=Patient)
    referring_party: ReferringParty = Field(default_factory=ReferringParty)
    clinical_context: CompactClinicalContext = Field(default_factory=CompactClinicalContext)
    attachments: Attachments = Field(default_factory=Attachments)
    routing: CompactRouting = Field(default_factory=CompactRouting)
    secondary_routing_targets: list[str] = Field(default_factory=list)
    model_suggested_destination: str | None = None
    missing_required_items: list[str] = Field(default_factory=list)
    evidence: list[CompactEvidenceItem] = Field(default_factory=list)
    rationale: str | None = None
    uncertainties: list[str] = Field(default_factory=list)
    human_review_required: bool = True

    @field_validator("language", "model_suggested_destination", "rationale", mode="before")
    @classmethod
    def cap_text(cls, value: Any) -> Any:
        return _truncate_text(value, 280)

    @field_validator("secondary_routing_targets", mode="before")
    @classmethod
    def normalize_secondary_targets(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        targets: list[str] = []
        for item in value[:3]:
            if isinstance(item, dict):
                raw = item.get("routing_target") or item.get("target") or item.get("label")
            else:
                raw = item
            if raw:
                targets.append(str(_truncate_text(str(raw), 120)))
        return targets

    @field_validator("missing_required_items", "uncertainties", mode="before")
    @classmethod
    def cap_lists(cls, value: Any) -> list[str]:
        return _truncate_text_list(value, max_items=8, max_chars=160)

    @field_validator("evidence", mode="before")
    @classmethod
    def cap_evidence(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        if not isinstance(value, list):
            return []
        return value[:8]


class ReferralAnalysis(BaseModel):
    document_id: str
    document_type: DocumentType = "unknown"
    language: str = "de"
    patient: Patient = Field(default_factory=Patient)
    referring_party: ReferringParty = Field(default_factory=ReferringParty)
    clinical_context_for_admin_routing: ClinicalContext = Field(default_factory=ClinicalContext)
    attachments: Attachments = Field(default_factory=Attachments)
    routing_proposal: RoutingProposal = Field(default_factory=RoutingProposal)
    model_suggested_destination: ModelSuggestedDestination | None = None
    secondary_routing_targets: list[SecondaryRoutingSuggestion] = Field(default_factory=list)
    unmapped_findings: list[UnmappedFinding] = Field(default_factory=list)
    missing_items: list[MissingItem] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    human_review_required: bool = True
    warnings: list[str] = Field(default_factory=list)
    ocr_min_confidence: float | None = None
    ocr_status: OcrStatus = "unknown"

    @field_validator("warnings", mode="before")
    @classmethod
    def cap_warnings(cls, value: Any) -> list[str]:
        return _truncate_text_list(value, max_items=12, max_chars=240)


class ReferralCaseRead(BaseModel):
    id: str
    document_id: str
    status: str
    analysis: ReferralAnalysis
    model_profile: str
    prompt_version: str
    created_at: datetime
    reviewed_at: datetime | None = None


class ReviewRequest(BaseModel):
    decision: Literal["confirm", "correct", "reject", "question"]
    corrected_analysis: ReferralAnalysis | None = None
    comment: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_correction_semantics(self) -> ReviewRequest:
        if self.decision == "correct" and self.corrected_analysis is None:
            raise ValueError("corrected_analysis is required for decision=correct")
        if self.decision != "correct" and self.corrected_analysis is not None:
            raise ValueError("corrected_analysis is only allowed for decision=correct")
        return self


class ReviewRead(BaseModel):
    id: str
    case_id: str
    reviewer_id: str
    decision: str
    created_at: datetime
    warning: str | None = None


ReferralWorklistFilter = Literal[
    "active",
    "all",
    "new",
    "review_required",
    "ocr_low",
    "route_unclear",
    "confirmed",
    "rejected",
]


class ReferralPipelineStageStatus(BaseModel):
    status: Literal["ok", "warning", "failed", "pending", "completed", "unknown"]
    label: str
    detail: str | None = None


class ReferralWorklistPipelineStatus(BaseModel):
    inbox: ReferralPipelineStageStatus
    pypdf: ReferralPipelineStageStatus
    ocr: ReferralPipelineStageStatus
    model: ReferralPipelineStageStatus
    review: ReferralPipelineStageStatus
    output: ReferralPipelineStageStatus


class ReferralWorklistItem(BaseModel):
    case_id: str | None
    document_id: str
    document_title: str
    source_system: str
    status: str
    routing_target: str | None
    department: str | None
    confidence: float | None
    human_review_required: bool
    missing_count: int
    ocr_min_confidence: float | None
    ocr_status: OcrStatus
    warnings: list[str]
    created_at: datetime
    reviewed_at: datetime | None = None
    pipeline: ReferralWorklistPipelineStatus


class ReferralPipelineEventRead(BaseModel):
    id: str
    document_id: str | None
    case_id: str | None
    stage: str
    status: str
    message: str
    payload: dict[str, Any] | None = None
    created_at: datetime


class ReferralDemoOutputRead(BaseModel):
    decision: str
    decision_label: str | None = None
    file_name: str
    relative_path: str
    case_id: str | None
    document_id: str | None
    document_title: str | None = None
    department: str | None = None
    routing_target: str | None
    referring_organization: str | None = None
    referring_physician: str | None = None
    created_at: datetime | None


class ReferralRoutingTargetRead(BaseModel):
    routing_target: str
    department: str


class MissingFieldCount(BaseModel):
    field: str
    count: int


class ReferralBatchSummary(BaseModel):
    total_documents: int
    active_worklist: int
    open_items: int
    new_documents: int
    analyzed: int
    review_required: int
    ready_to_forward: int
    forwarded: int
    ocr_low: int
    ocr_failed: int
    route_unclear: int
    model_errors: int
    confirmed: int
    corrected: int
    rejected: int
    questions: int
    routing_distribution: dict[str, int]
    top_missing_fields: list[MissingFieldCount]
    average_confidence: float | None
    average_ocr_confidence: float | None
    generated_at: datetime


class ReferralIngestReport(BaseModel):
    documents: int
    skipped: int
    changed: int
    analyses: int
    summary: ReferralBatchSummary


class ReferralInboxSummary(BaseModel):
    source_name: str
    backend: Literal["filesystem", "minio"]
    location: str
    bucket: str
    prefix: str
    total_pdfs: int
    registered_documents: int
    unregistered_pdfs: int
    analyzed_documents: int
    pending_analysis: int
    processable_pdfs: int
    generated_at: datetime


class ReferralInboxProcessRequest(BaseModel):
    limit: int = Field(default=2, ge=1, le=100)


class ReferralInboxProcessedDocument(BaseModel):
    document_id: str
    case_id: str | None
    document_title: str
    source_uri: str
    decision: str
    status: str


class ReferralInboxProcessResult(BaseModel):
    requested_limit: int
    processed: int
    skipped: int
    documents: list[ReferralInboxProcessedDocument]
    inbox: ReferralInboxSummary
    summary: ReferralBatchSummary


class ReferralInboxUploadRejected(BaseModel):
    file_name: str
    reason: str


class ReferralInboxUploadResult(BaseModel):
    uploaded: int
    rejected: list[ReferralInboxUploadRejected]
    files: list[str]
    inbox: ReferralInboxSummary


class ReferralDemoResetResult(BaseModel):
    documents_deleted: int
    pages_deleted: int
    cases_deleted: int
    reviews_deleted: int
    events_deleted: int
    inbox_files_deleted: int
    output_files_deleted: int
    inbox: ReferralInboxSummary
    summary: ReferralBatchSummary
