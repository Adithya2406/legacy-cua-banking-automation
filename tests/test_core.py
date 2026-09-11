"""Load-bearing contract, safety, compiler, replay, and handoff tests."""

from pathlib import Path

import pytest

from legacy_cua.certification import offline_semantic_validator
from legacy_cua.compiler import CapabilityCompiler
from legacy_cua.errors import AutomationError, ErrorCode
from legacy_cua.handoff import SessionOwnershipController
from legacy_cua.logging import JsonLogger
from legacy_cua.policy import PolicyEngine
from legacy_cua.providers import OfflineSemanticFixtureProvider
from legacy_cua.replay import ReplayEngine
from legacy_cua.schemas import ActionKind, ApplicationRegistry, CapabilityArtifact, CapabilityPolicy, CertificationStatus, OutcomeKind, RiskClass, Severity
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
    assert 'page.click("#supervisorcontinue")' not in source
