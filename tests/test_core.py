"""Load-bearing contract, safety, compiler, replay, and handoff tests."""

from pathlib import Path

import pytest

from legacy_cua.certification import CapabilityCertifier, offline_semantic_validator
from legacy_cua.compiler import CapabilityCompiler
from legacy_cua.errors import AutomationError, ErrorCode
from legacy_cua.handoff import SessionOwnershipController
from legacy_cua.logging import JsonLogger
from legacy_cua.policy import PolicyEngine
from legacy_cua.providers import OfflineSemanticFixtureProvider
from legacy_cua.replay import ReplayEngine
from legacy_cua.schemas import ActionKind, ApplicationRegistry, CapabilityArtifact, CapabilityPolicy, CertificationStatus, DiscoveryDecision, ExecutionResult, InterventionRequest, OutcomeKind, RiskClass, Severity, SurfaceObservation
from legacy_cua.discovery import DiscoveryEngine

from .fakes import FakeSurface


def build_artifact(tmp_path: Path) -> tuple[CapabilityArtifact, ApplicationRegistry]:
    """
    Discover and compile a test artifact from actually observed fake controls.

    Input Parameter:
        tmp_path(Path): Temporary test directory.

    Output Parameter:
        output_parameter(tuple): Active artifact and matching registry.
    """
    surface = FakeSurface()
    trace, registry = DiscoveryEngine(surface, OfflineSemanticFixtureProvider(), JsonLogger(tmp_path / "discovery.jsonl"), tmp_path).run("find a customer's savings balance", {"member_id": "10001"})
    artifact = CapabilityCompiler().compile(trace, registry)
    artifact.status = CertificationStatus.ACTIVE
    return artifact, registry


def test_replay_success_and_business_outcome(tmp_path: Path) -> None:
    """
    Verify deterministic success and not-found business outcome classification.

    Input Parameter:
        tmp_path(Path): Temporary test directory.

    Output Parameter:
        output_parameter(None): Pytest asserts behavior directly.
    """
    artifact, registry = build_artifact(tmp_path)
    success = ReplayEngine(FakeSurface(), JsonLogger(tmp_path / "success.jsonl"), tmp_path).run(artifact, registry, {"member_id": "10002"})
    assert success.kind == OutcomeKind.SUCCESS
    assert success.outputs == {"balance": 1200.0}
    not_found = ReplayEngine(FakeSurface(), JsonLogger(tmp_path / "not-found.jsonl"), tmp_path).run(artifact, registry, {"member_id": "40400"})
    assert not_found.kind == OutcomeKind.BUSINESS_OUTCOME
    assert not_found.code == "MEMBER_NOT_FOUND"
    recovered = ReplayEngine(FakeSurface(), JsonLogger(tmp_path / "recovered.jsonl"), tmp_path).run(artifact, registry, {"member_id": "40800"})
    assert recovered.kind == OutcomeKind.SUCCESS
    assert recovered.recovered_conditions == ["TRANSIENT_HOST_DELAY"]
    failure = ReplayEngine(FakeSurface(), JsonLogger(tmp_path / "failure.jsonl"), tmp_path).run(artifact, registry, {"member_id": "50000"})
    assert failure.kind == OutcomeKind.FAILURE
    assert failure.code == ErrorCode.APPLICATION_ERROR
    assert failure.expected is not None
    assert failure.observed is not None


def test_policy_blocks_domain_and_risk() -> None:
    """
    Verify policy enforcement is independent of discovery and replay decisions.

    Input Parameter:
        input_parameter(None): This test accepts no parameters.

    Output Parameter:
        output_parameter(None): Pytest asserts behavior directly.
    """
    policy = CapabilityPolicy(allowed_actions=[ActionKind.ACTIVATE], allowed_domains=["localhost"], allowed_route_prefixes=["/"], maximum_risk=RiskClass.SAFE)
    with pytest.raises(AutomationError) as domain_error:
        PolicyEngine().validate(policy, ActionKind.ACTIVATE, "https://evil.example/", RiskClass.SAFE)
    assert domain_error.value.code == ErrorCode.POLICY_DOMAIN_DENIED
    with pytest.raises(AutomationError) as risk_error:
        PolicyEngine().validate(policy, ActionKind.ACTIVATE, "http://localhost/", RiskClass.IRREVERSIBLE)
    assert risk_error.value.code == ErrorCode.POLICY_RISK_DENIED


def test_same_session_handoff_records_human_events(tmp_path: Path) -> None:
    """
    Verify ownership changes on one retained surface and returns to automation.

    Input Parameter:
        tmp_path(Path): Temporary test directory.

    Output Parameter:
        output_parameter(None): Pytest asserts behavior directly.
    """
    surface = FakeSurface()
    controller = SessionOwnershipController(surface, JsonLogger(tmp_path / "handoff.jsonl"))
    record = controller.handoff("capability", "step-2", "supervisor gate", Severity.HIGH, None, operator=lambda request: None)
    assert controller.owner.value == "automation"
    assert record.human_events[0]["id"] == "supervisorContinue"


def test_artifact_semantics_and_redaction(tmp_path: Path) -> None:
    """
    Verify semantic contract coverage and sensitive log redaction.

    Input Parameter:
        tmp_path(Path): Temporary test directory.

    Output Parameter:
        output_parameter(None): Pytest asserts behavior directly.
    """
    artifact, _ = build_artifact(tmp_path)
    assert offline_semantic_validator(artifact)
    logger = JsonLogger(tmp_path / "redaction.jsonl")
    logger.register_sensitive_values({"member_id": "12345"})
    logger.event("test", "INFO", "redact", member_id="12345", nested={"account_id": "999"})
    logger.event("test_message", "INFO", "look up member 12345")
    content = (tmp_path / "redaction.jsonl").read_text(encoding="utf-8")
    assert "12345" not in content and '"<redacted>"' in content
    assert "<redacted:member_id>" in content


def test_replay_source_has_no_model_dependency() -> None:
    """
    Verify the production replay module has no provider or OpenAI dependency.

    Input Parameter:
        input_parameter(None): This test accepts no parameters.

    Output Parameter:
        output_parameter(None): Pytest asserts the source boundary directly.
    """
    source = Path("src/legacy_cua/replay.py").read_text(encoding="utf-8").lower()
    assert "openai" not in source
    assert "discoveryprovider" not in source


def test_replay_rejects_registry_family_and_digest_drift(tmp_path: Path) -> None:
    """
    Replay must stop before acting when artifact and registry identity diverge.

    Input Parameter:
        tmp_path(Path): Temporary evidence directory.

    Output Parameter:
        output_parameter(None): Pytest asserts family and digest failures.
    """
    artifact, registry = build_artifact(tmp_path)
    surface = FakeSurface()
    family_drift = registry.model_copy(deep=True)
    family_drift.fingerprint.family = "other-application"
    family_result = ReplayEngine(surface, JsonLogger(tmp_path / "family.jsonl"), tmp_path).run(artifact, family_drift, {"member_id": "10001"})
    assert family_result.code == ErrorCode.REGISTRY_MISMATCH
    digest_drift = registry.model_copy(deep=True)
    digest_drift.fingerprint.digest = "different-digest"
    digest_result = ReplayEngine(surface, JsonLogger(tmp_path / "digest.jsonl"), tmp_path).run(artifact, digest_drift, {"member_id": "10001"})
    assert digest_result.code == ErrorCode.REGISTRY_MISMATCH


def test_replay_rejects_low_fingerprint_confidence(tmp_path: Path) -> None:
    """
    Replay must reject an application fingerprint below the confidence threshold.

    Input Parameter:
        tmp_path(Path): Temporary evidence directory.

    Output Parameter:
        output_parameter(None): Pytest asserts the confidence failure.
    """
    artifact, registry = build_artifact(tmp_path)
    registry.fingerprint.confidence = 0.5
    result = ReplayEngine(FakeSurface(), JsonLogger(tmp_path / "confidence.jsonl"), tmp_path).run(artifact, registry, {"member_id": "10001"})
    assert result.code == ErrorCode.FINGERPRINT_MISMATCH
    assert result.expected == ">=0.8"


def test_replay_returns_structured_input_and_inactive_failures(tmp_path: Path) -> None:
    """
    Malformed inputs and inactive capabilities remain structured results.

    Input Parameter:
        tmp_path(Path): Temporary evidence directory.

    Output Parameter:
        output_parameter(None): Pytest asserts structured request failures.
    """
    artifact, registry = build_artifact(tmp_path)
    engine = ReplayEngine(FakeSurface(), JsonLogger(tmp_path / "input.jsonl"), tmp_path)
    missing = engine.run(artifact, registry, {})
    malformed = engine.run(artifact, registry, {"member_id": "bad"})
    inactive = engine.run(artifact.model_copy(update={"status": CertificationStatus.DRAFT}), registry, {"member_id": "10001"})
    assert missing.code == ErrorCode.INPUT_INVALID
    assert malformed.code == ErrorCode.INPUT_INVALID
    assert inactive.code == ErrorCode.CAPABILITY_NOT_ACTIVE


def test_replay_maps_native_browser_errors_to_structured_failure(tmp_path: Path) -> None:
    """
    Unexpected surface failures must include step, screenshot, and retry context.

    Input Parameter:
        tmp_path(Path): Temporary evidence directory.

    Output Parameter:
        output_parameter(None): Pytest asserts structured runtime diagnostics.
    """
    artifact, registry = build_artifact(tmp_path)

    class BrokenSurface(FakeSurface):
        """
        Raise a native-style runtime failure from the surface action.

        Input Parameter:
            action(ActionKind): Requested surface action.
            control(object): Resolved control.
            value(str | None): Optional action value.

        Output Parameter:
            output_parameter(str | None): This implementation always raises.
        """

        def observe(self, screenshot_path: Path | None = None) -> SurfaceObservation:
            """
            Create a tangible screenshot marker before returning the fake observation.

            Input Parameter:
                screenshot_path(Path | None): Optional evidence destination.

            Output Parameter:
                output_parameter(SurfaceObservation): Simulated surface observation.
            """
            if screenshot_path:
                screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                screenshot_path.write_bytes(b"synthetic-test-image")
            return super().observe(screenshot_path)

        def act(self, action: ActionKind, control: object, value: str | None = None) -> str | None:
            """
            Raise a native-style runtime failure for every surface action.

            Input Parameter:
                action(ActionKind): Requested surface action.
                control(object): Resolved control.
                value(str | None): Optional action value.

            Output Parameter:
                output_parameter(str | None): This implementation always raises.
            """
            raise RuntimeError("native timeout")

    result = ReplayEngine(BrokenSurface(), JsonLogger(tmp_path / "native-error.jsonl"), tmp_path).run(artifact, registry, {"member_id": "10001"})
    assert result.code == ErrorCode.UNEXPECTED_EXCEPTION
    assert result.step_id == "step-1"
    assert result.expected is not None
    assert result.observed == "native timeout"
    assert result.evidence
    assert any(path.endswith("failure-step-1.png") for path in result.evidence)
    assert result.retry_info["retries"] == 1


def test_replay_boundary_keeps_human_click_out_of_source() -> None:
    """
    Verify production replay does not automate the human supervisor action.

    Input Parameter:
        input_parameter(None): This test accepts no parameters.

    Output Parameter:
        output_parameter(None): Pytest asserts the source boundary directly.
    """
    source = Path("src/legacy_cua/replay.py").read_text(encoding="utf-8").lower()
    assert 'page.click("#supervisorcontinue")' not in source


def test_human_event_metadata_excludes_page_text() -> None:
    """
    Verify browser human-event capture uses metadata-only fields.

    Input Parameter:
        input_parameter(None): This test accepts no parameters.

    Output Parameter:
        output_parameter(None): Pytest asserts sensitive DOM text is not captured.
    """
    source = Path("src/legacy_cua/surface.py").read_text(encoding="utf-8")
    assert "innerText" not in source[source.index("__cuaHumanEvents"):source.index("def close")]
    assert "e.target.value" not in source[source.index("__cuaHumanEvents"):source.index("def close")]


def test_discovery_rejects_invalid_model_control(tmp_path: Path) -> None:
    """
    Verify an invalid model-selected control is rejected without repair.

    Input Parameter:
        tmp_path(Path): Temporary evidence directory.

    Output Parameter:
        output_parameter(None): Pytest asserts the model response error.
    """
    class InvalidProvider:
        """
        Return a deliberately invalid model decision for safety testing.

        Input Parameter:
            goal(str): Natural-language discovery goal.
            observation(object): Current surface observation.
            history(list[DiscoveryDecision]): Prior model decisions.

        Output Parameter:
            output_parameter(DiscoveryDecision): Invalid decision used by the test.
        """

        def decide(self, goal: str, observation: object, history: list[DiscoveryDecision]) -> DiscoveryDecision:
            """
            Return a deliberately unobserved control identifier.

            Input Parameter:
                goal(str): Natural-language discovery goal.
                observation(object): Current surface observation.
                history(list[DiscoveryDecision]): Prior model decisions.

            Output Parameter:
                output_parameter(DiscoveryDecision): Invalid decision used by the test.
            """
            return DiscoveryDecision(action=ActionKind.INPUT, observed_id="not-observed", semantic_name="bad", input_name="member_id", reason="invalid")

    with pytest.raises(AutomationError) as error:
        DiscoveryEngine(FakeSurface(), InvalidProvider(), JsonLogger(tmp_path / "invalid-model.jsonl"), tmp_path).run("find balance", {"member_id": "10001"})
    assert error.value.code == ErrorCode.MODEL_RESPONSE_INVALID


def test_discovery_enforces_elapsed_timeout(tmp_path: Path) -> None:
    """
    Verify discovery stops on an elapsed-time budget.

    Input Parameter:
        tmp_path(Path): Temporary evidence directory.

    Output Parameter:
        output_parameter(None): Pytest asserts the timeout error code.
    """
    with pytest.raises(AutomationError) as error:
        DiscoveryEngine(FakeSurface(), OfflineSemanticFixtureProvider(), JsonLogger(tmp_path / "timeout.jsonl"), tmp_path).run("find balance", {"member_id": "10001"}, timeout_seconds=0)
    assert error.value.code == ErrorCode.DISCOVERY_TIMEOUT


def test_certification_rejects_missing_registry_control(tmp_path: Path) -> None:
    """
    Verify structural certification checks artifact references against the registry.

    Input Parameter:
        tmp_path(Path): Temporary evidence directory.

    Output Parameter:
        output_parameter(None): Pytest asserts certification rejects the broken reference.
    """
    artifact, registry = build_artifact(tmp_path)
    artifact.status = CertificationStatus.DRAFT
    artifact.steps[0].control = "missing-control"
    success = ExecutionResult(kind=OutcomeKind.SUCCESS, code="TEST", message="test gate")
    with pytest.raises(AutomationError) as error:
        CapabilityCertifier().certify(artifact, registry, offline_semantic_validator, lambda: success, lambda: success)
    assert error.value.code == ErrorCode.CERTIFICATION_FAILED


def test_invalid_resume_state_is_redacted(tmp_path: Path) -> None:
    """
    Verify failed handoff validation never returns or logs full visible page text.

    Input Parameter:
        tmp_path(Path): Temporary evidence directory.

    Output Parameter:
        output_parameter(None): Pytest asserts only a safe state summary is persisted.
    """
    artifact, registry = build_artifact(tmp_path)
    surface = FakeSurface()
    surface.text = "Supervisor verification for member 12345 with balance $8,765.43"
    logger = JsonLogger(tmp_path / "resume-invalid.jsonl")
    engine = ReplayEngine(surface, logger, tmp_path)
    engine.ownership.handoff = lambda *args, **kwargs: InterventionRequest(request_id="test", capability_id=artifact.capability_id, step_id="step-3", reason="test", severity=Severity.HIGH)
    result = engine._classify_exception(artifact, registry, surface.text, "step-3", str(tmp_path / "blocked.png"))
    assert result is not None
    assert result.code == ErrorCode.RESUME_STATE_INVALID
    assert result.observed == "matched:supervisor_verification"
    persisted = (tmp_path / "resume-invalid.jsonl").read_text(encoding="utf-8")
    assert "12345" not in persisted
    assert "$8,765.43" not in persisted
