# 1. Architecture

The design follows one strict boundary: **the model discovers; compiled artifacts replay**. A Playwright driver observes a live surface as a compressed set of accessible roles, names, labels, visible state, and screenshot evidence. Only the discovery provider can call an LLM. Its response is constrained to a Pydantic `DiscoveryDecision` and must select an ID actually present in the observation. Every proposed discovery action still passes through policy enforcement before execution.

A successful discovery produces two deliberately separate assets. The Application Model/Control Registry captures what this vendor product/version/tenant looks like and what its controls mean. The Capability Artifact captures a reusable business procedure and typed call contract. The compiler parameterizes inputs, declares outputs, attaches action/state/goal checkpoints, and removes the raw model conversation and example data. This separation lets many capabilities reuse application knowledge and lets a tenant override a registry without silently rewriting business procedures.

Certification sits between compilation and production. Discovery yields `draft`, never `active`. Structural validation—including cross-checking every compiled step and checkpoint control against the bound registry—semantic validation, deterministic alternate-input replay, exceptional-state verification, and reviewer approval are independent gates. The CLI `--auto-approve` path is an explicit reviewer convenience, not an implicit bypass: it activates only after every automated gate succeeds and records the reviewer and time.

The trade-off is deliberate conservatism. This implementation stops on ambiguity instead of asking a model to improvise during production. It may escalate more often, but its behavior is explainable, bounded, and appropriate for banking operations.

# 2. Artifact schema

The Pydantic artifact is a versioned agent-invocable contract: identity/version, application family and registry digest, typed inputs/outputs, ordered surface-neutral steps, explicit visible-state exception matchers, policy envelope, certification record, and lifecycle status. Input values use `ValueReference` objects, so a recorded member ID never enters the artifact. Output declarations state the shape returned to the caller.

Steps refer to semantic registry keys such as `member_identifier_input`, not browser coordinates or copied selectors. The corresponding registry control stores its observed application ID plus ranked locator evidence: accessible role/name, label, and DOM ID. Importantly, these concrete IDs are read from the live page during discovery. They are neither predefined by the compiler nor invented by the model. Exact accessible and label matches outrank DOM IDs; resolution requires a unique candidate.

Checkpoint levels make success explicit. An action checkpoint verifies that an input took effect. A state checkpoint can prove the expected application state. A goal checkpoint verifies the business output shape, such as valid money. The model cannot declare success merely because it finished acting.

The schema is surface-neutral at the action layer (`input`, `activate`, `extract`, `wait`) while locator records can evolve with driver-specific strategy types. This costs some browser-specific expressiveness but preserves a credible desktop/legacy extension seam.

# 3. Determinism & error handling

Replay accepts only an active artifact, matching registry, ephemeral inputs, surface, logger, and evidence directory. It has no model/provider dependency. It walks a fixed step list. Each step observes known exceptions, checks policy, resolves a unique target using fixed rankings, acts, and evaluates declared checkpoints. Retries are bounded and allowed only for steps marked safe and idempotent.

The result union separates four meanings. `success` includes typed outputs. `business_outcome` reports a legitimate domain answer such as no matching member. `recovered` records a known deterministic or human-mediated recovery. `failure` includes a stable code, failing step, expectation/message, and evidence path. The demo includes success, not-found, host-error, and supervisor-gate states.

Runtime errors matter more than cosmetic drift. Before each next action, replay detects configured visible states. Known not-found text maps to a business outcome; the host-system message maps to a hard failure; the supervisor dialog maps to intervention. Unknown missing or ambiguous targets stop safely. A failed checkpoint captures the pre-action view and, when available, the post-error state. Persisted observations use bounded state labels instead of the full page body. Drift is secondary but guarded by the application fingerprint and registry digest; production would require a confidence threshold and suspend capabilities after repeated mismatch.

# 4. Heterogeneity & multi-tenant

`SurfaceDriver` is the seam between procedure semantics and perception/action technology. `PlaywrightSurfaceDriver` is one implementation. A Windows accessibility or remote-desktop driver can implement the same observe/act/snapshot/human-event operations, resolving the same semantic control references through desktop accessibility attributes, OCR/visual anchors, or coordinates. Legacy web frames can extend `frame_path` and locator types without changing capability sequencing.

Registry fingerprinting records family, product version, tenant variant, title, route pattern, landmarks, and a digest of observed control evidence. A shared vendor baseline would live at family/version scope. Tenant overlays would add branding, label, route, and locator differences. Exact/high-confidence matches can reuse an approved capability. Medium confidence triggers additional deterministic verification. Low confidence creates a new discovery/review candidate instead of trusting cached knowledge.

Capabilities never silently mutate. Human actions, drift, or a successful fallback can propose a new registry/capability version, which must pass certification again. This protects all other tenants using the approved base.

# 5. Escalation & handoff

“Stuck” means a maximum-step/dead-end discovery state, an unresolved or ambiguous replay target, an unknown dialog, a failed checkpoint, or a policy/risk boundary. Severity comes from deterministic rules: Low for discovery ambiguity with minimal business impact, Medium when a capability cannot proceed, and High for sensitive approval or potentially irreversible states.

`SessionOwnershipController` implements a real control-transfer state machine. Automation begins as owner. On escalation it creates an `InterventionRequest` with capability, step, reason, severity, and screenshot; changes owner to human; and blocks its event loop while retaining the same browser, context, page, cookies, and application state. A headed window is the minimal operator surface. Injected listeners record click/input/change activity while the owner is human. The operator explicitly signals resume, ownership returns to automation, and captured human actions enter the audit log.

After takeover, replay re-observes the same page and proves the blocking state is gone before continuing the compiled step. If that validation fails, it returns `CUA-HITL-002`; it never assumes the human left the page where expected. A richer implementation would support named recovery checkpoints and multi-branch resumption.

# 6. Safety

Policy enforcement is code outside the model. Both discovery proposals and replayed steps must match allowed domains, route prefixes, action types, and maximum risk. The sample capability is localhost-only and read-only. Irreversible operations exceed policy and are blocked or require high-severity human approval; retries are forbidden unless idempotency is explicit.

Artifacts contain parameter names, never example PII or secrets. JSON logs recursively redact sensitive field names and record reasons, actions, step IDs, error codes, and evidence locations. Credentials remain environment variables. The primary limit is screenshots: a real banking screenshot may contain regulated data even when text logs are redacted. Production requires encrypted evidence storage, access control, tenant-specific retention, image redaction, audit immutability, and a secrets-backed deterministic authentication handler.

# 7. Cuts

I deliberately omitted distributed workers, a database/catalog API, desktop drivers, remote co-browsing, credential-vault integration, visual OCR fallback, cross-tenant deployment plumbing, and automatic capability repair. The assignment rewards the correctness of the core boundary more than premature platform infrastructure.

Next I would add a post-handoff recovery-checkpoint graph; screenshot PII redaction and encrypted retention; session-expiry recovery backed by a vault; signed artifacts with registry compatibility ranges; a second tenant variant proving overlay reuse; multi-run stability scoring; and a desktop accessibility driver. I would then expose active capabilities through a small typed catalog/API, while keeping discovery and production replay in separate deployable processes so model credentials cannot exist in the replay environment.
