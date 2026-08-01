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
| **Oh-Ben-Claw** | Working. Cloud provider by default with a local Ollama fallback, 24 tools, gateway, reflex/System-2 layer, ClawCam perception, temporal world model with belief revision. Curated 2026-07-28: five unreachable modules and the personality store removed. | The core. Approaching shippable. |
| **OBC-deployment-generator** | Genuinely working. 124 passing tests. Expo app, 69-board registry, generates config TOML + site plans + compilable ESP32 projects. | **The onboarding story.** This is how a stranger gets from zero to a running deployment. |
| **Accelerapp** | 99% AI-generated IoT monolith; the headline CLI is broken. 1% is a real, recent, well-tested OBC bridge. | Take `hardware/registry.py` + `firmware/obc_templates.py`. Leave the rest. |
| **ClawCam** | Working perception source over MCP, with a seeded demo DB. | **The proof.** See §4. |

### The crown jewel nobody has named yet

The deployment generator's `tests/planner-parity.test.ts` enforces
**byte-identical TOML output across three independent implementations** — the
Rust planner, the WASM build, and the TypeScript port. I hash-verified that its
`registry.json`, all four golden fixtures and the planner WASM are identical to
Oh-Ben-Claw's.

> **Corrected 2026-08-01.** "Three independent implementations" is two
> implementations in three executables: the WASM build is compiled from the Rust
> planner's own sources. The claim is still the strong one — a hand-written
> TypeScript port held byte-identical to the Rust that deploys is the hard part —
> but the two legs fail differently and should be named separately. The port can
> disagree on *logic*; the build can disagree on *age*, and did, for six weeks.
> See `parity/README.md`, corrected 2026-07-29, and `docs/DECISIONS.md`,
> *A hash gate cannot see a stale build*.

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

Reasoning: a rename drags a dozen half-finished phases into first contact with
the public. A four-way monorepo drags in Accelerapp's broken 99%. The clean repo
lets you move things over as they become defensible, which is also the natural
order to write docs in.

> **Corrected 2026-07-28.** This paragraph previously said a rename would drag
> in "115k lines of changelog". `CHANGELOG.md` was **1,548 lines** when checked
> and grows with every commit. The 115k figure appears to have been the source
> tree (77k LOC then) misremembered as the changelog. The conclusion stands on the half-finished phases; the number
> did not, and a decision resting on a wrong number is worth re-deriving rather
> than inheriting.

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

## 3a. Taking core public — what "curated" actually means

Decided 2026-07-28: **the core agent goes public, curated.** Ongoing work stays
in Oh-Ben-Claw and migrates to Open Body Control as each piece becomes
defensible — the same forward-migration model `scripts/sync_upstream.py` already
applies to the vendored artifacts, extended to source.

### Measured, not assumed

77,316 LOC across 42 modules. Modules with **zero references from outside their
own directory**:

| module | LOC |
|---|---|
| a2a | 868 |
| dashboard | 798 |
| rag | 367 |
| satcom | 336 |
| hooks | 279 |
| bin | 72 |
| **total** | **~2,720** |

Plus `memory/personality.rs` — SOUL.md / USER.md, implemented and documented,
never called (blocker 3 in §6).

So the first cut is **~3.5% of the tree**, not the amputation "clean repo"
suggests. That is a much easier decision than it looked, and it means the public
core can be close to the working core rather than a diverged fork.

> **Method note.** A first pass at this flagged *nine* islands including
> `gateway` — the module that binds the HTTP API. The pattern missed grouped
> imports (`use oh_ben_claw::{…}`), which is how most modules are pulled in.
> `gateway`, `runtime` and `tunnel` are live. `scripts/curation_survey.py` in
> the core repo is the corrected version, and it is a *proxy* for deadness, not
> a proof: zero external references means "removing it would not break the
> build", which is where the judgement starts rather than ends.

### What gates the release, in order

1. **Keys out of config.** `ProviderConfig.api_key` accepts an inline string.
   Env-var and secret-store first; the inline field discouraged or removed. A
   public config template is the file people paste into issues.
2. **Cloud-first defaults** that work on a fresh install with one env var, with
   Ollama documented as the opt-in path rather than the assumed one.
3. **Cut the six islands + `personality.rs`**, or wire the latter. Shipping
   documented features that do nothing is worse than not having them.
4. **A licence**, and a `CONTRIBUTING` that says where work happens.
5. **No single-user assumptions** in config paths, data locations, or the "one
   gateway per machine" shape — self-hosted now, hosted not foreclosed.

Explicitly *not* gating: the half-built phases. They can ship as-is provided the
docs do not claim they work.

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

Found while getting the system running — all of these are load-bearing.

**Fixed** (core commit "Fix three startup failures that only bite outside a dev
shell", verified against a service-manager-style start):

1. ~~**`Scheduler::new(&config.agent.name)`** passed a *name* where a *path* was
   expected, then `.unwrap()`ed the fallback — so the agent panicked on startup
   whenever the working directory wasn't writable.~~ Now resolves a path in the
   data dir and degrades to an in-memory scheduler rather than dying.
2. ~~**A failed gateway bind was only a WARN**, so the agent ran headless with
   no API: healthy-looking process, nothing answering.~~ Now an ERROR naming
   host, port and the likely cause.
4. ~~**Config path was undocumented and surprising** — a config in the
   documented `~/.oh-ben-claw/config.toml` was silently ignored and the agent
   fell back to defaults naming a *cloud* provider.~~ That path is now third in
   the search order, and the fallback warns and names the provider it chose.

**Still open:**

3. **`SOUL.md` / `USER.md` are dead code.** `memory/personality.rs` implements
   and documents them; nothing calls it. Either wire it into `build_context()`
   or delete it — shipping documented features that do nothing is worse than
   not having them.
5. **Tool argument names are inconsistent** — `vision_analyze` takes `source`,
   `audio_transcribe` takes `path`, `file` takes `action`+`path`. Local models
   get this wrong, and then *confabulate rather than report the failure*
   (observed: an invented description of an image the tool never read). Worked
   around downstream by naming the exact call shape in the prompt; the
   inconsistency itself is untouched and worth normalising before external
   users write tools against it.

---

## 7. Suggested order

1. ~~Fix blockers 1, 2 and 4.~~ **Done** — see §6.
2. ~~Stand up `obc-prime` with `registry/`, `parity/` and the sync script; make
   the tri-implementation parity claim the README headline.~~ **Done.** The gate
   verifies all 10 artifacts byte-identical across manifest, core and generator,
   and was itself verified by deliberately corrupting a file and watching it
   fail. `core/` is not vendored — the agent is still private, and the README
   says so rather than implying otherwise.
3. ~~Package **Trailwatch** as the first Reference Body, seeded DB included.~~
   **Done**, and the quickstart is real: it ships `serve.py`, a stdlib MCP
   server over the seeded database, so it has no dependency on the private
   camera-gateway project. Verified from a clean working directory with the
   live data dir moved aside.
4. ~~Wire Trailwatch into the deployment generator as a template.~~ **Done.**
   De-Manusing the generator (OAuth, package name, license) is **still open**.
5. Lift Accelerapp's two good modules into `firmware/`. **Open.**
6. Decide on `SOUL.md`: wire it or cut it. **Open.**

Also still open, in rough order of how much they'd embarrass a visitor:

- **The generator is still private and still Manus-bound.** Its OAuth is hard-
  wired to a sandbox portal, `package.json` is named `"app-template"`, and there
  is no licence. It cannot be published as-is, which means the onboarding story
  the README leans on isn't reachable yet.
- ~~**CI only checks the manifest.** The `--upstream` job is written but commented
  out, because the core repo isn't readable from CI. Drift against the core
  agent is therefore *not* caught today — only hand-edits are.~~ **Closed
  2026-07-30.** Six jobs run now: `manifest`, `behaviour` (executes the WASM
  against the goldens), `substrate` (builds and tests the vendored crates),
  `peer`, `accelerapp` and `upstream`. The premise was wrong on the part that
  had kept the job commented out for weeks — the core repo is public, so
  `github.token` reads it and no secret was ever needed. Nobody had asked.
- **`bodies/benchtop` has no runtime half**, only a generator inventory.
- **The operate token is stored in plaintext AsyncStorage** in the generator's
  fleet console, though `expo-secure-store` is already a dependency and is
  already used for the session token. That token authorises remote tool
  execution.
