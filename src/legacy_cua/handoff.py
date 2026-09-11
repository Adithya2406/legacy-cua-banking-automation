"""Same-session pause, ownership transfer, and resume control."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable

from .logging import JsonLogger
from .schemas import InterventionRequest, Owner, Severity
from .surface import SurfaceDriver


class SessionOwnershipController:
    """Coordinate exclusive ownership without replacing the live session."""

    def __init__(self, surface: SurfaceDriver, logger: JsonLogger) -> None:
        """
        Initialize automation as the owner of the existing surface.

        Input Parameter:
            surface(SurfaceDriver): Existing live surface retained through handoff.
            logger(JsonLogger): Structured audit logger.

        Output Parameter:
            output_parameter(None): This initializer returns no value.
        """
        self.surface = surface
        self.logger = logger
        self.owner = Owner.AUTOMATION
        self._resume = threading.Event()
        if hasattr(surface, "set_owner"):
            surface.set_owner(Owner.AUTOMATION.value)

    def handoff(self, capability_id: str, step_id: str, reason: str, severity: Severity, screenshot_path: str | None, operator: Callable[[InterventionRequest], None] | None = None) -> InterventionRequest:
        """
        Pause automation, cede the same session, then resume after an explicit signal.

        Input Parameter:
            capability_id(str): Active capability identifier.
            step_id(str): Paused step identifier.
            reason(str): Reason human judgment is required.
            severity(Severity): Deterministically assigned intervention severity.
            screenshot_path(str | None): Current-state screenshot evidence.
            operator(Callable[[InterventionRequest], None] | None): Optional test or operator callback.

        Output Parameter:
            output_parameter(InterventionRequest): Completed intervention record including human events.
        """
        request = InterventionRequest(request_id=str(uuid.uuid4()), capability_id=capability_id, step_id=step_id, reason=reason, severity=severity, screenshot_path=screenshot_path)
        self.owner = Owner.HUMAN
        if hasattr(self.surface, "set_owner"):
            self.surface.set_owner(Owner.HUMAN.value)
        self.logger.event(
            "handoff_started",
            "CUA-HITL-001",
            reason,
            request_id=request.request_id,
            capability_id=capability_id,
            severity=severity,
            step_id=step_id,
            screenshot_path=screenshot_path,
            ownership_transition=[Owner.AUTOMATION.value, Owner.HUMAN.value],
        )
        if operator:
            operator(request)
        else:
            input("Automation paused in the visible browser. Resolve the issue, then press Enter to resume: ")
        self._resume.set()
        self.owner = Owner.AUTOMATION
        if hasattr(self.surface, "set_owner"):
            self.surface.set_owner(Owner.AUTOMATION.value)
        request.owner = Owner.AUTOMATION
        request.human_events = self.surface.human_events()
        self.logger.event(
            "handoff_completed",
            "CUA-INFO-020",
            "human returned control",
            request_id=request.request_id,
            capability_id=capability_id,
            step_id=step_id,
            severity=severity,
            ownership_transition=[Owner.AUTOMATION.value, Owner.HUMAN.value, Owner.AUTOMATION.value],
            human_events=self.surface.human_events(),
            human_event_count=len(request.human_events),
            screenshot_path=screenshot_path,
        )
        return request
