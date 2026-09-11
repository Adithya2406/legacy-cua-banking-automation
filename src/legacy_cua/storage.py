"""JSON persistence for typed registries and capabilities."""

import json
from pathlib import Path

from .schemas import ApplicationRegistry, CapabilityArtifact


class ArtifactStore:
    """Persist reviewable typed contracts as stable JSON."""

    def save_registry(self, registry: ApplicationRegistry, path: Path) -> None:
        """
        Save an application registry as formatted JSON.

        Input Parameter:
            registry(ApplicationRegistry): Registry to persist.
            path(Path): Destination file path.

        Output Parameter:
            output_parameter(None): This function returns no value.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(registry.model_dump_json(indent=2), encoding="utf-8")

    def save_artifact(self, artifact: CapabilityArtifact, path: Path) -> None:
        """
        Save a capability artifact as formatted JSON.

        Input Parameter:
            artifact(CapabilityArtifact): Capability to persist.
            path(Path): Destination file path.

        Output Parameter:
            output_parameter(None): This function returns no value.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")

    def load_registry(self, path: Path) -> ApplicationRegistry:
        """
        Load and validate an application registry.

        Input Parameter:
            path(Path): Source JSON path.

        Output Parameter:
            output_parameter(ApplicationRegistry): Validated registry.
        """
        return ApplicationRegistry.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def load_artifact(self, path: Path) -> CapabilityArtifact:
        """
        Load and validate a capability artifact.

        Input Parameter:
            path(Path): Source JSON path.

        Output Parameter:
            output_parameter(CapabilityArtifact): Validated capability.
        """
        return CapabilityArtifact.model_validate(json.loads(path.read_text(encoding="utf-8")))
