"""Pydantic contracts shared by discovery, certification, and replay."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Reject unknown fields in persisted contracts."""

    model_config = ConfigDict(extra="forbid")


class Severity(StrEnum):
    """Classify intervention urgency."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Owner(StrEnum):
    """Identify the current live-session owner."""

    AUTOMATION = "automation"
    HUMAN = "human"


class CertificationStatus(StrEnum):
    """Describe the capability lifecycle state."""

    DRAFT = "draft"
    VERIFIED = "verified"
    APPROVED = "approved"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEPRECATED = "deprecated"


class OutcomeKind(StrEnum):
    """Separate success, business outcomes, recoveries, and failures."""

    SUCCESS = "success"
    BUSINESS_OUTCOME = "business_outcome"
    RECOVERED = "recovered"
    FAILURE = "failure"


class RiskClass(StrEnum):
    """Classify action reversibility."""

    SAFE = "safe"
    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"


class ActionKind(StrEnum):
    """List surface-neutral action primitives."""

    NAVIGATE = "navigate"
    INPUT = "input"
    ACTIVATE = "activate"
    EXTRACT = "extract"
    WAIT = "wait"


class Locator(StrictModel):
    """Store one deterministic control-locator signal."""

    strategy: Literal["accessible", "label", "dom_id", "text", "relative"]
    value: str
    role: str | None = None
    weight: int = Field(default=50, ge=1, le=100)


class Control(StrictModel):
    """Describe one discovered application control."""

    control_id: str
    semantic_name: str
    observed_name: str
    role: str
    locators: list[Locator] = Field(min_length=1)
    frame_path: list[str] = Field(default_factory=list)


class ApplicationFingerprint(StrictModel):
    """Identify a vendor product, version, and tenant variant."""

    family: str
    version: str
    tenant: str
    title: str
    route_pattern: str
    landmarks: list[str]
    digest: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ApplicationRegistry(StrictModel):
    """Persist version-specific semantic control knowledge."""

    schema_version: str = "1.0"
    fingerprint: ApplicationFingerprint
    controls: dict[str, Control]
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ParameterSpec(StrictModel):
    """Describe a typed capability input or output."""

    data_type: Literal["string", "number", "boolean", "money"]
    required: bool = True
    sensitive: bool = False
    description: str
    pattern: str | None = None


class ValueReference(StrictModel):
    """Reference invocation data without persisting its value."""

    input_name: str


class Checkpoint(StrictModel):
    """Define a deterministic assertion over UI state."""

    checkpoint_id: str
    level: Literal["action", "state", "goal"]
    assertion: Literal["control_value_equals", "visible", "text_equals", "money"]
    control: str
    expected: str | ValueReference | None = None


class CapabilityStep(StrictModel):
    """Define one transaction-like replay instruction."""

    step_id: str
    action: ActionKind
    control: str
    value: ValueReference | None = None
    output_name: str | None = None
    risk: RiskClass = RiskClass.SAFE
    safe_to_retry: bool = True
    retries: int = Field(default=1, ge=0, le=3)
    checkpoints: list[Checkpoint] = Field(default_factory=list)


class ExceptionRule(StrictModel):
    """Map a known visible state to a deliberate outcome."""

    rule_id: str
    match_type: Literal["visible_text_contains"] = "visible_text_contains"
    contains_text: str
    outcome: Literal["business_outcome", "recoverable", "failure", "intervention"]
    code: str
    severity: Severity | None = None


class CapabilityPolicy(StrictModel):
    """Embed the narrow action and navigation envelope."""

    allowed_actions: list[ActionKind]
    allowed_domains: list[str]
    allowed_route_prefixes: list[str]
    maximum_risk: RiskClass = RiskClass.SAFE


class CertificationRecord(StrictModel):
    """Record independent certification gates and approval state."""

    structural_valid: bool = False
    semantic_valid: bool = False
    alternate_input_verified: bool = False
    exceptional_state_verified: bool = False
    reviewer: str | None = None
    approved_at: datetime | None = None


class CapabilityArtifact(StrictModel):
    """Represent an agent-invocable, certified UI capability."""

    schema_version: str = "1.0"
    capability_id: str
    version: str
    name: str
    description: str
    application_family: str
    registry_digest: str
    inputs: dict[str, ParameterSpec]
    outputs: dict[str, ParameterSpec]
    steps: list[CapabilityStep] = Field(min_length=1)
    exception_rules: list[ExceptionRule] = Field(default_factory=list)
    policy: CapabilityPolicy
    certification: CertificationRecord = Field(default_factory=CertificationRecord)
    status: CertificationStatus = CertificationStatus.DRAFT

    @model_validator(mode="after")
    def validate_references(self) -> CapabilityArtifact:
        """
        Validate all input and output references within the artifact.

        Input Parameter:
            self(CapabilityArtifact): Artifact being validated.

        Output Parameter:
            output_parameter(CapabilityArtifact): Validated artifact instance.
        """
        for step in self.steps:
            if step.value and step.value.input_name not in self.inputs:
                raise ValueError(f"unknown input reference: {step.value.input_name}")
            if step.output_name and step.output_name not in self.outputs:
                raise ValueError(f"unknown output reference: {step.output_name}")
        return self


class ObservedControl(StrictModel):
    """Capture a control observed from the live surface."""

    observed_id: str
    role: str
    name: str
    label: str | None = None
    text: str = ""
    visible: bool = True


class SurfaceObservation(StrictModel):
    """Capture compressed UI semantics plus screenshot evidence."""

    url: str
    title: str
    controls: list[ObservedControl]
    visible_text: str
    screenshot_path: str | None = None


class DiscoveryDecision(StrictModel):
    """Represent one constrained model decision."""

    action: ActionKind
    observed_id: str
    semantic_name: str
    input_name: str | None = None
    output_name: str | None = None
    reason: str
    goal_complete: bool = False


class DiscoveryTraceEntry(StrictModel):
    """Record a discovery action independently of model transcript."""

    sequence: int
    decision: DiscoveryDecision
    observation: SurfaceObservation


class InterventionRequest(StrictModel):
    """Carry the context required for same-session human takeover."""

    request_id: str
    capability_id: str
    step_id: str
    reason: str
    severity: Severity
    screenshot_path: str | None = None
    owner: Owner = Owner.HUMAN
    human_events: list[dict[str, Any]] = Field(default_factory=list)


class ExecutionResult(StrictModel):
    """Return a structured replay result to the calling agent."""

    kind: OutcomeKind
    code: str
    message: str
    outputs: dict[str, Any] = Field(default_factory=dict)
    step_id: str | None = None
    evidence: list[str] = Field(default_factory=list)
    recovered_conditions: list[str] = Field(default_factory=list)
    expected: str | None = None
    observed: str | None = None
    retry_info: dict[str, Any] = Field(default_factory=dict)
    human_intervention_available: bool = False
