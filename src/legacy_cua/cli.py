"""Command-line entry points for discovery, certification, and replay."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

from .certification import CapabilityCertifier, offline_semantic_validator
from .compiler import CapabilityCompiler
from .demo_server import serve
from .discovery import DiscoveryEngine
from .logging import JsonLogger
from .providers import OfflineSemanticFixtureProvider, OpenAIDiscoveryProvider
from .replay import ReplayEngine
from .schemas import CapabilityArtifact, CertificationStatus, ExecutionResult
from .storage import ArtifactStore
from .surface import PlaywrightSurfaceDriver


load_dotenv()


def _active_copy(artifact: CapabilityArtifact) -> CapabilityArtifact:
    """
    Create an in-memory active copy solely for certification verification.

    Input Parameter:
        artifact(CapabilityArtifact): Candidate artifact under certification.

    Output Parameter:
        output_parameter(CapabilityArtifact): Ephemeral active copy.
    """
    copy = artifact.model_copy(deep=True)
    copy.status = CertificationStatus.ACTIVE
    return copy


def _run_once(url: str, artifact: CapabilityArtifact, registry_path: Path, member_id: str, log_path: Path, evidence_dir: Path, headed: bool = False) -> ExecutionResult:
    """
    Run one deterministic replay in a fresh browser session.

    Input Parameter:
        url(str): Banking demo URL.
        artifact(CapabilityArtifact): Active capability.
        registry_path(Path): Saved registry path.
        member_id(str): Synthetic invocation identifier.
        log_path(Path): Structured replay log path.
        evidence_dir(Path): Screenshot evidence directory.
        headed(bool): Whether to display the browser.

    Output Parameter:
        output_parameter(ExecutionResult): Structured replay result.
    """
    surface = PlaywrightSurfaceDriver(url, headed=headed)
    try:
        registry = ArtifactStore().load_registry(registry_path)
        return ReplayEngine(surface, JsonLogger(log_path), evidence_dir).run(artifact, registry, {"member_id": member_id})
    finally:
        surface.close()


def discover(arguments: argparse.Namespace) -> None:
    """
    Run semantic discovery and save a registry plus draft capability.

    Input Parameter:
        arguments(argparse.Namespace): Parsed discovery command arguments.

    Output Parameter:
        output_parameter(None): This function writes artifacts and prints paths.
    """
    output = Path(arguments.output)
    output.mkdir(parents=True, exist_ok=True)
    provider = OfflineSemanticFixtureProvider() if arguments.offline else OpenAIDiscoveryProvider(arguments.model)
    surface = PlaywrightSurfaceDriver(arguments.url, headed=arguments.headed)
    try:
        engine = DiscoveryEngine(surface, provider, JsonLogger(output / "discovery.jsonl"), output / "screenshots")
        trace, registry = engine.run(arguments.goal, {"member_id": arguments.member_id})
        artifact = CapabilityCompiler().compile(trace, registry)
        store = ArtifactStore()
        store.save_registry(registry, output / "application-registry.json")
        store.save_artifact(artifact, output / "capability.draft.json")
        print(json.dumps({"registry": str(output / "application-registry.json"), "artifact": str(output / "capability.draft.json"), "provider": "offline-fixture" if arguments.offline else "openai"}, indent=2))
    finally:
        surface.close()


def certify(arguments: argparse.Namespace) -> None:
    """
    Run certification gates and apply optional CLI auto-approval.

    Input Parameter:
        arguments(argparse.Namespace): Parsed certification command arguments.

    Output Parameter:
        output_parameter(None): This function writes the certified artifact.
    """
    store = ArtifactStore()
    artifact_path = Path(arguments.artifact)
    registry_path = Path(arguments.registry)
    artifact = store.load_artifact(artifact_path)
    work = artifact_path.parent
    active = _active_copy(artifact)
    alternate = lambda: _run_once(arguments.url, active, registry_path, "10002", work / "certification-alternate.jsonl", work / "certification-alternate")
    exceptional = lambda: _run_once(arguments.url, active, registry_path, "40400", work / "certification-exception.jsonl", work / "certification-exception")
    alternate_result = alternate()
    exceptional_result = exceptional()
    certified = CapabilityCertifier().certify(artifact, offline_semantic_validator, lambda: alternate_result, lambda: exceptional_result, auto_approve=arguments.auto_approve, reviewer=arguments.reviewer)
    destination = Path(arguments.output)
    store.save_artifact(certified, destination)
    report = {
        "capability_id": certified.capability_id,
        "status": certified.status,
        "provider": "deterministic-semantic-contract-validator",
        "gates": [
            {
                "gate": "structural_valid",
                "input_class": "artifact contract",
                "expected_result": True,
                "actual_result": bool(certified.certification.structural_valid),
                "evidence_path": str(artifact_path),
            },
            {
                "gate": "semantic_valid",
                "input_class": "business semantics",
                "expected_result": True,
                "actual_result": bool(offline_semantic_validator(certified)),
                "validator": "offline_semantic_validator",
                "explanation": "Checked that the capability includes a member_id input, a balance output, at least three steps, and banking-specific Savings semantics.",
                "evidence_path": str(artifact_path),
            },
            {
                "gate": "alternate_input_verified",
                "input_class": "alternate member input",
                "expected_result": "success",
                "actual_result": alternate_result.kind.value,
                "evidence_path": str(work / "certification-alternate.jsonl"),
            },
            {
                "gate": "exceptional_state_verified",
                "input_class": "not-found exception",
                "expected_result": "business_outcome or failure",
                "actual_result": exceptional_result.kind.value,
                "evidence_path": str(work / "certification-exception.jsonl"),
            },
        ],
    }
    report_path = destination.with_name("certification-report.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"artifact": str(destination), "report": str(report_path), "status": certified.status}, indent=2))


def replay(arguments: argparse.Namespace) -> None:
    """
    Replay a saved capability without constructing any model provider.

    Input Parameter:
        arguments(argparse.Namespace): Parsed replay command arguments.

    Output Parameter:
        output_parameter(None): This function prints the structured result.
    """
    artifact = ArtifactStore().load_artifact(Path(arguments.artifact))
    result = _run_once(arguments.url, artifact, Path(arguments.registry), arguments.member_id, Path(arguments.log), Path(arguments.evidence), arguments.headed)
    print(result.model_dump_json(indent=2))


def record_hitl(arguments: argparse.Namespace) -> None:
    """
    Run and persist an interactive same-session human handoff demonstration.

    Input Parameter:
        arguments(argparse.Namespace): Parsed human-handoff command arguments.

    Output Parameter:
        output_parameter(None): This function updates the evidence results and prints the outcome.
    """
    base = Path(arguments.output)
    artifact = ArtifactStore().load_artifact(base / "capability.active.json")
    result = _run_once(
        arguments.url,
        artifact,
        base / "application-registry.json",
        "77777",
        base / "replay-hitl.jsonl",
        base / "replay-hitl",
        headed=True,
    )
    results_path = base / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else {}
    results["hitl"] = result.model_dump(mode="json")
    results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    manifest_path = base / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["hitl_mode"] = "interactive-human"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(result.model_dump_json(indent=2))


def demo_e2e(arguments: argparse.Namespace) -> None:
    """
    Start the demo and execute discovery, certification, success, and exception runs.

    Input Parameter:
        arguments(argparse.Namespace): Parsed end-to-end command arguments.

    Output Parameter:
        output_parameter(None): This function produces a complete evidence bundle.
    """
    server = threading.Thread(target=serve, args=("127.0.0.1", arguments.port), daemon=True)
    server.start()
    time.sleep(0.5)
    base = Path(arguments.output)
    url = f"http://127.0.0.1:{arguments.port}/"
    run_id = f"run-{int(time.time() * 1000)}"
    discover(argparse.Namespace(output=str(base), offline=arguments.offline, model=arguments.model, url=url, headed=False, goal="Look up member 10001 and return their current savings balance", member_id="10001"))
    certify(argparse.Namespace(artifact=str(base / "capability.draft.json"), registry=str(base / "application-registry.json"), url=url, auto_approve=True, reviewer="reviewer-fast-path", output=str(base / "capability.active.json")))
    active = ArtifactStore().load_artifact(base / "capability.active.json")
    success = _run_once(url, active, base / "application-registry.json", "10003", base / "replay-success.jsonl", base / "replay-success")
    exceptional = _run_once(url, active, base / "application-registry.json", "40400", base / "replay-not-found.jsonl", base / "replay-not-found")
    recovered = _run_once(url, active, base / "application-registry.json", "40800", base / "replay-recovered.jsonl", base / "replay-recovered")
    failure = _run_once(url, active, base / "application-registry.json", "50000", base / "replay-failure.jsonl", base / "replay-failure")
    (base / "results.json").write_text(json.dumps({"success": success.model_dump(mode="json"), "not_found": exceptional.model_dump(mode="json"), "recovered": recovered.model_dump(mode="json"), "failure": failure.model_dump(mode="json")}, indent=2), encoding="utf-8")
    screenshot_enabled = os.getenv("OPENAI_INCLUDE_SCREENSHOT", "true").lower() not in {"0", "false", "no"}
    (base / "manifest.json").write_text(json.dumps({"schema_version": "1.0", "run_id": run_id, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "discovery_mode": "offline-fixture" if arguments.offline else "provider-backed", "provider_model": None if arguments.offline else arguments.model, "model_input_modalities": ["ui_metadata"] if arguments.offline else ["ui_metadata", "screenshot"] if screenshot_enabled else ["ui_metadata"], "synthetic_data_only": True, "claim": "Offline fixture evidence is explicitly labeled and is not a genuine LLM run." if arguments.offline else "Discovery used the configured OpenAI-compatible provider."}, indent=2), encoding="utf-8")
    print((base / "results.json").read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    """
    Build the command-line parser for all workflow stages.

    Input Parameter:
        input_parameter(None): This function accepts no parameters.

    Output Parameter:
        output_parameter(argparse.ArgumentParser): Configured command parser.
    """
    parser = argparse.ArgumentParser(prog="legacy-cua")
    commands = parser.add_subparsers(dest="command", required=True)
    discovery = commands.add_parser("discover")
    discovery.add_argument("--goal", required=True)
    discovery.add_argument("--member-id", default="10001")
    discovery.add_argument("--url", default="http://127.0.0.1:8765/")
    discovery.add_argument("--output", default="artifacts/runtime")
    discovery.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    discovery.add_argument("--offline", action="store_true")
    discovery.add_argument("--headed", action="store_true")
    discovery.set_defaults(handler=discover)
    certification = commands.add_parser("certify")
    certification.add_argument("--artifact", required=True)
    certification.add_argument("--registry", required=True)
    certification.add_argument("--url", default="http://127.0.0.1:8765/")
    certification.add_argument("--output", default="artifacts/runtime/capability.active.json")
    certification.add_argument("--reviewer", default="local-reviewer")
    certification.add_argument("--auto-approve", action="store_true")
    certification.set_defaults(handler=certify)
    execution = commands.add_parser("replay")
    execution.add_argument("--artifact", required=True)
    execution.add_argument("--registry", required=True)
    execution.add_argument("--member-id", required=True)
    execution.add_argument("--url", default="http://127.0.0.1:8765/")
    execution.add_argument("--log", default="evidence/runtime/replay.jsonl")
    execution.add_argument("--evidence", default="evidence/runtime/screenshots")
    execution.add_argument("--headed", action="store_true")
    execution.set_defaults(handler=replay)
    handoff = commands.add_parser("record-hitl")
    handoff.add_argument("--output", default="evidence/provider-backed")
    handoff.add_argument("--url", default="http://127.0.0.1:8765/")
    handoff.set_defaults(handler=record_hitl)
    demo = commands.add_parser("demo-e2e")
    demo.add_argument("--output", default="evidence/generated")
    demo.add_argument("--port", default=8765, type=int)
    demo.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    demo.add_argument("--offline", action="store_true")
    demo.set_defaults(handler=demo_e2e)
    return parser


def main() -> None:
    """
    Dispatch the requested command-line workflow stage.

    Input Parameter:
        input_parameter(None): This function reads process arguments.

    Output Parameter:
        output_parameter(None): This function returns no value.
    """
    arguments = build_parser().parse_args()
    arguments.handler(arguments)


if __name__ == "__main__":
    main()
