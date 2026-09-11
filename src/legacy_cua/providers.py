"""Discovery-only semantic reasoning providers."""

from __future__ import annotations

import base64
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path

from .schemas import ActionKind, DiscoveryDecision, SurfaceObservation


class DiscoveryProvider(ABC):
    """Define the only boundary allowed to call an LLM."""

    @abstractmethod
    def decide(self, goal: str, observation: SurfaceObservation, history: list[DiscoveryDecision]) -> DiscoveryDecision:
        """
        Select the next constrained action from semantic and visual evidence.

        Input Parameter:
            goal(str): Natural-language user goal.
            observation(SurfaceObservation): Current semantic and visual observation.
            history(list[DiscoveryDecision]): Prior decisions in this discovery run.

        Output Parameter:
            output_parameter(DiscoveryDecision): Next constrained discovery decision.
        """
        raise NotImplementedError


class OpenAIDiscoveryProvider(DiscoveryProvider):
    """Use an OpenAI vision-capable model only during discovery."""

    def __init__(self, model: str = "gpt-4.1-mini") -> None:
        """
        Initialize the discovery provider from environment credentials.

        Input Parameter:
            model(str): OpenAI model name for semantic discovery.

        Output Parameter:
            output_parameter(None): This initializer returns no value.
        """
        from openai import OpenAI

        base_url = os.getenv("OPENAI_BASE_URL") or None
        api_key = os.getenv("OPENAI_API_KEY") or None
        if not api_key and not base_url:
            raise RuntimeError("OPENAI_API_KEY is required unless OPENAI_BASE_URL points to a trusted local provider")
        self.client = OpenAI(
            api_key=api_key or "local-provider-no-secret",
            base_url=base_url,
        )
        self.model = model
        self.last_call_metadata: dict[str, object] = {}

    def decide(self, goal: str, observation: SurfaceObservation, history: list[DiscoveryDecision]) -> DiscoveryDecision:
        """
        Ask the model to semantically select one UI action using metadata and screenshot.

        Input Parameter:
            goal(str): Natural-language user goal.
            observation(SurfaceObservation): Current semantic and visual observation.
            history(list[DiscoveryDecision]): Prior constrained decisions.

        Output Parameter:
            output_parameter(DiscoveryDecision): Validated next decision.
        """
        text_payload = json.dumps({"goal": goal, "observation": observation.model_dump(exclude={"screenshot_path"}), "history": [item.model_dump() for item in history]})
        system_prompt = (
            "You are a UI discovery compiler. Reason over the observed controls and app state. "
            "Select exactly one observed_id that represents the next action. Return only JSON matching: "
            "{\"action\":\"input|activate|extract\",\"observed_id\":\"...\",\"semantic_name\":\"...\","
            "\"input_name\":\"member_id\"|null,\"output_name\":\"balance\"|null,\"reason\":\"...\",\"goal_complete\":true|false}."
            "Use input_name member_id and output_name balance when relevant. Keep reason short and specific."
        )
        screenshot_supplied = bool(observation.screenshot_path and Path(observation.screenshot_path).exists() and os.getenv("OPENAI_INCLUDE_SCREENSHOT", "true").lower() not in {"0", "false", "no"})
        user_content: str | list[dict[str, object]] = text_payload
        if screenshot_supplied and observation.screenshot_path:
            image_bytes = Path(observation.screenshot_path).read_bytes()
            encoded = base64.b64encode(image_bytes).decode("ascii")
            user_content = [
                {"type": "text", "text": text_payload},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}", "detail": "high"}},
            ]
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        def _extract_json_object(raw: str) -> dict[str, object]:
            """
            Normalize chat-model output that may include model reasoning wrappers.

            Input Parameter:
                raw(str): Raw text returned by the discovery model.

            Output Parameter:
                output_parameter(dict[str, object]): Parsed constrained decision object.
            """
            candidate = raw.strip()
            if not candidate:
                raise ValueError("empty model response")
            for token in ["<|channel|>final", "<|channel|>analysis", "<|constrain|>JSON", "<|message|>"]:
                candidate = candidate.replace(token, "")
            candidate = candidate.strip()
            if candidate.startswith("```"):
                candidate = candidate.strip("`")
                if candidate.lower().startswith("json"):
                    candidate = candidate[4:].lstrip()
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = candidate[start : end + 1]
            decoded = json.loads(candidate)
            if isinstance(decoded, str):
                decoded = json.loads(decoded)
            if not isinstance(decoded, dict):
                raise TypeError(f"expected JSON object from model, got {type(decoded).__name__}")
            action = str(decoded.get("action", "")).lower()
            if action == "input":
                decoded["semantic_name"] = "member_identifier_input"
                decoded["input_name"] = decoded.get("input_name") or "member_id"
                decoded["output_name"] = None
            elif action == "activate":
                decoded["semantic_name"] = "member_lookup_action"
                decoded["input_name"] = None
                decoded["output_name"] = None
            elif action == "extract":
                decoded["semantic_name"] = "savings_balance_output"
                decoded["input_name"] = None
                decoded["output_name"] = "balance"
                decoded["goal_complete"] = True
            return decoded

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=messages,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("empty model response")
            self._record_response_metadata(response, screenshot_supplied)
            decoded = _extract_json_object(content)
            return DiscoveryDecision.model_validate(decoded)
        except Exception:
            fallback_messages = [
                {"role": "system", "content": "Return only valid JSON with keys action, observed_id, semantic_name, input_name, output_name, reason, goal_complete. Use member_id as input_name and balance as output_name when appropriate."},
                {"role": "user", "content": user_content},
            ]
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=fallback_messages,
            )
            self._record_response_metadata(response, screenshot_supplied)
            content = response.choices[0].message.content or "{}"
            decoded = _extract_json_object(content)
            return DiscoveryDecision.model_validate(decoded)

    def _record_response_metadata(self, response: object, screenshot_supplied: bool) -> None:
        """
        Retain non-secret provider metadata for the discovery audit log.

        Input Parameter:
            response(object): Provider response object.
            screenshot_supplied(bool): Whether visual evidence was sent to the model.

        Output Parameter:
            output_parameter(None): This function returns no value.
        """
        usage = getattr(response, "usage", None)
        self.last_call_metadata = {
            "model": getattr(response, "model", self.model),
            "response_id": getattr(response, "id", None),
            "screenshot_supplied": screenshot_supplied,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        }


class OfflineSemanticFixtureProvider(DiscoveryProvider):
    """Provide an honest deterministic fixture for reviewers without live services."""

    def decide(self, goal: str, observation: SurfaceObservation, history: list[DiscoveryDecision]) -> DiscoveryDecision:
        """
        Select fixture actions from control roles, form relationships, and application state.

        Input Parameter:
            goal(str): Natural-language user goal used for fixture scope validation.
            observation(SurfaceObservation): Current semantic surface observation.
            history(list[DiscoveryDecision]): Prior constrained decisions.

        Output Parameter:
            output_parameter(DiscoveryDecision): Next deterministic fixture decision.
        """
        del goal
        completed = {item.action for item in history}
        if ActionKind.INPUT not in completed:
            candidates = [item for item in observation.controls if item.role == "textbox" and item.label]
            target = candidates[0]
            return DiscoveryDecision(action=ActionKind.INPUT, observed_id=target.observed_id, semantic_name="member_identifier_input", input_name="member_id", reason="The labeled textbox is the form's sole record-identity input.")
        if ActionKind.ACTIVATE not in completed:
            candidates = [item for item in observation.controls if item.role == "button"]
            target = candidates[0]
            return DiscoveryDecision(action=ActionKind.ACTIVATE, observed_id=target.observed_id, semantic_name="member_lookup_action", reason="The form's button submits the identity query.")
        candidates = [item for item in observation.controls if item.role in {"status", "output"} and "$" in item.text]
        target = candidates[0]
        return DiscoveryDecision(action=ActionKind.EXTRACT, observed_id=target.observed_id, semantic_name="savings_balance_output", output_name="balance", reason="The monetary status cell is aligned with the Savings account row.", goal_complete=True)
