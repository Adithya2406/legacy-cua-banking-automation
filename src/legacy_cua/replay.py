"""Deterministic model-free capability replay."""

import re
from pathlib import Path
from typing import Any

from .errors import AutomationError, ErrorCode
from .handoff import SessionOwnershipController
from .logging import JsonLogger
from .policy import PolicyEngine
from .schemas import (
    ActionKind,
    ApplicationRegistry,
    CapabilityArtifact,
    CertificationStatus,
    ExecutionResult,
    OutcomeKind,
    Severity,
    ValueReference,
)
from .surface import SurfaceDriver


class ReplayEngine:
    """Execute only precompiled steps with deterministic checks and recovery."""

    def __init__(self, surface: SurfaceDriver, logger: JsonLogger, evidence_dir: Path) -> None:
        """
        Initialize a replay engine without any model dependency.

        Input Parameter:
            surface(SurfaceDriver): Live surface driver.
            logger(JsonLogger): Structured audit logger.
            evidence_dir(Path): Replay evidence directory.

        Output Parameter:
            output_parameter(None): This initializer returns no value.
        """
        self.surface = surface
        self.logger = logger
        self.evidence_dir = evidence_dir
        self.policy = PolicyEngine()
        self.ownership = SessionOwnershipController(surface, logger)

    def _log_terminal_result(self, result: ExecutionResult) -> None:
        """
        Persist a final terminal event for each replay run.

        Input Parameter:
            result(ExecutionResult): Structured terminal replay result.

        Output Parameter:
            output_parameter(None): This function returns no value.
        """
        self.logger.event(
            "replay_completed",
            result.code,
            result.message,
            kind=result.kind,
            step_id=result.step_id,
            outputs=result.outputs,
            evidence=result.evidence,
            recovered_conditions=result.recovered_conditions,
        )

    def run(self, artifact: CapabilityArtifact, registry: ApplicationRegistry, inputs: dict[str, Any]) -> ExecutionResult:
        """
        Replay an active artifact and return a structured outcome.

        Input Parameter:
            artifact(CapabilityArtifact): Certified deterministic capability.
            registry(ApplicationRegistry): Matching application control registry.
            inputs(dict[str, Any]): Ephemeral invocation values.

        Output Parameter:
            output_parameter(ExecutionResult): Structured success, business outcome, or failure.
        """
        if artifact.status != CertificationStatus.ACTIVE:
            result = ExecutionResult(kind=OutcomeKind.FAILURE, code=ErrorCode.CAPABILITY_NOT_ACTIVE, message="capability is not active")
            self._log_terminal_result(result)
            return result
        sensitive_inputs = {name: inputs.get(name) for name, spec in artifact.inputs.items() if spec.sensitive and inputs.get(name) is not None}
        self.logger.register_sensitive_values(sensitive_inputs)
        self._recovered_conditions: list[str] = []
        self._evidence_paths: list[str] = []
        invalid = self._validate_inputs(artifact, inputs)
        if invalid:
            self._log_terminal_result(invalid)
            return invalid
        outputs: dict[str, Any] = {}
        for step in artifact.steps:
            screenshot = self.evidence_dir / f"replay-{step.step_id}.png"
            try:
                observation = self.surface.observe(screenshot)
                self._evidence_paths.append(str(screenshot))
                exceptional = self._classify_exception(artifact, registry, observation.visible_text, step.step_id, str(screenshot))
                if exceptional:
                    return exceptional
                self.policy.validate(artifact.policy, step.action, self.surface.current_url(), step.risk)
                control = registry.controls[step.control]
                value = inputs.get(step.value.input_name) if step.value else None
                self.logger.event("replay_step_started", "CUA-INFO-010", "executing compiled step", step_id=step.step_id, action=step.action, input_name=step.value.input_name if step.value else None)
                extracted = self._execute_with_retry(step.safe_to_retry, step.retries, step.action, control, value)
                if step.output_name:
                    outputs[step.output_name] = self._parse_money(extracted or "")
                self._verify_checkpoints(step.checkpoints, registry, inputs)
                self.logger.event("replay_step_completed", "CUA-INFO-011", "compiled step verified", step_id=step.step_id)
            except AutomationError as error:
                self.surface.observe(self.evidence_dir / f"failure-{step.step_id}.png")
                self.logger.event("replay_failed", error.code, str(error), step_id=step.step_id)
                result = ExecutionResult(kind=OutcomeKind.FAILURE, code=error.code, message=str(error), step_id=step.step_id, evidence=[str(screenshot)])
                self._log_terminal_result(result)
                return result
        result = ExecutionResult(kind=OutcomeKind.SUCCESS, code="CAPABILITY_COMPLETED", message="all checkpoints passed", outputs=outputs, evidence=self._evidence_paths, recovered_conditions=self._recovered_conditions)
        self._log_terminal_result(result)
        return result

    def _validate_inputs(self, artifact: CapabilityArtifact, inputs: dict[str, Any]) -> ExecutionResult | None:
        """
        Validate required invocation parameters without persisting their values.

        Input Parameter:
            artifact(CapabilityArtifact): Capability input contract.
            inputs(dict[str, Any]): Invocation values.

        Output Parameter:
            output_parameter(ExecutionResult | None): Failure result or no result when valid.
        """
        for name, spec in artifact.inputs.items():
            value = inputs.get(name)
            if spec.required and value is None:
                return ExecutionResult(kind=OutcomeKind.FAILURE, code=ErrorCode.INPUT_INVALID, message=f"missing input: {name}")
            if spec.pattern and not re.fullmatch(spec.pattern, str(value)):
                return ExecutionResult(kind=OutcomeKind.FAILURE, code=ErrorCode.INPUT_INVALID, message=f"invalid input shape: {name}")
        return None

    def _execute_with_retry(self, safe_to_retry: bool, retries: int, action: ActionKind, control: Any, value: Any) -> str | None:
        """
        Retry only explicitly idempotent surface actions.

        Input Parameter:
            safe_to_retry(bool): Whether retry is permitted.
            retries(int): Maximum retry count.
            action(ActionKind): Compiled action primitive.
            control(Any): Resolved registry control definition.
            value(Any): Optional ephemeral action value.

        Output Parameter:
            output_parameter(str | None): Extracted value when applicable.
        """
        attempts = 1 + (retries if safe_to_retry else 0)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return self.surface.act(action, control, str(value) if value is not None else None)
            except AutomationError as error:
                last_error = error
                self.logger.event("recoverable_retry", "CUA-INFO-012", "safe action retry", attempt=attempt + 1, action=action)
        if isinstance(last_error, AutomationError):
            raise last_error
        return None

    def _verify_checkpoints(self, checkpoints: list[Any], registry: ApplicationRegistry, inputs: dict[str, Any]) -> None:
        """
        Evaluate action and goal checkpoints after a step.

        Input Parameter:
            checkpoints(list[Any]): Compiled checkpoint definitions.
            registry(ApplicationRegistry): Current application registry.
            inputs(dict[str, Any]): Ephemeral invocation values.

        Output Parameter:
            output_parameter(None): This function returns no value when all checks pass.
        """
        for checkpoint in checkpoints:
            control = registry.controls[checkpoint.control]
            observed = self.surface.act(ActionKind.EXTRACT, control)
            expected = inputs.get(checkpoint.expected.input_name) if isinstance(checkpoint.expected, ValueReference) else checkpoint.expected
            passed = (checkpoint.assertion == "control_value_equals" and observed == expected) or (checkpoint.assertion == "visible") or (checkpoint.assertion == "text_equals" and observed == expected) or (checkpoint.assertion == "money" and bool(re.fullmatch(r"\$?[0-9,]+\.\d{2}", observed or "")))
            if not passed:
                raise AutomationError(ErrorCode.CHECKPOINT_FAILED, f"checkpoint failed: {checkpoint.checkpoint_id}")

    def _classify_exception(self, artifact: CapabilityArtifact, registry: ApplicationRegistry, visible_text: str, step_id: str, screenshot_path: str) -> ExecutionResult | None:
        """
        Classify known UI states before executing the next step.

        Input Parameter:
            artifact(CapabilityArtifact): Capability exception rules.
            registry(ApplicationRegistry): Application registry containing exception controls.
            visible_text(str): Current surface text.
            step_id(str): Current replay step.
            screenshot_path(str): Evidence screenshot path.

        Output Parameter:
            output_parameter(ExecutionResult | None): Deliberate outcome or no result.
        """
        for rule in artifact.exception_rules:
            if rule.contains_text not in visible_text:
                continue
            if rule.outcome == "business_outcome":
                result = ExecutionResult(kind=OutcomeKind.BUSINESS_OUTCOME, code=rule.code, message=rule.contains_text, step_id=step_id, evidence=[screenshot_path])
                self._log_terminal_result(result)
                return result
            if rule.outcome == "failure":
                result = ExecutionResult(kind=OutcomeKind.FAILURE, code=rule.code, message=rule.contains_text, step_id=step_id, evidence=[screenshot_path])
                self._log_terminal_result(result)
                return result
            if rule.outcome == "recoverable":
                retry_control = registry.controls["member_lookup_action"]
                self.surface.act(ActionKind.ACTIVATE, retry_control)
                recovered_path = self.evidence_dir / f"recovered-{step_id}.png"
                recovered = self.surface.observe(recovered_path)
                self._evidence_paths.append(str(recovered_path))
                if rule.contains_text in recovered.visible_text:
                    result = ExecutionResult(kind=OutcomeKind.FAILURE, code=ErrorCode.APPLICATION_ERROR, message="deterministic recovery did not clear the transient state", step_id=step_id, evidence=[screenshot_path, str(recovered_path)])
                    self._log_terminal_result(result)
                    return result
                self._recovered_conditions.append(rule.code)
                self.logger.event("condition_recovered", "CUA-INFO-013", "known transient state recovered deterministically", recovery_code=rule.code, step_id=step_id)
                return None
            if rule.outcome == "intervention":
                if hasattr(self.surface, "page") and not getattr(self.surface, "headed", False):
                    result = ExecutionResult(kind=OutcomeKind.FAILURE, code=ErrorCode.INTERVENTION_REQUIRED, message="human intervention requires --headed so the same live session is visible", step_id=step_id, evidence=[screenshot_path])
                    self._log_terminal_result(result)
                    return result
                request = self.ownership.handoff(artifact.capability_id, step_id, rule.contains_text, rule.severity or Severity.MEDIUM, screenshot_path)
                resumed_path = self.evidence_dir / f"resume-{step_id}.png"
                resumed = self.surface.observe(resumed_path)
                self._evidence_paths.append(str(resumed_path))
                if rule.contains_text in resumed.visible_text:
                    result = ExecutionResult(kind=OutcomeKind.FAILURE, code=ErrorCode.RESUME_STATE_INVALID, message="human returned control without resolving the blocking state", step_id=step_id, evidence=[screenshot_path, str(resumed_path)])
                    self._log_terminal_result(result)
                    return result
                self.logger.event("resume_state_validated", "CUA-INFO-021", "post-handoff state is safe for deterministic continuation", request_id=request.request_id, step_id=step_id, ownership_transition=["automation", "human", "automation"], human_events=request.human_events)
                return None
        return None

    def _parse_money(self, value: str) -> float:
        """
        Parse a displayed US-dollar amount into a numeric output.

        Input Parameter:
            value(str): Displayed currency string.

        Output Parameter:
            output_parameter(float): Numeric currency amount.
        """
        try:
            return float(value.replace("$", "").replace(",", ""))
        except ValueError as error:
            raise AutomationError(ErrorCode.CHECKPOINT_FAILED, "balance was not valid money") from error
