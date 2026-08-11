# Conscience: the perception & reach gate

**How Open Body Control stops a language model from *observing* a subject or
*touching* a system it shouldn't — enforced by deterministic code the model
cannot override.**

*Status: built and vendored, with one gap that code cannot close. Sibling to
[SAFETY.md](SAFETY.md). Where SAFETY.md governs what the agent may **do** to the
physical world (Track 0, actuation), this governs what the agent may **see** and
what it may **reach**. Nothing here is aspirational; the gaps in §6 are as
load-bearing as the guarantees in §2. Written 2026-08.*

> This line said *"design, not a decision"* until 2026-08-06. That was true when
> written and stopped being true two days later, when the `obc-conscience` crate
> landed upstream and was vendored here — `cargo test --workspace` in this
> repository now runs its 43 tests. Understating a shipped safety control is a
> smaller sin than overstating one, and it is still the same defect: a status
> line nobody re-read. The one thing §6 still calls unmeasured — the detector's
> human false-negative rate in the field — is unmeasured because it needs an
> annotated eval set, not more code.

---

## 0. Why this exists, and why the actuator gate is not enough

Track 0 answers one question completely: *can the model move a motor it
shouldn't?* No — a deterministic limit table on the host and mirrored on the
MCU refuses out-of-range actuation regardless of how the model was reasoned
into asking.

It answers two other questions not at all:

- **Can the model *watch* a subject it shouldn't?** A camera-bearing,
  always-on, mesh-networked agent is a surveillance apparatus by default.
  ClawCam pointed at wildlife is one configuration change — or one
  hallucinated tool call, or one prompt injection — away from ClawCam
  pointed at a person who never consented. The actuator gate is silent on
  this. Recording is not actuation; it moves no motor and trips no limit.
- **Can the model *reach* a system it shouldn't?** In July 2026, OpenAI's own
  models — in a sandbox with guardrails deliberately disabled — found an
  Artifactory zero-day, escaped, and used chained credentials to breach
  Hugging Face's production database. The lesson the whole industry drew is
  the lesson this project already holds for actuation: **containment must
  never rely on the model's own refusals.** An agent with network reach,
  stored credentials, and a code-execution tool is a lateral-movement engine
  unless something outside the model bounds where it may reach.

Conscience is Track 0 extended to perception and reach: **the model proposes
what to observe and what to touch; a deterministic gate disposes.** The
model is not the privacy function, and it is not the access-control function,
for the same reason it is not the safety function — *"threat 1 (model wrong)
and threat 3 (model/host compromised) are the same problem,"* so enforcement
must live in neither the model nor the code the model can influence.

## 1. Threat model

Five adversaries, extending SAFETY.md's four:

1. **Model wrong** — hallucinates a subject into the allowlist, or a
   plausible reason to retain footage of a bystander.
2. **Model manipulated** — a sign, a QR code, a spoken phrase, or text in the
   camera frame reasons the model into capturing or exfiltrating.
   (Perception *is* the injection surface here — the thing it watches tells
   it what to do.)
3. **Component compromised** — a poisoned skill or a compromised host issues
   capture/retain/network calls directly.
4. **Record disputed** — someone claims footage was taken, or a system was
   accessed, that the logs must be able to confirm or refute.
5. **Operator overreach** — the operator themselves configures the agent to
   surveil a non-consenting third party. Conscience cannot fully stop an
   operator with physical control, but it can make invasive configuration
   *loud, logged, and effortful* rather than silent and default. (This is the
   adversary SAFETY.md does not have; a safety gate protects the operator's
   own hardware, a conscience gate must also consider people who are not the
   operator.)

## 2. What conscience guarantees

Stated as flatly as SAFETY.md's actuation guarantee:

> **No perception the model requests results in the capture, retention, or
> transmission of a human subject outside an explicit, operator-declared
> consent scope — and no external system is reached with credentials or
> network access outside an explicit, operator-declared reach allowlist —
> however the model was reasoned into requesting it, including via prompt
> injection or a compromised plan.**

Three mechanisms carry it.

### 2.1 The consent registry (perception gate)

A declarative table, structurally identical to SAFETY.md's `[[safety.limits]]`
and read the same way — **the model cannot write to it:**

```toml
[[conscience.subjects]]
class = "wildlife"          # subject class the deployment may perceive
capture = true
retain_days = 30
transmit = "weights-only"   # none | weights-only | frames | full

[[conscience.subjects]]
class = "human"
capture = false             # DEFAULT-DENY for humans. Full stop.
retain_days = 0
transmit = "none"
```

- **Default-deny for humans is the load-bearing default.** A deployment that
  wants to perceive humans (a doorbell, a consented eldercare body) must
  declare it explicitly, per class, with a retention bound and a transmit
  mode — the same way arming an actuator is *"an act,"* not a persisted
  ambient state.
- A perception classifier runs **before** any frame reaches the reasoner or
  storage. Detected subjects outside the allowlist are refused at capture:
  the frame is dropped, never stored, never sent to the LLM, and the refusal
  is logged (see §2.3). The model never sees what it was not permitted to
  see — so it cannot be injected by it, and cannot be reasoned into keeping
  it.
- **Fail-closed on classifier uncertainty.** If the perception gate cannot
  confidently classify a subject, it treats it as the most-restricted
  matching class (human, unless configured otherwise) and refuses. Guessing
  toward capture would launder surveillance into "we weren't sure." Per
  AGENT-MEMORY-INTEGRITY's principle: never guess *up*.

### 2.2 The reach allowlist (external-access gate)

The breach lesson, made structural. Every outbound reach — network host,
credential, tool with external effect — is gated by a declarative allowlist
the model cannot edit:

```toml
[[conscience.reach]]
host = "api.anthropic.com"      # explicit egress allowlist; default-deny
purpose = "brain"
credentials = "brain-key"       # scoped, short-lived; never "forever"

[[conscience.reach]]
tool = "mcp.clawcam"
scope = "lan-only"              # no arbitrary egress from a perception tool
```

- **Default-deny egress.** An agent with no declared reach can talk to
  nothing. Every host, every credential, every externally-effecting tool is
  opt-in, scoped, and (per the breach's central lesson) **short-lived and
  task-scoped — never standing, never `forever`.**
- **Credentials are never handed to the model.** They are referenced by
  name; the gate injects them at the egress boundary for allowlisted hosts
  only. A poisoned skill that exfiltrates a key exfiltrates a name, not a
  secret.
- **A perception tool has no general egress.** ClawCam may reach the LAN
  gateway; it may not open arbitrary sockets. The exact "camera becomes a
  launchpad" chain is refused by configuration, not by the model declining.
- **Code-execution tools are default-off and, when on, run with no reach.**
  The sandbox-escape class of failure is bounded by giving the sandbox
  nothing to escape *toward*.

### 2.3 Audited refusals

Every perception and reach decision — **taken or refused** — is written to
the same hash-chained, HMAC (optionally Ed25519) tamper-evident log
SAFETY.md defines. Refusals are first-class records: *"a bystander was
detected and the frame was dropped"* and *"a call to an un-allowlisted host
was refused"* are exactly the records that answer threat 4 and that let an
operator (or an auditor, or the subject) verify the conscience was armed and
working. A conscience that isn't audited is just a promise — and this whole
body of work exists to replace promises with structure.

## 3. What this composes with

- **AGENT-MEMORY-INTEGRITY / Origin taxonomy:** a dropped frame produces no
  memory; a permitted observation enters memory as `Observed` with its
  consent-scope stamped as provenance. "Was I allowed to see this?" and "am I
  allowed to act on this?" become the same typed question.
- **SAFETY.md / Track 0:** perception feeds foresight and missions, which
  propose actions, which Track 0 gates. Conscience gates the *front* of that
  pipeline (what enters) as Track 0 gates the *back* (what leaves as
  motion). An agent is bounded at both ends by deterministic code.
- **The spine (SPINE-AUTH):** reach-allowlisting and frame authentication are
  the same instinct at different layers — nothing enters or leaves the mesh
  unless it is named and permitted.

## 4. What conscience does NOT claim

Honesty section, in the manner of SAFETY.md §4 and §6:

- **It cannot stop an operator with physical control from surveilling.** An
  operator can rewrite the registry. Conscience makes that act explicit,
  effortful, and permanently logged — it does not make it impossible. The
  claim is *"no silent surveillance, no default surveillance, no
  model-initiated surveillance,"* not *"no surveillance."*
- **The perception classifier is a heuristic.** It will sometimes misclassify.
  The design fails closed on uncertainty precisely because it is imperfect —
  but a determined adversary and an unlucky angle can still produce a wrong
  call. It bounds the common case and the injection case; it is not a proof.
- **Semantic consent is not expressible.** "This person consented to eldercare
  monitoring but not to having a guest recorded" is beyond a class table.
  Conscience gates by declared class, not by situated understanding.
- **It does not encrypt storage or defend the host filesystem.** Retained,
  permitted footage sits under the host's protection, not conscience's.
- **No third-party certification.** This is an engineering argument, not a
  legal compliance claim (GDPR/BIPA/state biometric law are the operator's
  responsibility; conscience is a tool for meeting them, not a warranty).
- **Off by default is a real caveat, like taint-tracking in SAFETY.md.** If
  conscience ships opt-in, a deployment that never configures it has no gate.
  The strong recommendation — and the reference Bodies' default — is
  conscience armed with human-capture denied, so the safe path is the
  default path.

## 5. Reference posture (the Bodies)

- **Trailwatch** ships with `human.capture = false`, `wildlife` permitted
  weights-only — the conscience-armed default, demonstrating that a wildlife
  body cannot be quietly turned on a person without an explicit, logged
  configuration change.
- **Benchtop** declares no perception and empty reach — the null conscience,
  proving the default-deny posture is the starting point, not an add-on.

## 6. Status & open items (load-bearing)

> **Re-measured 2026-08-06.** This section was written by appending, over two
> days, and it ends by listing as open the two things it declares **done**
> a hundred lines earlier. That is not a small inconsistency in a section whose
> heading says *load-bearing*: a reader who scrolls to the bottom for "what is
> still missing" gets the opposite of the answer.
>
> Every symbol, subcommand, environment variable and test count below was
> re-derived from a `git archive HEAD` of the core repo on 2026-08-06. What held
> up: all sixteen named symbols exist, all five `OBC_*` opt-ins are read in
> `main.rs`, and the three subcommands this section calls *Runnable* are real
> (`EvalDetector`, `ReplayDecisions`, `ConsentCheck` in the clap enum — the
> kebab-case forms the text uses are what clap derives). Two of those looked
> absent on a first pass and were not; a search for `McpRegistry::build_tools_with_reach`
> finds nothing when the code says `fn build_tools_with_reach`.
>
> What did not hold up is recorded inline: the two contradicted bullets, the
> vendoring note, the running test numbers, and one function name that points at
> the wrong side of the live path.

**Built (2026-08-03):** the gate logic is now real code — the `obc-conscience`
crate (authored upstream in Oh-Ben-Claw, `cargo test -p obc-conscience`:
**43/43** as of 2026-08-06, incl. the label→class classifier). It implements the consent registry / `PerceptionGate` (default-deny
humans, fail-closed on uncertainty), the egress `ReachGate` (default-deny,
credentials-by-name, perception-tools-have-no-egress), and the
`deny_unknown_fields` `ConscienceConfig`. It mirrors `obc-safety`'s
deterministic-gate pattern exactly.

> ~~Vendoring into OBC-Prime is a follow-up via `scripts/sync_upstream.py` (the
> drift-gated copy path).~~ **Done 2026-08-06.** The crate is in `crates/` here,
> under the same SHA-256 gate as the rest, and `cargo test --workspace` in this
> repository runs its 43 tests. Until that landed, this document described a gate
> the repository carrying it could not execute — which is the failure mode the
> README's note about SAFETY.md, BELIEF-REVISION.md and MEMORY-2026-07.md
> already names.

**A note on the numbers below.** The counts quoted through this section
(`18/18`, `27/27`, `34/34`, `13/13`, `lib 904/904`, `905/905`, `919/919`,
`clawcam 23/23`, `http 6/6`, `http 7/7`) are a running log written as each piece
landed, and several are same-day contradictions of each other. Measured
2026-08-06, the current figures are: **obc-conscience 43**, obc-safety audit
module **7**, `clawcam_ingest` **25**, `tools/builtin/http` **12**, oh-ben-claw
lib **922**. The historical numbers are left in place because each one was true
when written and shows the order things arrived in; treat any of them as a
timestamp, not a status.

**Still open:**

- The perception **label→class classifier** is now built (2026-08-04):
  `obc_conscience::classifier::SubjectClassifier` maps a detector's raw label
  (`person`, `deer`, `mountain lion`) onto a broad consent class
  (`human` / `wildlife`), **fails closed** on any label it doesn't recognize
  (refused outright, never mapped onto a permitted class even on a permissive
  body), and is wired at the ingest boundary via `Conscience::may_perceive_label`
  (5 classifier tests; obc-conscience 18/18, oh-ben-claw lib 905/905). A species
  taxonomy is added via `[conscience.classifier]` config; everything unmapped
  fails closed. **Honest scope:** this maps the *labels the detector already
  emits* onto consent classes — it is NOT the computer-vision detector. Whether a
  person is labeled at all remains the upstream model's job, so the
  false-negative caveat below applies to that detector, not to this map.
- Fail-closed-on-uncertainty needs a measured false-negative rate on a real
  subject set before any human-permitting deployment is defensible. **Measurement
  harness done (2026-08-04):** `obc_conscience::detector_eval` scores a labeled
  eval set (human-annotated ground truth vs detector output, classified onto
  consent classes via the same `SubjectClassifier` the gate uses) into a per-class
  miss rate with a **Wilson 95% upper bound** — because "0 misses in 20 frames"
  is a 0% point estimate but a ~16% upper bound, and safety plans against the
  bound. The restricted class (`human`) is foregrounded; an unrecognized *detected*
  label counts as covering it (mirrors the gate's fail-closed behavior), an
  unrecognized *truth* label is excluded and reported (never fabricated into a
  present class). Runnable on real data: `oh-ben-claw eval-detector --frames
  frames.json` (sample + full collection protocol in `docs/DETECTOR-FN-EVAL.md`;
  9 tests, obc-conscience 27/27). **Still open:** the field number itself — the
  harness proves the method on synthetic frames, but a real rate needs the
  annotated deployment eval set (≥100 person-present frames spanning night / rain /
  occlusion / long range). Until then the human miss rate is *unmeasured*, not low.
- **Deterministic replay of decisions — done (2026-08-04):** both gates are pure
  functions of `(input, config)`, so a decision is replayable if the log captures
  its full input. `obc_conscience::replay` provides `DecisionRecord` (input +
  verdict + a stable FNV-1a fingerprint of the config's canonical JSON) and
  `replay()`, which re-runs each record's input through the *same* gate call the
  runtime makes and diffs the verdict. A mismatch is attributed to **config
  drift** (the record's fingerprint differs from the one replayed against —
  "refused in June, allowed today") or flagged as an **unexplained determinism
  bug** (same fingerprint, different verdict — a pure function disagreeing with
  itself). The record carries the perception confidence the refusal-only audit
  entry omits, so a decision log written from these is sufficient to replay.
  `evaluate` uses `may_reach`/`may_perceive_label`, so a disabled conscience
  replays as Allow on both gates — matching the runtime. Runnable:
  `oh-ben-claw replay-decisions --log log.json` (exits non-zero only on an
  unexplained mismatch, so it is CI-safe); sample log in
  `crates/obc-conscience/examples/`; 7 tests, obc-conscience 45/45. **Now wired
  (2026-08-04), and here (2026-08-08):** `obc_conscience::decision_log::DecisionLog`
  persists every perception
  decision (allow + refuse, with confidence — the input the audit chain omits) as
  fingerprint-stamped JSONL, opt-in via `OBC_DECISION_LOG`; the perception poll
  (`poll_clawcam_guarded`) writes to it, and `replay-decisions` reads both a JSON
  array and JSONL, so it now runs on real runtime history.

  The date pair matters. For four days this bullet said "now wired" while the
  writer lived in the private runtime as `crate::decision_log` — a path that
  resolved nowhere in this repository. The crate here defined `DecisionRecord`,
  replayed it, and computed the fingerprint, and could neither produce a log nor
  read one back; the format was specified above with nothing here to check the
  specification against. It moved into the crate on 2026-08-08 and arrived here
  the same day, with its 2 tests. `cargo test -p obc-conscience` now exercises
  the round trip — open a log, record an allow and a refusal, read it back,
  replay it — in this repository, on this page's claim.
- **Multi-party consent — done (2026-08-04):** the class gate can't express
  "Alice opted in, Bob didn't" — a per-*person* property, not a per-class one. The
  trap is that checking consent by *recognizing* people means face-recognizing
  everyone in frame, a worse surveillance capability than the one being
  constrained. Resolution (`obc_conscience::multiparty`): consent is **affirmative,
  opt-in, and keyed to a token the subject presents** (beacon/badge/code), never a
  derived identity — no token ⇒ not consented. Grants are purpose-scoped, expiring
  (`0` = already-expired, no eternal consent), and revocable, failing closed on
  every axis. `decide_frame` checks only the restricted class (wildlife needs no
  token) under `RequireAll` (any un-consented person refuses the whole frame, and
  a *count* is reported, not a "who didn't consent" list — that list would itself
  be surveillance) or `Redact` (list subjects to blank; a body that can't localize
  must treat Redact as refuse). Honest limits labeled: redaction needs
  localization; a token proves a signal is present, not that consent was freely
  given. Runnable: `oh-ben-claw consent-check --frame f.json --ledger l.json`;
  design + rationale in `docs/MULTIPARTY-CONSENT.md`; 9 tests, obc-conscience
  43/43. **Now wired into the live ingest path (2026-08-04):** `ClawCamDetection`
  gained an optional `consent_token`; `multiparty_filter` groups detections into
  frames by `event_id` and runs `decide_frame` per frame before the class gate
  (RequireAll drops the frame, Redact drops the un-consented subjects), auditing
  each as `conscience.consent`. Opt-in via `OBC_CONSENT_LEDGER`
  (+ `OBC_CONSENT_POLICY`, `OBC_CONSENT_PURPOSE`) — off with no ledger, so existing
  deployments are unchanged.
- The perception gate is now **called at the perception ingest boundary**
  (`vision/clawcam_ingest.rs`: `conscience_filter` /
  `ingest_clawcam_detections_gated`, 2026-08-03) — non-consented subjects are
  dropped before world memory and the reasoner; 4 tests, module 23/23 green in
  the real workspace.
- The reach gate is now **called at the HTTP egress boundary**
  (`tools/builtin/http.rs`: optional `ReachGate` on `HttpTool`, refuses a
  non-allowlisted host before any connection — the breach lesson; 4 tests, 6/6
  module green, 2026-08-03).
- A **`[conscience]` config section** now exists (`Config.conscience:
  ConscienceConfig`) and the reach gate is **threaded into the agent tool
  registry**: `default_tools_with_reach()` gates the HTTP tool, and `main`
  wires it when `conscience.enabled`. Whole crate builds; reach gate live at
  runtime for the agent's outbound calls (2026-08-03). Still to do: (a) apply
  the reach gate to the other egress tools (browser, comms, MCP client) and to
  the other tool registries (orchestrator, pool, MCP server) — **partly done
  (2026-08-04):** the **browser navigate** tool is now reach-gated + audited
  (`all_browser_tools_with_reach`), and the **orchestrator inner agent and its
  sub-agent pool** are gated (`InnerAgentDeps.reach` → `AgentPool::with_reach_gate`
  → `default_tools_with_reach` per spawn), so delegation is no longer an egress
  bypass; the standalone `mcp serve` tool registry is now gated too (2026-08-04) —
  tools exposed over MCP are an egress surface an external client could drive, so
  they hit the same allowlist; and the **MCP-client egress surface**
  (`McpRemoteTool`) is now reach-gated + audited too (2026-08-04) — each remote
  tool forwards its arguments to a server outside the trust boundary, so it is
  keyed on the server name (transport-agnostic: stdio subprocess and HTTP
  endpoint gated the same) and built already carrying the gate via
  `McpRegistry::build_tools_with_reach`, refusal pre-forward + on the audit
  chain. That **closes (a) (2026-08-04)**: the `comms` tool turned out to be
  link telemetry (reads + reversible world-memory appends), not an egress path,
  so it was never in scope; and the "embedded MCP-server registry" is the same
  surface as `mcp serve`, already gated. (b) inject the
  gate's named credential via the vault on allow — **implemented + live for the
  primary agent (2026-08-04):** a `CredentialResolver` seam resolves a name to
  its secret at the egress boundary and the HTTP tool injects it as a bearer
  token (the model sees the name, never the value); named-but-unresolvable
  credentials **fail closed** (refused, audited, no connection), and an
  `Authorization` header the caller set is respected. The production resolver is
  the existing encrypted `SecretsVault` via `get_or_env` (vault value first, env
  fallback), reused rather than rebuilt; `main` wires it (unlocked vault when
  `OBC_VAULT_PASSWORD` is set, else environment-only) into the primary tool
  registry when conscience is enabled. **(b) now covers every egress surface
  (2026-08-04):** the resolver is threaded to the **sub-agent surfaces** —
  orchestrator inner agent and spawned pool agents (`InnerAgentDeps.resolver` →
  `AgentPool::with_reach_gate` → `default_tools_with_reach` per spawn) — so
  delegation is not an injection bypass either; and the **MCP-client surface**
  injects at the connection boundary (MCP auth is connection-level, not
  per-call): `McpRegistry::connect_with_conscience` binds a reach-named
  credential as the HTTP bearer token (http) or an env var of that name (stdio),
  refuses an unlisted server, and fails closed on an unresolvable credential —
  a pure, unit-tested decision (`apply_conscience_to_config`). Browser needs no
  credential. `McpRegistry` is still latent (no live agent wires it), so that
  path closes the mechanism at the correct layer ahead of wiring; the per-call
  `McpRemoteTool` reach gate remains the runtime chokepoint. **(b) done.**
  `HttpTool` +7, `McpRegistry` +4 tests; lib 919/919. (c) record reach-gate
  refusals to the audit log too — ✅ **done (2026-08-04)**: the auditor is built before the tool registry and threaded into the HTTP tool, so reach refusals are audited live, exactly as perception refusals are.

**Both gates now on by default at runtime (2026-08-03):** the perception gate
is threaded into the runtime ClawCam poll (`main.rs` builds a `Conscience` per
poll; `poll_clawcam_guarded` drops non-consented detections before world memory)
and the reach gate into the agent tool registry. A deployment that sets
`[conscience] enabled = true` gets both; disabled admits everything.
Whole crate builds; clawcam module 23/23, http gate 6/6.

> Corrected 2026-08-06: this said `poll_clawcam_into_world_gated`. That function
> exists and has **no callers** — `main.rs:2230` calls `poll_clawcam_guarded`
> directly, building the `PerceptionGuard` itself, which is the whole of what
> the wrapper does. The gate is live on the runtime path either way; the
> document named the sibling nothing uses. Worth the correction rather than a
> silent edit, because "the runtime calls X" is exactly the kind of sentence a
> reader checks a safety claim against.

**Refusals are audited (2026-08-03):** `ActionAuditor::record_conscience_refusal`
writes each refusal into the same hash-chained, HMAC'd (optionally Ed25519)
tamper-evident log as physical actions — a `conscience.perception` / `.reach`
denial, non-physical. The runtime ClawCam poll records every dropped detection
there when an auditor is configured. A refusal is now a verifiable record, not
a log line — a conscience that isn't audited is just a promise. (obc-safety
audit 7/7 incl. the conscience-chain test.) The HTTP reach gate has the same
capability wired and tested (`HttpTool::with_auditor`; a refused request writes
a verifiable `conscience.reach` record — http module 7/7). **And it is now live at runtime (2026-08-04):** `main.rs` builds the action
auditor *before* the tool registry and threads it through
`default_tools_with_reach(reach, auditor)` into the HTTP tool, so a refused
outbound call writes a `conscience.reach` denial to the same tamper-evident log
as a perception refusal. The init-order refactor is done — both gates' refusals
are audited live. (Whole-workspace `cargo check` clean; obc-conscience 13/13,
obc-safety 99/99, oh-ben-claw lib 904/904.)

- ~~No deterministic replay of perception decisions yet (mirrors SAFETY.md's
  replay gap).~~ **Contradicted by this same section and removed 2026-08-06.**
  Replay landed 2026-08-04 — `obc_conscience::replay`, 7 tests, and
  `replay-decisions` reads the JSONL the runtime poll writes. This bullet
  survived the commit that made it false because the update was appended above
  it instead of replacing it.
- ~~Operator-overreach (adversary 5) is only partially addressed; a
  multi-party consent scheme (the subject, not just the operator, attests) is
  research, not design.~~ **Also contradicted and removed 2026-08-06.**
  Multi-party consent landed 2026-08-04 — `obc_conscience::multiparty`, 9 tests,
  token-presented rather than identity-derived, wired into the ingest path
  behind `OBC_CONSENT_LEDGER`.

  What is *still* true about adversary 5, and worth keeping rather than
  deleting: consent tokens make invasive configuration loud, logged and
  effortful; they do not stop an operator with physical control, and a token
  proves a signal is present, not that consent was freely given. §4 says this
  and remains accurate.

**Genuinely open, as of 2026-08-06:**

- **The measured false-negative rate.** The harness is done; the field number is
  not. Until an annotated deployment eval set exists (≥100 person-present frames
  across night / rain / occlusion / long range), the human miss rate is
  *unmeasured*, not low. This is the one item on the page that no amount of
  code closes.
- **`poll_clawcam_into_world_gated` has no callers.** The "Both gates now on by
  default" paragraph above said the runtime perception path is that function. It
  is not — `main.rs:2230` calls `poll_clawcam_guarded` directly and builds the
  `PerceptionGuard` itself, which is all the wrapper does. The gate *is* live on
  the runtime path; the document named the unused sibling. Corrected above, and
  the function itself is flagged upstream for a keep-or-cut decision.

---

*The one-line version, in the house style: an observation of a non-consenting
human, or a reach to an un-allowlisted system, is refused by deterministic
code the model cannot override — before the frame reaches the reasoner and
before the credential reaches the wire — and every such decision is written
to a tamper-evident log. The model is not the conscience.*
