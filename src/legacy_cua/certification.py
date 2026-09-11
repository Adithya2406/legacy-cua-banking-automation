"""Capability certification lifecycle and reviewer fast path."""

from collections.abc import Callable
from datetime import datetime, timezone

from .errors import AutomationError, ErrorCode
from .schemas import ApplicationRegistry, CapabilityArtifact, CertificationStatus, ExecutionResult, OutcomeKind


class CapabilityCertifier:
    """Apply independent structural, semantic, behavioral, and approval gates."""

    def certify(self, artifact: CapabilityArtifact, registry: ApplicationRegistry, semantic_validator: Callable[[CapabilityArtifact], bool], alternate_runner: Callable[[], ExecutionResult], exceptional_runner: Callable[[], ExecutionResult], auto_approve: bool = False, reviewer: str = "cli-auto-approve") -> CapabilityArtifact:
        """
        Certify a draft capability and optionally activate it for reviewer testing.

        Input Parameter:
            artifact(CapabilityArtifact): Draft capability to certify.
            registry(ApplicationRegistry): Registry used to validate all compiled control references.
            semantic_validator(Callable[[CapabilityArtifact], bool]): Semantic goal-to-artifact validation seam.
            alternate_runner(Callable[[], ExecutionResult]): Deterministic alternate-input verification.
            exceptional_runner(Callable[[], ExecutionResult]): Known exceptional-state verification.
            auto_approve(bool): Whether to apply the reviewer fast-path approval.
            reviewer(str): Recorded reviewer identity.

        Output Parameter:
            output_parameter(CapabilityArtifact): Updated certified capability.
        """
        validated = CapabilityArtifact.model_validate(artifact.model_dump())
        control_references = [step.control for step in validated.steps]
        control_references.extend(checkpoint.control for step in validated.steps for checkpoint in step.checkpoints)
        artifact.certification.structural_valid = all(control in registry.controls for control in control_references)
        artifact.certification.semantic_valid = semantic_validator(artifact)
        artifact.certification.alternate_input_verified = alternate_runner().kind == OutcomeKind.SUCCESS
        artifact.certification.exceptional_state_verified = exceptional_runner().kind in {OutcomeKind.BUSINESS_OUTCOME, OutcomeKind.FAILURE}
        checks = artifact.certification
        if not all([checks.structural_valid, checks.semantic_valid, checks.alternate_input_verified, checks.exceptional_state_verified]):
            raise AutomationError(ErrorCode.CERTIFICATION_FAILED, "one or more certification gates failed")
        artifact.status = CertificationStatus.VERIFIED
        if auto_approve:
            artifact.certification.reviewer = reviewer
            artifact.certification.approved_at = datetime.now(timezone.utc)
            artifact.status = CertificationStatus.ACTIVE
        return artifact


def offline_semantic_validator(artifact: CapabilityArtifact) -> bool:
    """
    Validate that required business semantics exist without a live model service.

    Input Parameter:
        artifact(CapabilityArtifact): Candidate capability artifact.

    Output Parameter:
        output_parameter(bool): Whether required semantic concepts are represented.
    """
    actions = {step.action for step in artifact.steps}
    return "member_id" in artifact.inputs and "balance" in artifact.outputs and len(actions) >= 3 and "Savings" in artifact.description
