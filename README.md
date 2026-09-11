# Legacy CUA: discover once, replay deterministically

Legacy CUA is a small, end-to-end computer-use automation system for a deliberately legacy-style banking UI. An LLM may reason over accessibility/UI metadata and screenshot evidence during **discovery only**. A compiler turns the successful constrained trace into a typed capability. Certification gates activation. Production replay follows that compiled graph with no model client anywhere in the replay dependency tree.

The repository is intentionally a deep vertical slice rather than a platform: it includes a local table-based banking app, versioned Application Model/Control Registry, Pydantic artifact contracts, policy guardrails, deterministic replay and checkpoints, error taxonomy, structured/redacted logs, a same-session human handoff, certification, tests, and saved evidence.

## Architecture at a glance

```text
goal + target
      |
      v
Playwright observation ---- screenshot + semantic control metadata
      |                                      |
      +----------> discovery provider <------+   (LLM boundary)
                         |
               constrained trace decisions
                         |
      Application Registry + Capability Compiler
                         |
                  draft capability
                         |
  structural + semantic + alternate input + exception checks
                         |
              reviewer approval / activation
                         |
      deterministic ReplayEngine (no provider/model import)
                         |
     success | business outcome | recovered | failure
```

The registry answers “what do controls mean in this app/version?” The capability answers “what procedure should run?” Multiple procedures can reuse one registry, while tenant/version fingerprints prevent accidental cross-version application.

## Repository layout

```text
src/legacy_cua/
  cli.py             workflow commands
  demo_server.py     intentionally legacy local banking UI
  surface.py         surface-neutral contract + Playwright adapter
  providers.py       discovery-only model boundary and offline fixture
  discovery.py       observe-decide-act loop
  compiler.py        trace-to-capability compiler
  certification.py   independent certification gates
  replay.py          deterministic executor and checkpoints
  handoff.py         same-session ownership transfer
  policy.py          domain, route, action, and risk guardrails
  schemas.py         strict Pydantic contracts
  storage.py         typed JSON persistence
  logging.py         JSONL audit logs and redaction
evidence/             saved artifacts, logs, results, and screenshots
tests/                load-bearing unit/integration tests
REPORT.md             design decisions and trade-offs
```

## Setup

Python 3.11+ is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m pip install .
```

Conda is also supported:

```bash
conda create --prefix ./.conda-env python=3.11 pip -y
conda activate ./.conda-env
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m pip install .
```

For provider-backed discovery, copy `.env.example` to `.env` and configure it locally. `.env` is ignored by Git and loaded automatically; never commit it.

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | For OpenAI | Provider credential; leave blank only for a trusted local compatible endpoint |
| `OPENAI_MODEL` | Yes for provider mode | Vision-capable discovery model; defaults to `gpt-4.1-mini` |
| `OPENAI_BASE_URL` | Local/compatible providers only | OpenAI-compatible endpoint; leave blank for OpenAI |
| `OPENAI_INCLUDE_SCREENSHOT` | Recommended | Keep `true` for assignment-compliant metadata-plus-screenshot discovery |

No credential or provider URL is embedded in the source, artifacts, or evidence. The application URL defaults to localhost because the target is the bundled demo app, and it may be overridden with `--url`.

## Fastest no-live-service demo

This path needs no external application and no model API. It starts the local app, uses the clearly labeled offline semantic fixture to exercise the same constrained discovery/compiler contracts, auto-approves after all certification checks, runs a successful replay, and runs a not-found replay:

```bash
legacy-cua demo-e2e --offline --output evidence/generated
```

The offline provider is not represented as a genuine LLM run. Its purpose is reviewer reproducibility. The browser interaction, control extraction, compiler, certification, replay, checkpoints, policy, and evidence paths are real.

## Exact live discovery then replay commands

Terminal 1 — local target application:

```bash
python -m legacy_cua.demo_server
```

Terminal 2 — genuine provider-backed discovery:

```bash
export OPENAI_API_KEY="your-key"
export OPENAI_MODEL="gpt-4.1-mini"
legacy-cua discover \
  --goal "Look up member 10001 and return their current savings balance" \
  --member-id 10001 \
  --url http://127.0.0.1:8765/ \
  --output artifacts/runtime
```

The prompt sends a compressed list of **observed** controls and the current screenshot to a vision-capable model. The model must return a typed decision selecting an `observed_id`; invalid IDs are rejected rather than silently converted into a selector. The registry control IDs and locators are constructed from those live observations, not fabricated or predefined in the discovery engine. Provider logs retain only non-secret metadata such as the model, response ID, token counts, and whether a screenshot was supplied.

Certify, including deterministic alternate-input and exceptional-state verification, then use the reviewer fast path:

```bash
legacy-cua certify \
  --artifact artifacts/runtime/capability.draft.json \
  --registry artifacts/runtime/application-registry.json \
  --auto-approve \
  --reviewer "assignment-reviewer" \
  --output artifacts/runtime/capability.active.json
```

Replay with no LLM:

```bash
legacy-cua replay \
  --artifact artifacts/runtime/capability.active.json \
  --registry artifacts/runtime/application-registry.json \
  --member-id 10003 \
  --log evidence/runtime/replay-success.jsonl \
  --evidence evidence/runtime/replay-success
```

Exercise a legitimate not-found business outcome:

```bash
legacy-cua replay \
  --artifact artifacts/runtime/capability.active.json \
  --registry artifacts/runtime/application-registry.json \
  --member-id 40400 \
  --log evidence/runtime/replay-not-found.jsonl \
  --evidence evidence/runtime/replay-not-found
```

Synthetic demo cases are `10001`/`10002`/`10003` (success), `40400` (not found), `40800` (one transient delay followed by deterministic recovery), `50000` (host failure), and `77777` (supervisor intervention). These are fake records only.

## Human-in-the-loop demonstration

Run replay headed with member `77777`:

```bash
legacy-cua replay \
  --headed \
  --artifact artifacts/runtime/capability.active.json \
  --registry artifacts/runtime/application-registry.json \
  --member-id 77777
```

To record the handoff directly into an end-to-end evidence bundle, start the demo server and run:

```bash
legacy-cua record-hitl \
  --output evidence/provider-backed \
  --url http://127.0.0.1:8765/
```

This command always opens a visible browser and requires an actual person to resolve the supervisor dialog and press Enter. There is no production auto-click path.

When the deterministic rule sees the supervisor gate, `SessionOwnershipController` changes owner from `automation` to `human`, keeps the same browser/context/page alive, and blocks the automation event loop. The human clicks **Supervisor Continue** in that existing window, then presses Enter in the terminal. Browser listeners record clicks/input/change events only while ownership is human. Ownership returns to automation, replay re-observes the page, proves the supervisor gate is gone, and continues the compiled step. If the state is still blocked it stops with `CUA-HITL-002`. Approved artifacts are never rewritten from human actions; proposed improvements would create a new draft version.

## Determinism and targeting

Each registry control contains a ranked locator bundle derived from the observed UI: exact accessible role/name, associated label, and observed DOM ID. Replay applies fixed resolution and uniqueness rules. It never asks a model to interpret a changed page. Every step is transaction-like: observe exceptions, policy-check, resolve, act, and verify checkpoints. Only `safe_to_retry` actions receive bounded retries.

`ReplayEngine` does not import, receive, or construct a discovery provider. A source-level test can therefore verify the boundary, while behavior tests prove replay succeeds using only the artifact, registry, input, surface, and logger.

## Result taxonomy

- `success`: all declared checkpoints passed and typed outputs were extracted.
- `business_outcome`: the application produced a legitimate domain result such as `MEMBER_NOT_FOUND`.
- `recovered`: a known recoverable or human-mediated condition was handled; the caller is told what to do next.
- `failure`: an unsafe, ambiguous, invalid, or unexpected condition stopped execution with step and evidence context.

Intervention severity is deterministic: **Low** for discovery ambiguity with no business impact, **Medium** for a blocked capability or application failure, and **High** near sensitive, approval, or irreversible states.

## Safety boundaries

Policy is enforced outside the model for both discovery and replay. It checks domain, route prefix, action type, and maximum risk. The sample capability permits only safe read/inquiry behavior on localhost. Irreversible actions are blocked. Invocation values are referenced by name in artifacts, never embedded. Structured logs redact sensitive fields and registered invocation values even when a model repeats them inside free-form reasoning. Screenshots can still contain visible regulated data in a real deployment; production storage therefore needs encrypted, access-controlled retention and automated image redaction.

## Error codes

| Code | Meaning | Classification / action |
|---|---|---|
| `CUA-DISC-001` | Discovery exceeded max steps | Failure; stop and review |
| `CUA-DISC-002` | Discovery reached a dead end | Low intervention |
| `CUA-DISC-003` | Model selected invalid/unobserved control | Low intervention |
| `CUA-POL-001` | Domain outside allowlist | Hard safety failure |
| `CUA-POL-002` | Route outside allowlist | Hard safety failure |
| `CUA-POL-003` | Action outside allowlist | Hard safety failure |
| `CUA-POL-004` | Risk exceeds capability policy | High intervention / block |
| `CUA-RPL-001` | Target not found | Medium intervention |
| `CUA-RPL-002` | Target ambiguous | Medium intervention; never guess |
| `CUA-RPL-003` | Checkpoint failed | Failure with screenshot |
| `CUA-RPL-004` | Application reported hard failure | Medium intervention |
| `CUA-RPL-005` | Session expired | Recover only with configured deterministic login |
| `CUA-RPL-006` | Invocation input invalid | Caller-correctable failure |
| `CUA-CERT-001` | Capability is not active | Replay blocked |
| `CUA-CERT-002` | Certification gate failed | Remains draft/unapproved |
| `CUA-HITL-001` | Human intervention required | Low/Medium/High from matching rule |
| `CUA-HITL-002` | State invalid after resume | Stop; do not continue blindly |

Informational events use `CUA-INFO-*` and are not errors.

## Tests

```bash
pytest -q
```

The tests cover discovery-to-compile behavior using observed control IDs, deterministic success, business outcomes, policy denials, sensitive log redaction, and ownership handoff on one retained surface. The browser-backed `demo-e2e` command is the executable integration proof.

## Evidence provenance

`evidence/` contains a manifest describing whether discovery used a real model or the offline fixture. Never relabel offline output as provider-backed evidence. To satisfy the assignment's strict “genuine LLM run” ground rule, use a vision-capable model and commit the generated log/artifact/screenshot set. Logs store provider provenance and model-input modalities but never credentials, endpoint URLs, or raw member identifiers.

## Known cuts

This submission does not implement desktop drivers, distributed queues, remote co-browsing, credential vault integration, image redaction, or automated cross-tenant promotion. The abstraction seams are present, but building that infrastructure would obscure the evaluated core. See `REPORT.md` for the intended next steps.
