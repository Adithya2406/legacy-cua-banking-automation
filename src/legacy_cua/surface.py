"""Surface abstraction and Playwright implementation."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .errors import AutomationError, ErrorCode
from .schemas import ActionKind, Control, Locator, ObservedControl, SurfaceObservation


class SurfaceDriver(ABC):
    """Separate capability semantics from browser or desktop mechanics."""

    @abstractmethod
    def observe(self, screenshot_path: Path | None = None) -> SurfaceObservation:
        """
        Observe the current surface as compressed semantic metadata.

        Input Parameter:
            screenshot_path(Path | None): Optional screenshot destination.

        Output Parameter:
            output_parameter(SurfaceObservation): Current surface observation.
        """
        raise NotImplementedError

    @abstractmethod
    def act(self, action: ActionKind, control: Control, value: str | None = None) -> str | None:
        """
        Execute one surface-neutral action on a resolved control.

        Input Parameter:
            action(ActionKind): Action primitive to execute.
            control(Control): Registry control to target.
            value(str | None): Optional input value.

        Output Parameter:
            output_parameter(str | None): Extracted value when applicable.
        """
        raise NotImplementedError

    @abstractmethod
    def current_url(self) -> str:
        """
        Return the current surface URL or desktop location.

        Input Parameter:
            input_parameter(None): This function accepts no parameters.

        Output Parameter:
            output_parameter(str): Current surface location.
        """
        raise NotImplementedError

    @abstractmethod
    def human_events(self) -> list[dict[str, Any]]:
        """
        Return human interaction events recorded in the live session.

        Input Parameter:
            input_parameter(None): This function accepts no parameters.

        Output Parameter:
            output_parameter(list[dict[str, Any]]): Recorded human events.
        """
        raise NotImplementedError


class PlaywrightSurfaceDriver(SurfaceDriver):
    """Drive a browser while preserving one context across handoff."""

    def __init__(self, url: str, headed: bool = False) -> None:
        """
        Launch a Chromium session and navigate to the target.

        Input Parameter:
            url(str): Initial application URL.
            headed(bool): Whether the browser is visible for human takeover.

        Output Parameter:
            output_parameter(None): This initializer returns no value.
        """
        from playwright.sync_api import sync_playwright

        self.headed = headed
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=not headed)
        self._context = self._browser.new_context()
        self._context.add_init_script("""
            window.__cuaHumanEvents = [];
            for (const type of ['click','input','change']) {
              document.addEventListener(type, e => {
                if (window.__cuaOwner === 'human') window.__cuaHumanEvents.push({
                  type, tag: e.target.tagName, id: e.target.id || null,
                  name: e.target.getAttribute('aria-label') || e.target.innerText || e.target.value || ''
                });
              }, true);
            }
        """)
        self.page = self._context.new_page()
        self.page.goto(url)
        self.page.wait_for_load_state("domcontentloaded")

    def close(self) -> None:
        """
        Close browser resources owned by this driver.

        Input Parameter:
            input_parameter(None): This function accepts no parameters.

        Output Parameter:
            output_parameter(None): This function returns no value.
        """
        self._browser.close()
        self._playwright.stop()

    def set_owner(self, owner: str) -> None:
        """
        Expose current ownership inside the same browser page.

        Input Parameter:
            owner(str): New owner name.

        Output Parameter:
            output_parameter(None): This function returns no value.
        """
        self.page.evaluate("owner => window.__cuaOwner = owner", owner)

    def observe(self, screenshot_path: Path | None = None) -> SurfaceObservation:
        """
        Observe visible controls, text, URL, title, and screenshot.

        Input Parameter:
            screenshot_path(Path | None): Optional screenshot destination.

        Output Parameter:
            output_parameter(SurfaceObservation): Compressed live observation.
        """
        controls = self.page.locator("input, button, select, textarea, a, [role], [data-output]").evaluate_all("""
          els => els.filter(e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)).map(e => {
            const label = e.labels && e.labels[0] ? e.labels[0].innerText.trim() : null;
            const role = e.getAttribute('role') || ({INPUT:'textbox',BUTTON:'button',A:'link',SELECT:'combobox'}[e.tagName] || e.tagName.toLowerCase());
            const name = e.getAttribute('aria-label') || label || e.innerText.trim() || e.getAttribute('placeholder') || e.name || e.id;
            return {observed_id:e.id || e.name || `${e.tagName.toLowerCase()}-${Array.from(document.querySelectorAll(e.tagName)).indexOf(e)}`, role, name, label, text:e.innerText || e.value || '', visible:true};
          })
        """)
        if screenshot_path:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(screenshot_path), full_page=True)
        return SurfaceObservation(
            url=self.page.url,
            title=self.page.title(),
            controls=[ObservedControl.model_validate(item) for item in controls],
            visible_text=self.page.locator("body").inner_text(),
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )

    def _resolve(self, control: Control) -> Any:
        """
        Resolve a registry control by ranked deterministic locator signals.

        Input Parameter:
            control(Control): Registry control containing ranked locator signals.

        Output Parameter:
            output_parameter(Any): Unique Playwright locator.
        """
        candidates: list[tuple[int, Any]] = []
        for locator in control.locators:
            if locator.strategy == "accessible" and locator.role:
                candidate = self.page.get_by_role(locator.role, name=locator.value, exact=True)
            elif locator.strategy == "label":
                candidate = self.page.get_by_label(locator.value, exact=True)
            elif locator.strategy == "dom_id":
                candidate = self.page.locator(f"#{locator.value}")
            elif locator.strategy == "text":
                candidate = self.page.get_by_text(locator.value, exact=True)
            else:
                continue
            count = candidate.count()
            if count == 1:
                candidates.append((locator.weight, candidate))
            elif count > 1 and locator.weight >= 80:
                raise AutomationError(ErrorCode.TARGET_AMBIGUOUS, f"ambiguous control: {control.semantic_name}")
        if not candidates:
            raise AutomationError(ErrorCode.TARGET_NOT_FOUND, f"control not found: {control.semantic_name}")
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def act(self, action: ActionKind, control: Control, value: str | None = None) -> str | None:
        """
        Execute an action using deterministic control resolution.

        Input Parameter:
            action(ActionKind): Action primitive to execute.
            control(Control): Registry control to target.
            value(str | None): Optional input value.

        Output Parameter:
            output_parameter(str | None): Extracted text or value when requested.
        """
        target = self._resolve(control)
        if action == ActionKind.INPUT:
            target.fill(value or "")
        elif action == ActionKind.ACTIVATE:
            target.click()
        elif action == ActionKind.EXTRACT:
            return target.inner_text().strip() or target.input_value()
        elif action == ActionKind.WAIT:
            target.wait_for(state="visible")
        else:
            raise AutomationError(ErrorCode.APPLICATION_ERROR, f"unsupported action: {action}")
        return None

    def current_url(self) -> str:
        """
        Return the current page URL.

        Input Parameter:
            input_parameter(None): This function accepts no parameters.

        Output Parameter:
            output_parameter(str): Current page URL.
        """
        return self.page.url

    def human_events(self) -> list[dict[str, Any]]:
        """
        Return interaction events captured while ownership was human.

        Input Parameter:
            input_parameter(None): This function accepts no parameters.

        Output Parameter:
            output_parameter(list[dict[str, Any]]): Human interaction events.
        """
        return self.page.evaluate("() => window.__cuaHumanEvents || []")


def control_from_observation(observed: ObservedControl, semantic_name: str) -> Control:
    """
    Build a registry control from identifiers actually observed in the app.

    Input Parameter:
        observed(ObservedControl): Live observed control metadata.
        semantic_name(str): Model-assigned semantic role.

    Output Parameter:
        output_parameter(Control): Persistable control with ranked locators.
    """
    locators = [Locator(strategy="accessible", role=observed.role, value=observed.name, weight=100)]
    if observed.label:
        locators.append(Locator(strategy="label", value=observed.label, weight=95))
    locators.append(Locator(strategy="dom_id", value=observed.observed_id, weight=60))
    return Control(control_id=observed.observed_id, semantic_name=semantic_name, observed_name=observed.name, role=observed.role, locators=locators)


def fingerprint_digest(parts: list[str]) -> str:
    """
    Produce a stable application fingerprint digest.

    Input Parameter:
        parts(list[str]): Ordered fingerprint evidence values.

    Output Parameter:
        output_parameter(str): Short SHA-256 digest.
    """
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
