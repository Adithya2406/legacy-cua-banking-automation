"""In-memory surface used by load-bearing deterministic tests."""

from pathlib import Path
from typing import Any

from legacy_cua.errors import AutomationError, ErrorCode
from legacy_cua.schemas import ActionKind, Control, ObservedControl, SurfaceObservation
from legacy_cua.surface import SurfaceDriver


class FakeSurface(SurfaceDriver):
    """Model the banking UI without browser dependencies."""

    def __init__(self, member_outcomes: dict[str, str] | None = None) -> None:
        """
        Initialize predictable member outcomes.

        Input Parameter:
            member_outcomes(dict[str, str] | None): Mapping from synthetic member IDs to outcomes.

        Output Parameter:
            output_parameter(None): This initializer returns no value.
        """
        self.member_outcomes = member_outcomes or {"10001": "$17,482.91", "10002": "$1,200.00"}
        self.value = ""
        self.text = ""
        self.output = ""
        self.owner = "automation"
        self.attempts = 0

    def observe(self, screenshot_path: Path | None = None) -> SurfaceObservation:
        """
        Return the current simulated observation.

        Input Parameter:
            screenshot_path(Path | None): Optional evidence path.

        Output Parameter:
            output_parameter(SurfaceObservation): Simulated surface observation.
        """
        controls = [
            ObservedControl(observed_id="custRefEntry", role="textbox", name="Customer Reference", label="Customer Reference", text=self.value),
            ObservedControl(observed_id="inquiryGo", role="button", name="Execute Inquiry"),
        ]
        if self.output:
            controls.append(ObservedControl(observed_id="availAmt", role="status", name="Available Amount", text=self.output))
        return SurfaceObservation(url="http://localhost/", title="Heritage Core", controls=controls, visible_text=self.text or self.output, screenshot_path=str(screenshot_path) if screenshot_path else None)

    def act(self, action: ActionKind, control: Control, value: str | None = None) -> str | None:
        """
        Execute a simulated surface action.

        Input Parameter:
            action(ActionKind): Action primitive.
            control(Control): Target registry control.
            value(str | None): Optional input value.

        Output Parameter:
            output_parameter(str | None): Simulated extracted value.
        """
        if control.control_id == "missing":
            raise AutomationError(ErrorCode.TARGET_NOT_FOUND, "control missing")
        if action == ActionKind.INPUT:
            self.value = value or ""
        elif action == ActionKind.ACTIVATE:
            self.attempts += 1
            if self.value == "40400":
                self.text = "No matching customer record"
            elif self.value == "50000":
                self.text = "Host system unavailable"
            elif self.value == "40800" and self.attempts == 1:
                self.text = "Temporary host delay - retry inquiry"
            else:
                self.text = ""
                self.output = self.member_outcomes.get(self.value, "$9.99")
        elif action == ActionKind.EXTRACT:
            return self.value if control.control_id == "custRefEntry" else self.output
        return None

    def current_url(self) -> str:
        """
        Return the simulated URL.

        Input Parameter:
            input_parameter(None): This function accepts no parameters.

        Output Parameter:
            output_parameter(str): Simulated URL.
        """
        return "http://localhost/"

    def human_events(self) -> list[dict[str, Any]]:
        """
        Return simulated human events.

        Input Parameter:
            input_parameter(None): This function accepts no parameters.

        Output Parameter:
            output_parameter(list[dict[str, Any]]): Simulated human event list.
        """
        return [{"type": "click", "id": "supervisorContinue"}]

    def set_owner(self, owner: str) -> None:
        """
        Set simulated live-session ownership.

        Input Parameter:
            owner(str): New owner value.

        Output Parameter:
            output_parameter(None): This function returns no value.
        """
        self.owner = owner
