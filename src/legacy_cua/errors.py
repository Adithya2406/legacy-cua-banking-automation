"""Typed errors and stable error codes."""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Enumerate stable machine-readable error codes."""

    DISCOVERY_MAX_STEPS = "CUA-DISC-001"
    DISCOVERY_DEAD_END = "CUA-DISC-002"
    MODEL_RESPONSE_INVALID = "CUA-DISC-003"
    POLICY_DOMAIN_DENIED = "CUA-POL-001"
    POLICY_ROUTE_DENIED = "CUA-POL-002"
    POLICY_ACTION_DENIED = "CUA-POL-003"
    POLICY_RISK_DENIED = "CUA-POL-004"
    TARGET_NOT_FOUND = "CUA-RPL-001"
    TARGET_AMBIGUOUS = "CUA-RPL-002"
    CHECKPOINT_FAILED = "CUA-RPL-003"
    APPLICATION_ERROR = "CUA-RPL-004"
    SESSION_EXPIRED = "CUA-RPL-005"
    INPUT_INVALID = "CUA-RPL-006"
    CAPABILITY_NOT_ACTIVE = "CUA-CERT-001"
    CERTIFICATION_FAILED = "CUA-CERT-002"
    INTERVENTION_REQUIRED = "CUA-HITL-001"
    RESUME_STATE_INVALID = "CUA-HITL-002"


class AutomationError(RuntimeError):
    """Represent a coded automation failure with optional step context."""

    def __init__(self, code: ErrorCode, message: str, step_id: str | None = None) -> None:
        """
        Initialize a coded automation error.

        Input Parameter:
            code(ErrorCode): Stable error code for the failure.
            message(str): Human-readable failure description.
            step_id(str | None): Optional capability step identifier.

        Output Parameter:
            output_parameter(None): This initializer returns no value.
        """
        super().__init__(message)
        self.code = code
        self.step_id = step_id
