"""LLM-driven observe-decide-act discovery loop."""

from pathlib import Path
from urllib.parse import urlparse

from .errors import AutomationError, ErrorCode
from .handoff import SessionOwnershipController
from .logging import JsonLogger
from .policy import PolicyEngine
from .providers import DiscoveryProvider
from .schemas import (
    ActionKind,
    ApplicationFingerprint,
    ApplicationRegistry,
    CapabilityPolicy,
    DiscoveryDecision,
    DiscoveryTraceEntry,
    RiskClass,
    Severity,
)
from .surface import SurfaceDriver, control_from_observation, fingerprint_digest


class DiscoveryEngine:
    """Run constrained model discovery and build observed control knowledge."""

    def __init__(self, surface: SurfaceDriver, provider: DiscoveryProvider, logger: JsonLogger, evidence_dir: Path) -> None:
        """
        Initialize the discovery engine.

        Input Parameter:
            surface(SurfaceDriver): Live application surface.
            provider(DiscoveryProvider): Discovery-only reasoning provider.
            logger(JsonLogger): Structured audit logger.
            evidence_dir(Path): Screenshot evidence directory.

        Output Parameter:
            output_parameter(None): This initializer returns no value.
        """
        self.surface = surface
        self.provider = provider
        self.logger = logger
        self.evidence_dir = evidence_dir
        self.policy_engine = PolicyEngine()
        self.ownership = SessionOwnershipController(surface, logger)

    def run(self, goal: str, input_values: dict[str, str], max_steps: int = 8) -> tuple[list[DiscoveryTraceEntry], ApplicationRegistry]:
        """
        Discover a goal-driven flow and emit a version-specific registry.

        Input Parameter:
            goal(str): Natural-language goal.
            input_values(dict[str, str]): Ephemeral invocation data excluded from artifacts and logs.
            max_steps(int): Maximum model decisions before stopping.

        Output Parameter:
            output_parameter(tuple[list[DiscoveryTraceEntry], ApplicationRegistry]): Discovery trace and observed registry.
        """
        trace: list[DiscoveryTraceEntry] = []
        decisions: list[DiscoveryDecision] = []
        registry_controls = {}
        self.logger.register_sensitive_values(input_values)
        self.logger.event("discovery_started", "CUA-INFO-000", "semantic discovery started", provider=self.provider.__class__.__name__, model=getattr(self.provider, "model", None))
        policy = CapabilityPolicy(allowed_actions=list(ActionKind), allowed_domains=[urlparse(self.surface.current_url()).hostname or "localhost"], allowed_route_prefixes=["/"], maximum_risk=RiskClass.SAFE)
        for sequence in range(1, max_steps + 1):
            observation = self.surface.observe(self.evidence_dir / f"discovery-step-{sequence}.png")
            decision = self.provider.decide(goal, observation, decisions)
            self.policy_engine.validate(policy, decision.action, observation.url, RiskClass.SAFE)
            observed = next((item for item in observation.controls if item.observed_id == decision.observed_id), None)
            if observed is None:
                if getattr(self.surface, "headed", False):
                    self.ownership.handoff("discovery-candidate", f"decision-{sequence}", "model selected an unobserved control", Severity.LOW, observation.screenshot_path)
                raise AutomationError(ErrorCode.MODEL_RESPONSE_INVALID, "model selected an unobserved control")
            control = control_from_observation(observed, decision.semantic_name)
            registry_controls[decision.semantic_name] = control
            value = input_values.get(decision.input_name or "")
            self.logger.event("discovery_decision", "CUA-INFO-001", decision.reason, sequence=sequence, action=decision.action, observed_id=decision.observed_id, input_name=decision.input_name, provider_metadata=getattr(self.provider, "last_call_metadata", {}))
            self.surface.act(decision.action, control, value)
            trace.append(DiscoveryTraceEntry(sequence=sequence, decision=decision, observation=observation))
            decisions.append(decision)
            if decision.goal_complete:
                first = trace[0].observation
                digest = fingerprint_digest([first.title, urlparse(first.url).path, *sorted(item.observed_id for item in first.controls)])
                fingerprint = ApplicationFingerprint(family="legacybank-servicing", version="1.0", tenant="demo-credit-union", title=first.title, route_pattern="/*", landmarks=[item.name for item in first.controls[:4]], digest=digest)
                self.logger.event("discovery_completed", "CUA-INFO-002", "goal completed and registry compiled", step_count=len(trace), registry_digest=digest)
                return trace, ApplicationRegistry(fingerprint=fingerprint, controls=registry_controls)
        final_observation = self.surface.observe(self.evidence_dir / "discovery-stuck.png")
        if getattr(self.surface, "headed", False):
            self.ownership.handoff("discovery-candidate", f"decision-{max_steps}", "discovery exceeded maximum steps", Severity.LOW, final_observation.screenshot_path)
        raise AutomationError(ErrorCode.DISCOVERY_MAX_STEPS, "discovery exceeded maximum steps")
