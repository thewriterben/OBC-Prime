# Where OBC sits in embodied AI — July 2026

A field survey against the actual codebase, not against the pitch. Every claim
about OBC below was checked in source during the review; every claim about the
field carries a citation.

---

## The thesis, up front

The embodied-AI field in 2026 is **bifurcated**, and the split is the opportunity.

On one side: continuous-control **VLAs for a single manipulator**. π0.7, GR00T
N1.7, RDT2, SmolVLA, Gemini Robotics 1.5. Every "cross-embodiment" claim in this
literature means *different arms* — GR00T's relative end-effector space,
Gemini's Motion Transfer, LingBot's nine dual-arm configs. The April 2026 edge
survey of VLA deployment contains **no discussion of multi-robot coordination at
all**.

On the other side: **text-to-API agents for buildings**. SMH-Bench (Jun 2026)
evaluates smart-home agents across 135 devices and 31 nested rooms — via
structured API calls, with no vision, no proprioception, no continuous action
space, no reflexes.

Nobody occupies the middle: **a persistent agent commanding a heterogeneous mesh
of cheap nodes, with sensing, memory and physical actuation, running
unattended.** That is exactly what OBC is. This is not a gap I invented to
flatter the project — I went looking for who serves it and found the two camps
above and a vacuum between them.

The strategic risk is the opposite of what you'd expect. OBC's danger is not
that it's behind on model quality. It's that it has quietly built several things
the 2026 literature calls open problems, **has not named them, and is therefore
invisible**.

---

## 1. What OBC already has that the field is still asking for

Verified in source. This section is the surprising one.

### 1.1 A non-LLM enforcement layer between the model and the motors

`src/security/limits.rs` opens with:

> *"The agent's LLM decides what to do; this gate decides whether a physical
> action is allowed — using fixed rules the model cannot influence. It is the
> host-side mirror of the on-MCU `SafetyGate` in the ESP32-S3 firmware: the same
> limit table is enforced in both places so a compromised host, a poisoned
> skill, or a hallucinated tool call still cannot drive an actuator out of
> bounds."*

The 2026 safety consensus is a two-tier architecture: an untrusted planner plus a
trusted non-LLM enforcer. **RoboGuard** (arXiv:2503.07885, RA-L Feb 2026)
compiles rules to Linear Temporal Logic and cuts unsafe execution from >92% to
<3% under jailbreak; its central claim is that *the LLM never emits the final
action, only constraints a verifier consumes*. **RoboSafe**
(arXiv:2512.21220) compiles safety knowledge to executable predicates checked
before every action.

OBC does this, **and enforces the same limit table on the microcontroller as
well as the host**. That is stronger than the published pattern, which assumes a
separate process; OBC uses a separate *device*. Default-deny pin allow-lists,
value ranges, per-`(node, tool)` rate limits, plus dynamic trust scoring that
demotes a node behaving anomalously and refuses its physical actions.

I could not find a published open-source LLM-robotics system with dual-location
deterministic enforcement. Not one of the MCP-robotics servers surveyed
(`ros-mcp-server`, 1.4k stars, the de facto leader) has a mandatory confirmation
workflow at all.

### 1.2 A tamper-evident audit chain for *physical* actions

`src/security/audit.rs`: HMAC-SHA256 chained over
`seq | ts | node | tool | args_sha256 | decision | prev_mac`, with optional
Ed25519 detached signatures so third parties can verify without the secret.

The only open standardisation attempt is IETF
**draft-sharif-agent-audit-trail-00** (29 Mar 2026): SHA-256 `prev_hash`
chaining over RFC 8785 canonical JSON, optional ECDSA P-256. It **explicitly
does not cover physical actuation** — its action types are
tool_call/decision/delegation/escalation.

So OBC has implemented the draft's architecture *in the dimension the draft
omits*. The robotics field's practical stack is rosbag2 plus SROS2, and rosbag
is not tamper-evident. There is no standard schema binding reasoning trace →
safety verdict → commanded actuation → measured outcome into one signed record.
OBC is most of the way to being that schema.

### 1.3 A physical risk vocabulary

`RiskClass::physical(reversible: bool, BlastRadius)`, with `requires_per_call`,
surfaced through approval grants and an operate-token elevation tier.

MCP's tool annotations — `readOnlyHint`, `destructiveHint`, `idempotentHint`,
`openWorldHint` — carry **no physical semantics**: no reversibility class, no
velocity bound, no geofence, no dwell time, no energy budget. The spec requires
clients to treat them as *untrusted*. The
[2026 MCP roadmap](https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/)
does not mention robotics or physical systems anywhere.

### 1.4 Bitemporal, provenance-tagged world memory

`src/memory/world.rs` carries `valid_from`/`valid_to` (when it was true) plus
`ingested_at` (when we learned it), and an `Origin` type distinguishing
observation from assertion — with an explicit design note that consumers declare
the *set* of origins they accept, never a threshold.

This is the substrate DAAAM (CVPR 2026) reaches for with append-and-timestamp
fragment histories, and the missing ingredient in the memory-contamination
literature below. Most agent memory systems overwrite; OBC closes and appends.

### 1.5 A System 1 / System 2 split that actually runs

Reflex rules firing at 1 Hz without waking the model, escalating with a triage
playbook, novelty-windowed and wake-budgeted.

The field converged on exactly this: Figure's **Helix 02** (Jan 2026) runs S2 at
7–9 Hz over S1 at 200 Hz, with a new 10M-param S0 at 1 kHz; Gemini Robotics
splits ER (reasoning) from VLA (acting); NanoVLA routes dynamically. OBC has the
same architecture at a different timescale, for a distributed sensor mesh rather
than a manipulator.

**Summary: on safety architecture, auditability and risk vocabulary, OBC is
ahead of the published open-source state of the art. It just hasn't said so.**

---

## 2. Table-stakes gaps — fix these to be credible

### 2.1 Nothing invalidates stale facts *(highest priority, already causing harm)*

I grepped `world.rs` for retract / invalidate / stale / ttl. **Zero matches.** A
fact opens and stays open forever unless a newer observation of the same entity
closes it.

We hit this live during setup. A `mesh.escalated_count >= 1` written during a
bench session in July stayed open for weeks, and the `safe-mesh-node-lost` reflex
correctly and continuously fired on hardware that had been unplugged — a
critical alert about nothing, several hundred times, plus repeated System 2
wakes. It cost real debugging time and I initially misdiagnosed it as a rule
defect and disabled a safety rule to work around it. That was the wrong fix.

This is a textbook instance of a named 2026 failure mode.
**arXiv:2605.17830** (May 2026) measures *temporal memory contamination* with
**no adversary present**: broad-retrieval memory architectures reach violation
rates of **0.3–0.5**, versus 0.1–0.2 for short-term memory. Mechanisms named:
cross-context leakage, **stale information overriding corrections**, and
summarisation producing claims exceeding any source. A retrieval-time monitor
achieves 0.970–0.984 recall.

OBC has the bitemporal schema to fix this properly and does not use it. Needed:
per-entity freshness policy (TTL or explicit close-on-source-loss), a
retrieval-time staleness monitor, and reflex conditions that can require
recency. **This is both the most embarrassing bug and the clearest research
contribution available** — see §3.1.

### 2.2 Escalation gating is uncalibrated

OBC gates System 2 wakes with a novelty window and an hourly cap. Reasonable, but
not what the evidence supports.

**arXiv:2605.18045** (May 2026) is a strong negative result: across seven
uncertainty estimators — softmax heuristics, MC-dropout entropy, epistemic
variance, ensembles — *estimator choice barely matters* (Spearman ρ clusters at
0.264–0.300, 97.8–99.5% act/defer agreement). **Threshold choice dominates**:
restricting to the top-10% most confident cut error from 36.5% to 19.9%.
Fine-grained semantic OOD detection was **at chance** (AUROC 0.35–0.49).

**arXiv:2606.10267** (Jun 2026) adds: a **success/termination detector beats both
fixed-frequency and VLM-predicted termination**; moderate detector error is
tolerable; 4–8 s fallback horizons are the sweet spot; **observations as text +
bounding boxes beat raw images**; cross-episode memory helps, in-episode history
is near-useless. Hierarchy matters enormously — 67.08% vs 40.56% naive vs 25.30%
flat.

Actions: don't build an exotic novelty detector; sweep thresholds and log them.
Add a success/termination detector. Feed System 2 structured text plus bounding
boxes, not prose.

### 2.3 No spatial memory

`site_anchor`, `gnss_fix` and `clawcam_spatial` exist, but there is no scene
graph — no object-centric persistent memory, no "what did I see, where, and
when" query.

**DAAAM** (arXiv:2512.00565, CVPR 2026, MIT-SPARK, **BSD-3**) is the current best
practice and is directly adoptable in architecture if not in code: hierarchical
4D scene graph, object fragments whose descriptions are appended, timestamped and
**preserved on merge**, geometry decoupled from semantics — 10 Hz tracking online
with batched semantic lifting, a set-cover frame selector cutting VLM queries
**~10×**. Result: 11.6 Hz on an RTX 5090 versus ConceptGraphs at 0.075 Hz;
OC-NaVQA accuracy 0.711 vs 0.299.

Reality check before over-investing: **FindingDory** (arXiv:2506.15635) shows
GPT-4o at **27.3%** and near-zero on multi-goal embodied memory tasks. This is
not solved by anyone.

### 2.4 Perception is an unguarded attack surface

OBC folds `vision_analyze` output and MCP detection payloads into world memory,
which drives reflexes, which wake System 2 with text. Any text an attacker can
get into a camera frame is a potential instruction path.

**CHAI** (IEEE SaTML 2026, UC Santa Cruz + JHU) demonstrates physical
command-hijacking with text placed in the environment: **95.5%** success on
aerial object tracking, **81.8%** on driverless cars, against GPT-4o and
InternVL. **AttackVLA** reports FreezeVLA at 95.4% and 100% untargeted
disruption on OpenVLA.

And the mundane threat is worse: **CVE-2026-27509/27510** (Unitree Go2, patched
24 Feb 2026) — unauthenticated DDS domain 0 publish giving root RCE with physical
actuation, persistent across reboot.

Actions: treat every perceived token as data, never instruction; strip or
sandbox OCR'd text before it reaches the planning path; keep the spine
authenticated. OBC's `p2p`/MQTT spine currently has no auth story.

### 2.5 Skill library rot is unaddressed

`skill_forge/rollout.rs` has promote/demote with clean-run counting. Good. It
lacks merge, retire, validators and description-space deduplication.

**arXiv:2605.24050** (May 2026): expanding to a 202-skill library costs **~21%
pass rate**, and **skill shadowing explains up to 68%** of that loss — context
overhead is statistically indistinguishable from noise. One agent selected
`video-frame-extraction` in **26/26** trajectories because its description
matched better. **SkillOps** (arXiv:2605.13716) shows five rule-based ops —
merge, repair, retire, add_validator, add_adapter — reach 79.5% on ALFWorld
(+8.8pp) at near-zero LLM cost.

---

## 3. Where OBC can be genuinely novel

Ranked by (contribution × feasibility ÷ competition).

### 3.1 Provenance-aware staleness arbitration for embodied memory ★ best bet

The open problem: when the world changes, which remembered facts are still
admissible? DAAAM appends history but does not arbitrate stale-vs-current.
arXiv:2605.17830 measures the damage and proposes only a retrieval-time monitor.
Nobody has published invalidation semantics tied to *source liveness* — the fact
that the sensor which asserted something has since gone away.

OBC is unusually well positioned: it already has valid-time, transaction-time,
`source` and `Origin`. The missing piece is a policy layer — per-entity
freshness, close-on-source-loss, recency-requiring reflex conditions, and a
monitor that flags facts whose asserting source is no longer live.

And OBC has the motivating failure in its own logs, with a measured cost. That is
a publishable artifact: *a bitemporal fix for a named contamination failure mode,
demonstrated on a real deployment.*

### 3.2 A physical-actuation authority profile over MCP ★ clearest white space

MCP `2026-07-28` — the spec version finalising **today** — removes the
initialization handshake and session IDs; client info moves into per-request
`_meta`. The tools spec states plainly: *"the protocol has no concept of a state
handle,"* recommending opaque handles the **model** carries forward.

For a shopping cart that is fine. For a moving actuator, **the session is the
safety context** — exclusive ownership, e-stop latch, arbitration. A model that
forgets a handle is a safety incident. Sampling, Roots and Logging are all
deprecated in the same release.

The counterweight: **elicitation survived and improved**. Multi-round-trip
requests return `resultType: "input_required"` with `requestState`, and the
client retries with `inputResponses` — a genuinely usable confirm-before-actuate
primitive that works without a sticky stream. **It has zero robotics users
today.**

The contribution: publish an **MCP profile for physical actuation** — a risk
vocabulary with real physical semantics (reversibility class, blast radius,
velocity/force bound, geofence, dwell, energy budget, preemption rights), a
lease/arbitration model for "who owns this actuator until when", and the MRTR
elicitation flow as the confirm gate. OBC already has two-thirds of the
vocabulary shipping. Don't fork MCP — profile it.

### 3.3 Deterministic replay and a signed decision record

No published system can replay why an embodied agent acted: VLA nondeterminism
(sampling temperature, async chunking) defeats it. OBC's audit chain already
records the hard part. Extend the record to prompt hash, model + weights hash,
sampled action, safety verdict and reason, commanded and measured state, and RNG
seed — then demonstrate byte-exact replay. Contribute physical action types
upstream to the IETF draft.

### 3.4 A safety-case template for open-vocabulary policies

ISO 21448 (SOTIF) presumes you can enumerate triggering conditions; for an
open-vocabulary policy you cannot. ISO/IEC TR 5469 and ISO/PAS 8800 give
structure but no template. **No harmonised standard has been published in the
OJEU for any AI Act obligation** — JTC 21 has ~7 deliverables in progress, none
past stage 60.

OBC's dual-location deterministic gate is a *strong* safety argument. Writing it
up as a reusable safety case would be a real contribution to a genuinely empty
space — and costs nothing but prose.

---

## 4. What not to build

- **A VLA.** π0.6/π0.7 weights aren't released; GR00T N1.7 needs 16 GB inference
  and 40 GB fine-tune; openpi is 8 GB inference but **22.5 GB for LoRA**. On a
  12 GB RTX 5070 you can run but not adapt. If you ever need a policy, use
  **SmolVLA** (450M, Apache-2.0, ~2 GB) — the only one you can both run and
  fine-tune locally.
- **Pixel-space world-model planning.** Action-inconsistent futures and
  long-horizon drift are unsolved at frontier compute. If world models enter,
  use them as *verifiers* — arXiv:2605.06222 gets 69.1% fewer forward passes and
  45%→80% real-robot success by gating on prediction error.
- **A simulator** (Genesis, 29.7k stars), **datasets** (LeRobot, 58k on the Hub),
  **low-level real-time control** (`ros2_control`), or **humanoid hardware** —
  K-Scale Labs shut down 4 Nov 2025 and open-sourced everything after a price
  war.
- **Your own agent-to-agent protocol.** A2A hit 150+ organisations under the
  Linux Foundation; IBM's ACP wound down into it. Zero embodied adoption yet,
  which is an opportunity to *use* it, not to replace it.

---

## 5. Suggested order

1. **Staleness arbitration** (§2.1 → §3.1). Fixes a live bug, and it's the
   research contribution. Start with close-on-source-loss and a recency
   predicate for reflex conditions.
2. **Perception hardening** (§2.4). Cheap, and the CHAI numbers make it
   indefensible to skip. Sandbox OCR'd text; authenticate the spine.
3. **Name and document what already exists** (§1). The dual-location safety gate
   and the physical audit chain are the strongest things in the codebase and are
   undocumented. Write `docs/SAFETY.md`. This is the cheapest credibility in the
   whole plan.
4. **Threshold-calibrated escalation + success detector** (§2.2).
5. **Skill hygiene** (§2.5) — SkillOps' merge/retire/validate are rule-based and
   nearly free.
6. **The MCP physical-actuation profile** (§3.2) — write it as a spec document
   with OBC as the reference implementation.
7. **Spatial memory** (§2.3), last. Highest effort, and the field's own numbers
   say it's unsolved.

---

## Sources

Field state: [ICLR'26 VLA review](https://mbreuss.github.io/blog_post_iclr_26_vla.html) ·
[π0.7](https://www.pi.website/blog/pi07) · [openpi](https://github.com/Physical-Intelligence/openpi) ·
[Gemini Robotics 1.5](https://arxiv.org/abs/2510.03342) · [GR00T N1.7](https://github.com/Nvidia/Isaac-GR00T) ·
[SmolVLA](https://huggingface.co/docs/lerobot/smolvla) · [Helix](https://www.figure.ai/news/helix) ·
[LeRobot async](https://huggingface.co/docs/lerobot/async) · [TinyVLM](https://arxiv.org/html/2603.00136v1) ·
[ESP-DL](https://github.com/espressif/esp-dl) · [SMH-Bench](https://arxiv.org/html/2606.01912)

Memory/architecture: [DAAAM](https://arxiv.org/html/2512.00565v1) · [Hydra](https://arxiv.org/abs/2201.13360) ·
[FindingDory](https://arxiv.org/html/2506.15635) · [temporal memory contamination](https://arxiv.org/html/2605.17830v1) ·
[skill shadowing](https://arxiv.org/html/2605.24050v1) · [SkillOps](https://arxiv.org/html/2605.13716v1) ·
[confidence-gated autonomy](https://arxiv.org/abs/2605.18045) · [orchestrating robot policies](https://arxiv.org/html/2606.10267v1) ·
[when to trust imagination](https://arxiv.org/abs/2605.06222) · [RECAP/π*0.6](https://arxiv.org/html/2511.14759v1) ·
[embodied collective intelligence](https://arxiv.org/html/2606.27929)

Safety/standards: [RoboGuard](https://arxiv.org/abs/2503.07885) · [SafeVLA](https://arxiv.org/abs/2503.03480) ·
[RoboSafe](https://arxiv.org/html/2512.21220v1) · [CHAI](https://news.ucsc.edu/2026/01/misleading-text-can-hijack-ai-enabled-robots/) ·
[AttackVLA](https://arxiv.org/html/2511.12149) · [SafeAgentBench](https://arxiv.org/html/2412.13178v5) ·
[ASIMOV-2.0](https://arxiv.org/html/2509.21651) · [RoboArena](https://arxiv.org/html/2506.18123v2) ·
[Unitree RCE](https://boschko.ca/unitree-go2-rce/) · [IETF agent audit trail](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/)

Protocols: [MCP 2026-07-28 RC](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/) ·
[MCP roadmap](https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/) ·
[MCP tools spec](https://modelcontextprotocol.io/specification/draft/server/tools) ·
[ros-mcp-server](https://github.com/robotmcp/ros-mcp-server) · [ROS 2 Lyrical Luth](https://discourse.openrobotics.org/t/ros-2-lyrical-luth-released/55021) ·
[A2A at LF](https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year) ·
[Home Assistant AI Task](https://www.home-assistant.io/integrations/ai_task/)
