# OBC-Prime — positioning and build plan

Written 2026-07-28, from a survey of all four repos plus the running system.

---

## 1. The name

**Recommendation: Open Body Control.**

Three reasons, in order of weight:

1. **OBC already means On-Board Computer** in aerospace and robotics. That's
   not a collision to avoid, it's inherited meaning to lean on — you get the
   embodied-compute association for free. (Your own agent, asked what it was,
   reached for "OBC (On-Board Computer)" unprompted.)
2. **It reads like a standard, not a product.** Open Sound Control is the model:
   a name that says "this is the layer everyone builds against." For a project
   whose real asset is a hardware registry and a node protocol, that framing is
   worth more than a clever brand.
3. **"Body" is the honest word for what this is.** Not a chatbot with plugins —
   an agent with a mesh of ESP32 nodes, cameras, sensors and actuators. "Body"
   covers all of it and sets up the natural vocabulary: *brain* (the Rust
   agent), *body* (nodes and peripherals), *senses* (ClawCam, audio, GNSS),
   *reflexes* (the System 1 layer that already exists).

Runners-up: **Onboard Control** (safer, less distinctive), **Open Brain & Claw**
(preserves the heritage that's load-bearing in the code — `obc-brain`, ClawCam,
ClawHub — but doesn't explain itself to a newcomer).

Whatever you pick, keep `obc` as the CLI binary, the config dir and the crate
name. Those are already in muscle memory and in every doc.

---

## 2. What you actually have (four repos, honestly assessed)

| Repo | State | Value to a public project |
|---|---|---|
| **Oh-Ben-Claw** | Working. Runs on local Ollama, 24 tools, gateway, reflex/System-2 layer, ClawCam perception. Also carries a 115k-line CHANGELOG, half-built subsystems and dead code. | The core. But not shippable as-is. |
| **OBC-deployment-generator** | Genuinely working. 124 passing tests. Expo app, 69-board registry, generates config TOML + site plans + compilable ESP32 projects. | **The onboarding story.** This is how a stranger gets from zero to a running deployment. |
| **Accelerapp** | 99% AI-generated IoT monolith; the headline CLI is broken. 1% is a real, recent, well-tested OBC bridge. | Take `hardware/registry.py` + `firmware/obc_templates.py`. Leave the rest. |
| **ClawCam** | Working perception source over MCP, with a seeded demo DB. | **The proof.** See §4. |

### The crown jewel nobody has named yet

The deployment generator's `tests/planner-parity.test.ts` enforces
**byte-identical TOML output across three independent implementations** — the
Rust planner, the WASM build, and the TypeScript port. I hash-verified that its
`registry.json`, all four golden fixtures and the planner WASM are identical to
Oh-Ben-Claw's.

That parity harness is the most valuable engineering artifact across all four
repos, and it's currently an undocumented implementation detail of a private
Expo app. In a public project it should be a headline claim: *the planner that
runs in your browser and the planner that runs on the device provably agree.*

Its one weakness: those files are **hand-copied with no sync script and no drift
check**. The only thing catching staleness is tests failing after the fact.
First infrastructure task in the new repo is `scripts/sync-registry` plus a CI
drift gate.

---

## 3. Recommended structure

**A clean public repo with Oh-Ben-Claw as upstream core** — not a rename, not a
monorepo of all four.

Reasoning: a rename drags 115k lines of changelog and a dozen half-finished
phases into first contact with the public. A four-way monorepo drags in
Accelerapp's broken 99%. The clean repo lets you move things over as they
become defensible, which is also the natural order to write docs in.

```
obc-prime/
  core/         # the Rust agent — vendored or submoduled from Oh-Ben-Claw
  registry/     # boards + accessories, SSOT, emitted by core
  parity/       # golden fixtures + the tri-implementation harness  <- headline
  bodies/       # ready-to-run reference deployments (see §4)
  generator/    # the Expo app, de-Manus-ed
  firmware/     # node sketches; Accelerapp's two good modules land here
  docs/
```

---

## 4. ESP32 + ClawCam as a ready-to-use feature

Your instinct is right that this shouldn't just be a demo. The framing that
makes it useful beyond showing off:

**Reference Bodies** — complete, named, runnable deployments. Each one is a
directory containing a config TOML, a board list, firmware, and a seeded
database so it runs *before* any hardware arrives.

The first one already exists in all but name. ClawCam + the LoRa mesh is
**"Trailwatch"**: a wildlife/perimeter camera body. Species detection folding
into world memory, vision reflex rules on verified person detections, mesh nodes
reporting health over LoRa, calibration-drift escalation to System 2. It is
already running on this machine right now against 14 days of seeded data.

Why this is more than a demo:

- **It runs with zero hardware.** The seeded DB means a stranger can `git clone`,
  start OBC, and watch reflexes fire in about two minutes. That is the single
  highest-leverage thing you can offer a newcomer.
- **It's a working template.** Swap the species list and the alert subjects and
  it's a security perimeter, a livestock monitor, or a lab-door watcher. The
  reflex rules and escalation playbooks are the reusable part.
- **It proves the whole stack at once** — perception → world memory → reflex →
  System 2 → notification — which no amount of documentation does.

Second Reference Body worth building: **"Benchtop"** — one ESP32-S3 over serial,
no mesh, no camera. The five-minute on-ramp for someone with a single dev board
in a drawer. The deployment generator can already emit exactly this.

**Gap to close:** ClawCam appears *nowhere* in the deployment generator. The
generator knows about 69 boards and 10 feature desires but cannot produce the
one deployment you've actually proven end to end. Wiring Trailwatch into the
generator as a selectable template is the highest-value integration on this list.

---

## 5. Where Accelerapp fits

Narrowly, and that's fine. It becomes the **firmware codegen backend**:
OBC owns the registry and the node protocol; Accelerapp turns a board record
into a flashable sketch plus platform drivers. Its `registry.py` and
`obc_templates.py` are hand-written, tested, and correctly treat OBC as the
source of truth.

Do not import the rest. The compliance, monetization, governance and
"post-quantum" modules are scaffolding, and `accelerapp generate device.yaml` —
the first command in its own README — currently raises ImportError because
`core.py` is shadowed by a `core/` package. Either fix that in place as a
standalone tool or lift the two good modules into `firmware/` and move on.

---

## 6. Blockers to fix before anything is public

Found while getting the system running — all of these are load-bearing:

1. **`Scheduler::new(&config.agent.name)`** in `main.rs` passes a *name* where a
   *path* is expected, then `.unwrap()`s the fallback. OBC panics on startup
   whenever the working directory isn't writable — which is every service
   manager on every OS. This will break the first thing a stranger tries.
2. **A failed gateway bind is only a WARN.** OBC keeps running headless with no
   API. Looks healthy, answers nothing. Should be fatal, or at minimum retried.
3. **`SOUL.md` / `USER.md` are dead code.** `memory/personality.rs` implements
   and documents them; nothing calls it. Either wire it into `build_context()`
   or delete it — shipping documented features that do nothing is worse than
   not having them.
4. **Config path is undocumented and surprising.** The doc comment says
   `~/.oh-ben-claw/config.toml`; the code resolves `OBC_CONFIG` →
   `%APPDATA%\thewriterben\...`. A config in the documented location is silently
   ignored and the agent falls back to `openai/gpt-4o` — i.e. it quietly tries
   to spend money.
5. **Tool argument names are inconsistent** — `vision_analyze` takes `source`,
   `audio_transcribe` takes `path`, `file` takes `action`+`path`. Local models
   get this wrong, and then *confabulate rather than report the failure*
   (observed: an invented description of an image the tool never read).
   Worth normalising before external users write tools against it.

---

## 7. Suggested order

1. Fix blockers 1, 2 and 4 — they're small and they're the difference between
   "works" and "works for someone else."
2. Stand up `obc-prime` with `core/`, `registry/`, `parity/` and the sync script.
   Make the tri-implementation parity claim the README headline.
3. Package **Trailwatch** as the first Reference Body, seeded DB included.
4. Wire Trailwatch into the deployment generator as a template; de-Manus the
   generator (OAuth, package name, license) at the same time.
5. Lift Accelerapp's two good modules into `firmware/`.
6. Decide on `SOUL.md`: wire it or cut it.
