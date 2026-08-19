# Safety architecture

How Open Body Control stops a language model from doing something physical that
it shouldn't.

This document describes what is implemented, what is opt-in, and what is not
covered. Where a control has a limit, the limit is stated. Nothing here is
aspirational — every mechanism below was read out of the source, and the gaps in
§6 are as load-bearing as the guarantees in §2.

> **Status:** the core agent is not yet public. This document describes its
> architecture so the design can be reviewed and argued with before the code
> lands. Paths refer to the core repository.

---

## 1. The threat model

An always-on agent with physical actuators has four distinct adversaries, and
they need different controls:

| # | Threat | Realistic form |
|---|---|---|
| 1 | **The model is wrong** | A hallucinated tool call, a misread sensor, a plan that made sense in context and not in the world |
| 2 | **The model is manipulated** | Text in a camera frame, a poisoned document, an injected instruction arriving through perception |
| 3 | **A component is compromised** | A malicious skill, a tampered host, a hostile MCP server |
| 4 | **The record is disputed** | Something happened; nobody can prove what the agent decided or why |

The central design commitment is that **threat 1 and threat 3 are the same
problem**. A safety control that trusts the host process is worthless against a
compromised host, and a control that trusts the model is worthless against a
confabulating model. So the enforcement that matters does not live in either.

---

## 2. What is implemented

### 2.1 A deterministic gate the model cannot influence

`src/security/limits.rs`

The agent's LLM decides *what* to do. A separate, fixed-rule gate decides
whether a physical action is *allowed*. The gate contains no model, no
heuristics and no natural language — only a table:

```toml
[[safety.limits]]
node_id        = "obc-esp32-s3-001"
tool           = "gpio_write"
allowed_pins   = [12, 13]     # default-deny: a list present means only these
value_min      = 0
value_max      = 1
min_interval_ms = 500         # per (node, tool, pin)
```

**`[safety]` rejects unknown keys, and that is deliberate.** Every other config
section tolerates stray keys. This one must not: a typo here does not degrade a
feature, it silently removes an enforcement control while startup still logs the
gate as active.

That is not hypothetical. Documentation across the core repo wrote this table as
`[[safety.limit]]` — singular — while the field is `limits`. Serde ignored the
unknown key, the agent logged `Track 0 safety gate active limits=0`, and the
gate enforced nothing. Anyone who configured a limit table from the
documentation got a gate that reported itself armed and was not. The section now
fails to parse instead, with a line and column.

Three checks, in order: pin allow-list, value range, rate limit. A violation
returns a typed `SafetyViolation` (`PinNotAllowed`, `ValueOutOfRange`,
`RateLimited`) — not a string, so callers can branch on it and the audit record
can carry the reason verbatim.

**The important limitation, stated plainly:** if no rule covers a
`(node, tool)` pair, the gate **allows** the action and defers to the approval
layer (§2.3). The gate is default-deny *within* a rule and fail-open *across*
rules. That is a deliberate choice — a gate that denied every uncovered tool
would make the agent unusable and would push operators to disable it — but it
means **the gate protects exactly what you have configured and nothing else**.
An unconfigured actuator is governed only by approval and autonomy policy.

### 2.2 The same table enforced on the microcontroller

`firmware/.../safety.rs`, wired at `firmware/.../main.rs`

The limit table is mirrored to each node over the spine
(`obc/nodes/{id}/limits`) and enforced *again* on the ESP32-S3, by an on-MCU
`SafetyGate` constructed with that board's output pins. Both the host-command
path and the node's own local reflex path go through it.

This is the property worth stating clearly, because it is unusual: **a
compromised host, a poisoned skill, or a hallucinated tool call still cannot
drive an actuator outside the limits the node itself holds.** The host is not in
the trusted computing base for bounds enforcement. Compromising the agent gets
you the agent; it does not get you the actuator.

Both halves of that sentence are now in this repository and can be run against
each other. `obc-safety` brought the gate on 2026-08-01; `obc-movement` brought
the caller on 2026-08-08. The order inside `MovementController` is gate →
remember → dispatch: the limit check runs first and returns early, so a refused
command never reaches a sink *and* is never written to world memory as a
commanded state. Until then this page described a check whose only caller lived
in a repository you could not read. It was true; you had to take it on faith.
`cargo test -p obc-movement` is the version you do not.

Worth naming the gap that remains: a refusal leaves no trace here. The
`MovementError::Safety` goes back to the caller, and whether it reaches the
tamper-evident audit chain depends on that caller, which is still upstream. The
gate refuses; this crate does not record that it refused.

The published safety literature for LLM-driven robots converges on a two-tier
architecture — an untrusted planner plus a trusted non-LLM enforcer. RoboGuard
([arXiv:2503.07885](https://arxiv.org/abs/2503.07885), RA-L Feb 2026) compiles
written rules to Linear Temporal Logic and reduces unsafe plan execution from
>92% to <3% under jailbreak, on the principle that *the LLM never emits the final
action, only constraints a verifier consumes*. RoboSafe
([arXiv:2512.21220](https://arxiv.org/html/2512.21220v1)) compiles safety
knowledge to executable predicates checked before every action.

Those systems place the enforcer in a separate *process*. OBC places it in a
separate *device*, and keeps the host-side copy as a first line so violations are
caught and audited before they reach the wire.

### 2.3 Risk-typed approval

`src/tools/traits.rs`

Every tool declares a risk class:

```rust
pub struct RiskClass {
    pub reversible: bool,      // can this be cleanly undone?
    pub blast: BlastRadius,    // None | Low | ... — real-world reach
    pub physical: bool,        // does it drive an actuator?
}
```

Ordinary tools default to `RiskClass::safe()` (non-physical, reversible,
`BlastRadius::None`). Tools that touch the world override it. The approval layer
uses the class to set default scopes: **irreversible or high-blast actions
default to per-call approval and can never be auto-granted `forever`.** Grant
scope is a function of declared risk, not of operator convenience.

Mutating gateway calls additionally require a separate `X-OBC-Operate` header
beyond the ordinary API token, so a read-only credential cannot actuate.

This vocabulary does not exist anywhere in MCP. MCP's tool annotations —
`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint` — carry no
physical semantics (no reversibility class, blast radius, velocity bound,
geofence, dwell time or energy budget), and the specification requires clients to
treat them as **untrusted**. The
[2026 MCP roadmap](https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/)
does not mention robotics or physical systems.

### 2.4 Taint tracking: perception is data, not instruction

`src/security/taint.rs`, config `safety.taint_mode = "off" | "warn" | "enforce"`

The provenance guard refuses a privileged call whose **argument values echo
untrusted external content**, unless the tool is explicitly operator-granted.
`warn` logs and counts; `enforce` refuses.

This is the control that addresses threat 2, and it is the one with the
strongest empirical case. **CHAI** (IEEE SaTML 2026, UC Santa Cruz + JHU)
demonstrates physical command-hijacking using nothing but text placed in the
environment: **95.5%** success against aerial object tracking, **81.8%** against
driverless cars, targeting GPT-4o and InternVL. **AttackVLA**
([arXiv:2511.12149](https://arxiv.org/html/2511.12149)) reports 100% untargeted
disruption on OpenVLA.

Surveys of embodied agent security as of mid-2026 note that no embodied analogue
of CaMeL-style capability isolation is shipping. Taint tracking is a step toward
one. It is **opt-in and off by default**, which is the honest caveat: the control
exists, most deployments will not have it on, and `warn` is the sensible first
setting because `enforce` will refuse legitimate calls until the taint sources
are tuned.

### 2.5 Dynamic trust scoring

`safety.dynamic_trust = true`

A node behaving anomalously — latency spikes, failures — is demoted and its
physical actions refused. This composes with, and does not replace, the
deterministic limits. It is a liveness/anomaly control, not a security boundary:
it will catch a failing node, not a patient attacker.

### 2.6 A tamper-evident record of every physical action

`src/security/audit.rs`, `src/security/audit_sign.rs`

Every world-changing action the agent takes **or is refused** is appended to a
JSONL log as a hash-chained, MAC'd record:

```
mac = HMAC-SHA256(key, seq | ts | node | tool | args_sha256 | decision | prev_mac)
```

Each record carries the previous record's MAC. Any insertion, deletion,
reordering or edit breaks the chain and is caught by `verify`. Arguments are
recorded as a SHA-256 rather than in the clear, so the log proves *what was
requested* without becoming a secondary disclosure risk.

`Decision` is a three-valued enum — `Allowed`, `Denied(reason)`,
`NeedsApproval` — so **refusals are first-class records**. A log that only
contains what happened cannot answer "did the gate ever stop anything?"

Optionally, an `AuditSigner` adds an **Ed25519 detached signature** over the same
canonical fields, so a third party can verify the log with only the public key
and no access to the MAC secret. `verify_signatures` returns the count of signed
records verified and errors on the first bad signature; unsigned legacy records
are skipped and remain covered by the HMAC chain.

The only open standardisation attempt in this space, IETF
[draft-sharif-agent-audit-trail-00](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/)
(29 Mar 2026), proposes the same architecture — SHA-256 `prev_hash` chaining over
canonical JSON, optional detached signatures — and **explicitly excludes physical
actuation**, covering only tool_call / decision / delegation / escalation. In
robotics the practical stack remains rosbag2 plus SROS2, and rosbag is not
tamper-evident.

### 2.7 Reflexes that do not need the model

Rule-driven reflexes evaluate sensed state on a fast loop and act or escalate
without waking the language model. The safety-relevant property is that the
reactive path does not depend on model availability, latency or correctness — if
the model is down, wedged, or wrong, safing rules still fire.

Escalation to the slow reasoner is rate-capped and novelty-gated, so a noisy
sensor cannot drive unbounded model invocations.

Each escalation carries a triage directive naming the playbook that expands it.
Those three playbooks are in [`playbooks/`](playbooks/README.md) — vendored from
the core repo from 2026-08-02, because the reference bodies were already citing
them by path and the path resolved to nothing here.

---

## 3. How to turn it on

The gate and the audit log are **opt-in and disabled by default**. A deployment
without a `[safety]` section has no deterministic gate and no action audit; it
is governed only by approval scopes and autonomy level.

```toml
[safety]
enabled        = true
# audit_log_path: leave unset. It defaults to an absolute path in the data dir.
# A relative value is resolved against the *working directory*, so the log would
# follow wherever the agent was launched from — a tamper-evident log that can
# silently fork into several files is not one.
audit_key      = "..."                  # falls back to the pairing secret, then a dev key
dynamic_trust  = true
taint_mode     = "warn"                 # start here; move to "enforce" once tuned

[[safety.limits]]
node_id         = "obc-esp32-s3-001"
tool            = "gpio_write"
allowed_pins    = [12, 13]
value_min       = 0
value_max       = 1
min_interval_ms = 500
```

Confirm it took. The limit count is in the startup log and is the only way to
know the table parsed:

```
Track 0 safety gate active limits=1        # not 0
Track 0 action audit log active path=action_audit.jsonl
Track 0 dynamic trust scoring enabled
Track 0 taint tracking enabled mode=Warn
```

### What the gate actually covers

The gate is consulted on **node/peripheral commands** — calls carrying a
`(node, tool, channel/pin, value)` shape, at `agent/mod.rs` and in the
peripheral command path. `gpio_write` on a physical node is the archetype.

MCP tools without pin/value semantics (`capture_now`, `set_device_state`) are
**not** covered by the limit table; they are governed by risk class, approval
scope and the operate tier, and they *are* recorded in the action audit. Do not
write limits for them expecting enforcement.

### Verifying the log

There is **no CLI yet** — verification is currently a library call
(`security::audit::verify`, `verify_signatures`). That is a real gap for anyone
operating this rather than developing it, and it is tracked.

The format is deliberately simple enough to verify independently, which is the
point of publishing it. A third party needs only the key and ten lines:

```python
import hashlib, hmac, json

prev, key = "GENESIS", open("audit.key","rb").read()
for line in open("action_audit.jsonl", encoding="utf-8"):
    r = json.loads(line)
    canon = "|".join([str(r["seq"]), str(r["ts_ms"]), r["node_id"], r["tool"],
                      r["args_sha256"], json.dumps(r["decision"], separators=(",",":")),
                      prev])
    assert r["prev_mac"] == prev, f"chain broken at seq {r['seq']}"
    assert hmac.new(key, canon.encode(), hashlib.sha256).hexdigest() == r["mac"], \
        f"bad MAC at seq {r['seq']}"
    prev = r["mac"]
```

If that script passes, no record has been inserted, deleted, reordered or
edited since it was written.

**Set `audit_key` explicitly.** The fallback chain ends at a development key,
which provides tamper-*evidence* against accident but not against an adversary
who knows the default.

---

## 4. What this does not protect against

Stated because a safety document that only lists strengths is marketing.

- **Semantic safety.** The gate enforces physics — pins, ranges, rates. It has no
  opinion on whether an in-bounds action is a *good idea*. "Don't actuate this
  while a person is in the room" is not expressible today. Nobody has solved
  this: the published state of the art either checks physics with hard maths or
  checks meaning with another language model, and the second is not a verifier.
- **Uncovered tools.** See §2.1. No rule means no gate.

- **Perception content in the planning path.** Taint tracking guards tool
  *arguments*. Text recovered from an image by `vision_analyze` still reaches the
  reasoner as prose. Nothing currently strips or sandboxes OCR'd instructions.
- **Stale beliefs.** World memory is bitemporal but nothing invalidates a fact
  when its source goes away. A fact asserted by a sensor that has since been
  unplugged stays current indefinitely, and reflexes will keep acting on it. This
  has caused real false alerts in a live deployment. See
  [RESEARCH-2026-07.md §2.1](RESEARCH-2026-07.md).
- **Replay.** The audit log records decisions, not enough state to deterministically
  re-derive them. You can prove what the agent did; you cannot yet re-run why.
- **Tail reliability.** No published embodied benchmark — SafeAgentBench,
  ASIMOV-2.0, RoboArena — reports what it would take to demonstrate a 10⁻⁶
  failure rate, which is what IEC 61508 / ISO 13849 performance levels demand.
  Neither does this project. Nobody should claim a performance level here.

---

## 5. Regulatory position

For a hobbyist or research deployment this is essentially unregulated: the EU
Machinery Regulation binds *placing on the market*, and AI Act Art. 2(12) exempts
free and open-source AI. That exemption does **not** survive selling a unit,
offering a hosted service, or a high-risk classification.

Dates that matter if this ever becomes a product:

| Instrument | Applies |
|---|---|
| EU AI Act Art. 50 transparency | 2 Aug 2026 (watermarking grace to 2 Dec 2026) |
| Revised Product Liability Directive (EU) 2024/2853 | products placed on market from 9 Dec 2026 — explicitly covers software and post-market updates, no open-source carve-out once distributed commercially |
| EU Machinery Regulation 2023/1230 | 20 Jan 2027 — self-evolving safety behaviour is Annex I high-risk, notified body required |
| AI Act high-risk, safety component of a product | 2 Aug 2028 (deferred by the Digital Omnibus, May 2026) |

Relevant standards: **ISO 10218-1/-2:2025** (Feb 2025, first revision since 2011,
adds safety-related cybersecurity), **ISO/IEC TR 5469** (functional safety + AI),
**ISO/PAS 8800:2024**. **No harmonised standard has been published in the OJEU
for any AI Act obligation** — presumption of conformity does not currently exist.

ISO 21448 (SOTIF) is the closest fit for the failure mode that matters here —
hazard from performance insufficiency without a fault — but it presumes you can
enumerate triggering conditions, which an open-vocabulary policy defeats. That
gap is unfilled by any published standard.

---

## 6. Reporting a vulnerability

See the security policy in the upstream repo,
[Oh-Ben-Claw/SECURITY.md](https://github.com/thewriterben/Oh-Ben-Claw/blob/main/SECURITY.md)
— the agent it covers is the one that actuates hardware, and it is developed
there. Please do not open a public issue for anything that would let someone
actuate hardware they do not own.

> This said `[SECURITY.md](../SECURITY.md)` until 2026-08-02. There is no
> `SECURITY.md` in this repository; the link was written against the upstream
> tree and pointed at nothing here from the day the file arrived. Found by
> resolving every relative link in a `git archive` export rather than reading
> them.

---

## Appendix: design decisions and why

**Why is the gate fail-open across rules?** A gate that denied every uncovered
`(node, tool)` would be correct and unusable, and operators would disable it
wholesale — trading a partial control for none. Fail-open across rules with
default-deny within a rule keeps the control adoptable. The mitigation is that
approval and autonomy still apply to uncovered tools, and the audit records the
uncovered call either way.

**Why HMAC before signatures?** A symmetric chain is verifiable by the key holder
with no key-management story at all, which means it actually gets enabled.
Ed25519 signing is additive on top for third-party verification, and the record
shape does not change between them.

**Why record refusals?** A log containing only successful actions cannot
distinguish "the gate never fired" from "the gate was never on". `Denied` and
`NeedsApproval` records are the evidence that the control is live.

**Why hash the arguments instead of storing them?** Tool arguments can contain
credentials, personal data, or images. A SHA-256 proves what was requested if you
have the original, without the log itself becoming a disclosure risk.

**Why is taint tracking off by default?** `enforce` will refuse legitimate calls
until taint sources are tuned for a given deployment, and a safety control that
gets switched off in frustration is worse than one introduced deliberately in
`warn`. This is a real tradeoff, not a good one — the honest position is that
it should become default-`warn` once the false-positive rate is measured.
