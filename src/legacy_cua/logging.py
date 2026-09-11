"""Structured JSON logging with sensitive-value redaction."""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JsonLogger:
    """Write line-delimited JSON events suitable for audit and debugging."""

    def __init__(self, path: Path, run_id: str | None = None) -> None:
        """
        Initialize a structured logger at a filesystem path.

        Input Parameter:
            path(Path): Destination JSONL log path.
            run_id(str | None): Optional correlation identifier for the run.

        Output Parameter:
            output_parameter(None): This initializer returns no value.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.run_id = run_id or str(uuid.uuid4())
        self._sensitive_values: dict[str, str] = {}
        self._logger = logging.getLogger(f"legacy_cua.{path}.{self.run_id}")
        self._logger.handlers.clear()
        self._logger.setLevel(logging.INFO)
        handler = logging.FileHandler(path, mode="w", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(handler)
        self._logger.propagate = False

    def event(self, event: str, code: str, message: str, **context: Any) -> None:
        """
        Write one redacted structured event.

        Input Parameter:
            event(str): Stable event name.
            code(str): Stable error or informational code.
            message(str): Human-readable event summary.
            context(Any): Additional non-secret diagnostic fields.

        Output Parameter:
            output_parameter(None): This function returns no value.
        """
        record = self._redact({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "event": event,
            "code": code,
            "message": message,
            **context,
        })
        self._logger.info(json.dumps(record, sort_keys=True))

    def register_sensitive_values(self, values: dict[str, Any]) -> None:
        """
        Register ephemeral values that must be removed from every logged string.

        Input Parameter:
            values(dict[str, Any]): Sensitive names and invocation values held only in memory.

        Output Parameter:
            output_parameter(None): This function returns no value.
        """
        for name, value in values.items():
            rendered = str(value)
            if rendered:
                self._sensitive_values[rendered] = name

    def _redact(self, value: Any) -> Any:
        """
        Recursively redact fields whose names indicate sensitive data.

        Input Parameter:
            value(Any): Arbitrary log context value.

        Output Parameter:
            output_parameter(Any): Redacted value safe for persistence.
        """
        sensitive = {"member_id", "password", "token", "secret", "api_key", "account_id"}
        if isinstance(value, dict):
            return {key: "<redacted>" if key.lower() in sensitive else self._redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, str):
            redacted = value
            for sensitive_value, name in sorted(self._sensitive_values.items(), key=lambda item: len(item[0]), reverse=True):
                redacted = redacted.replace(sensitive_value, f"<redacted:{name}>")
            return redacted
        return value
