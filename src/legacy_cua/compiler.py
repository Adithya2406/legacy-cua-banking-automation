"""Compile successful discovery traces into reusable capabilities."""

from .schemas import (
    ActionKind,
    ApplicationRegistry,
    CapabilityArtifact,
    CapabilityPolicy,
    CapabilityStep,
    Checkpoint,
    DiscoveryTraceEntry,
    ExceptionRule,
    ParameterSpec,
    RiskClass,
    Severity,
    ValueReference,
)


class CapabilityCompiler:
    """Compile a successful trace without retaining model conversation or real inputs."""

    def compile(self, trace: list[DiscoveryTraceEntry], registry: ApplicationRegistry) -> CapabilityArtifact:
        """
        Convert trace decisions into parameterized deterministic steps.

        Input Parameter:
            trace(list[DiscoveryTraceEntry]): Successful constrained discovery trace.
            registry(ApplicationRegistry): Discovered version-specific control registry.

        Output Parameter:
            output_parameter(CapabilityArtifact): Draft capability artifact.
        """
        steps: list[CapabilityStep] = []
        for entry in trace:
            decision = entry.decision
            value = ValueReference(input_name=decision.input_name) if decision.input_name else None
            checkpoints = []
            if decision.action == ActionKind.INPUT:
                checkpoints.append(Checkpoint(checkpoint_id="member-input-matches", level="action", assertion="control_value_equals", control=decision.semantic_name, expected=value))
            if decision.action == ActionKind.EXTRACT:
                checkpoints.append(Checkpoint(checkpoint_id="balance-is-money", level="goal", assertion="money", control=decision.semantic_name))
            steps.append(CapabilityStep(step_id=f"step-{entry.sequence}", action=decision.action, control=decision.semantic_name, value=value, output_name=decision.output_name, risk=RiskClass.SAFE, checkpoints=checkpoints))
        policy = CapabilityPolicy(allowed_actions=[ActionKind.INPUT, ActionKind.ACTIVATE, ActionKind.EXTRACT, ActionKind.WAIT], allowed_domains=["127.0.0.1", "localhost"], allowed_route_prefixes=["/"], maximum_risk=RiskClass.SAFE)
        return CapabilityArtifact(
            capability_id="legacybank.get-savings-balance",
            version="1.0.0",
            name="Get Savings Balance",
            description="Look up a member and return the current Savings balance.",
            application_family=registry.fingerprint.family,
            registry_digest=registry.fingerprint.digest,
            inputs={"member_id": ParameterSpec(data_type="string", sensitive=True, description="Synthetic member identifier.", pattern=r"^[0-9]{5}$")},
            outputs={"balance": ParameterSpec(data_type="money", description="Current savings balance in USD.")},
            steps=steps,
            exception_rules=[
                ExceptionRule(rule_id="member-not-found", contains_text="No matching customer record", outcome="business_outcome", code="MEMBER_NOT_FOUND"),
                ExceptionRule(rule_id="transient-host-delay", contains_text="Temporary host delay", outcome="recoverable", code="TRANSIENT_HOST_DELAY"),
                ExceptionRule(rule_id="application-error", contains_text="Host system unavailable", outcome="failure", code="CUA-RPL-004", severity=Severity.MEDIUM),
                ExceptionRule(rule_id="supervisor-dialog", contains_text="Supervisor verification", outcome="intervention", code="CUA-HITL-001", severity=Severity.HIGH),
            ],
            policy=policy,
        )
