"""Deterministic policy enforcement outside the model boundary."""

from urllib.parse import urlparse

from .errors import AutomationError, ErrorCode
from .schemas import ActionKind, CapabilityPolicy, RiskClass


class PolicyEngine:
    """Validate every proposed or replayed action against an allowlist."""

    _risk_order = {RiskClass.SAFE: 0, RiskClass.REVERSIBLE: 1, RiskClass.IRREVERSIBLE: 2}

    def validate(self, policy: CapabilityPolicy, action: ActionKind, url: str, risk: RiskClass) -> None:
        """
        Reject navigation, actions, or risk outside the configured policy.

        Input Parameter:
            policy(CapabilityPolicy): Capability policy envelope.
            action(ActionKind): Proposed action type.
            url(str): Current target URL.
            risk(RiskClass): Risk classification for the action.

        Output Parameter:
            output_parameter(None): This function returns no value when allowed.
        """
        parsed = urlparse(url)
        if parsed.hostname not in policy.allowed_domains:
            raise AutomationError(ErrorCode.POLICY_DOMAIN_DENIED, f"domain denied: {parsed.hostname}")
        if not any(parsed.path.startswith(prefix) for prefix in policy.allowed_route_prefixes):
            raise AutomationError(ErrorCode.POLICY_ROUTE_DENIED, f"route denied: {parsed.path}")
        if action not in policy.allowed_actions:
            raise AutomationError(ErrorCode.POLICY_ACTION_DENIED, f"action denied: {action}")
        if self._risk_order[risk] > self._risk_order[policy.maximum_risk]:
            raise AutomationError(ErrorCode.POLICY_RISK_DENIED, f"risk denied: {risk}")
