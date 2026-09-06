# OBC-Prime — positioning and build plan

Written 2026-07-28, from a survey of all four repos plus the running system.

> **Status re-measured 2026-08-02.** This file is two things at once: a dated
> survey, which is allowed to be a snapshot, and a live to-do list in §7, which
> is not — the README sends a newcomer here for "what is landing and in what
> order". The second half had drifted five days and in the more corrosive
> direction: **seven items listed as open or gating were already done** — the
> release gates on keys-in-config, cloud-first defaults and licence/CONTRIBUTING;
> the `SOUL.md` decision, which appeared twice and had been settled by deleting
> it; and two of the three things said to block publishing the generator. Work
> that looks larger than it is buries the work that is genuinely left.
>
> Everything below marked done or open on this date was re-derived from a
> `git archive HEAD` of the repo it concerns, not from reading. Where a number
> is given, it is that measurement. The dated survey text is left standing with
> corrections attached, rather than rewritten to look like it was right.

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

> **Not taken, and the docs now say the opposite (2026-08-02).** The binary is
> `oh-ben-claw` (`default-run` in the core `Cargo.toml`), the config dir is
> `~/.oh-ben-claw/`, and the crate is `oh-ben-claw`. Nothing was ever renamed to
> `obc`. The reference bodies here *did* say `obc start` until PR #15, which
> changed them — to `oh-ben-claw start`, because that is the binary that exists,
> and a quickstart naming a binary a reader cannot run is the more urgent
> problem. So the recommendation was reversed in practice, in this repo, by a
> merged change that did not know it was reversing anything.
>
> The decision is still live: rename the binary to `obc` and this paragraph is
> right again, or drop the paragraph. What is not tenable is a plan file
> recommending a name the rest of the repo has already argued against.

---

## 2. What you actually have (four repos, honestly assessed)

| Repo | State | Value to a public project |
|---|---|---|
| **Oh-Ben-Claw** | Working. Cloud provider by default with a local Ollama fallback, 24 tools, gateway, reflex/System-2 layer, ClawCam perception, temporal world model with belief revision. Curated 2026-07-28: five unreachable modules and the personality store removed. | The core. Approaching shippable. |
| **OBC-deployment-generator** | Genuinely working. 124 passing tests. Expo app, 69-board registry, generates config TOML + site plans + compilable ESP32 projects. | **The onboarding story.** This is how a stranger gets from zero to a running deployment. |
| **Accelerapp** | 99% AI-generated IoT monolith; the headline CLI is broken. 1% is a real, recent, well-tested OBC bridge. | Take `hardware/registry.py` + `firmware/obc_templates.py`. Leave the rest. |
| **ClawCam** | Working perception source over MCP, with a seeded demo DB. | **The proof.** See §4. |

> **"24 tools" is a survey number and does not agree with the core repo.** That
> README says "one tool out of seventy-six"; a Trailwatch run logs
> `tool_count=22` for a body with the browser and ClawHub disabled. The count is
> config-dependent, so all three can be true of different things — but a
> 2026-08-02 attempt to derive a single figure from the registry found 40 tool
> `name()` literals and could not account for the rest, so **no number here is
> re-measured**. Left as written rather than replaced with a figure nobody
> checked.

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

> **Re-measured 2026-08-02 — the cut mostly happened, and what is left changed
> character.** Against `git archive HEAD` of the core repo:
>
> | module | then | now |
> |---|---|---|
> | `dashboard` | 798 LOC, island | **deleted** in 489aecc |
> | `rag` | 367 LOC, island | **deleted** in 489aecc |
> | `satcom` | 336 LOC, island | **deleted** in 489aecc |
> | `hooks` | 279 LOC, island | **deleted** in 489aecc |
> | `memory/personality.rs` | island | **deleted**; `SOUL.md` is gone and `PersonalityStore` has zero non-comment references |
> | `bin` | 72 LOC, island | present, and correctly zero-referenced — they are binaries |
> | `a2a` | 868 LOC, island | present at 871 LOC, **one** external reference: `tests/evals.rs` |
>
> So ~2,720 becomes ~940, and only `a2a` is a decision. It also stopped being
> the kind of thing this table was counting. "Island" here meant *dead code* —
> nothing outside its directory names it. `a2a` is not dead: it has 18 unit
> tests and wire-shape conformance goldens that pass, and they are testing the
> right things. It is **unreachable production code** — nothing constructs
> `A2AServer` outside tests, `A2AClient` is constructed nowhere at all, no route
> serves the agent card, `config.a2a` has zero reads, and `A2AServer::execute`
> is a documented stub. The core README now carries that measurement in full.
>
> A reference count cannot tell those two apart, which is worth writing down
> next to a table built from reference counts. The method note below says a
> proxy for deadness is "where the judgement starts rather than ends"; this is
> the case where it started somewhere quite different from where it ended.

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

> **Re-measured 2026-08-02.** Three of the five are closed, one differently from
> how it was framed here.
>
> 1. **Keys out of config — done, by a different route.** This asked for
>    env-var-and-secret-store-first with the inline field discouraged. What
>    landed instead: `ProviderConfig.api_key` is
>    `Option<secret::SecretString>`, a type that will not print itself. The
>    inline field still exists; it can no longer leak into a log or a pasted
>    debug dump, which was the actual worry behind "a public config template is
>    the file people paste into issues".
> 2. **Cloud-first defaults — done.** `default_provider_name()` returns
>    `"openai"`. A fresh install with one env var is the documented path and
>    Ollama is opt-in, which is the inverse of where this started.
> 3. **Cut the islands + `personality.rs` — done except `a2a`.** Four modules
>    and the personality store are deleted; see the table above. `a2a` is the
>    one left and is now a documented decision rather than a pending cut.
> 4. **A licence and a CONTRIBUTING — done.** Both are in the core repo, and
>    `CONTRIBUTING.md` here opens with which repo a change belongs in.
> 5. **No single-user assumptions — not re-measured.** Genuinely open, and the
>    only one of the five that is. Saying so is better than leaving it in a list
>    where four neighbours are silently finished.

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

3. ~~**`SOUL.md` / `USER.md` are dead code.** `memory/personality.rs` implements
   and documents them; nothing calls it. Either wire it into `build_context()`
   or delete it — shipping documented features that do nothing is worse than
   not having them.~~ **Closed — deleted**, in 489aecc, "delete what was never
   wired". `src/memory/personality.rs` and `SOUL.md` are both gone from the
   core repo and `PersonalityStore` has zero non-comment references. Recorded
   2026-08-02; it had been listed open here for two days after the delete, and
   also listed open a second time in §7.6 below.
5. **Tool argument names are inconsistent** — `vision_analyze` takes `source`,
   `audio_transcribe` takes `path`, `file` takes `action`+`path`. Local models
   get this wrong, and then *confabulate rather than report the failure*
   (observed: an invented description of an image the tool never read). Worked
   around downstream by naming the exact call shape in the prompt; the
   inconsistency itself is untouched and worth normalising before external
   users write tools against it.

   > Still open on 2026-08-02. `vision_analyze` does declare `source`, and
   > `shell` declares `command` — but the 2026-08-02 pass could not extract the
   > schemas for `audio_transcribe` or `file`, which are declared in a different
   > shape, so this is carried forward *unverified* rather than confirmed. An
   > item nobody managed to re-measure should say so.

---

## 7. Suggested order

1. ~~Fix blockers 1, 2 and 4.~~ **Done** — see §6.
2. ~~Stand up `obc-prime` with `registry/`, `parity/` and the sync script; make
   the tri-implementation parity claim the README headline.~~ **Done.** The gate
   verifies all 10 artifacts byte-identical across manifest, core and generator,
   and was itself verified by deliberately corrupting a file and watching it
   fail. `core/` is not vendored — the agent is still private, and the README
   says so rather than implying otherwise.

   > 2026-08-02: **96** artifacts, not 10, and `crates/` *is* vendored now — six
   > crates, 391 tests running here in CI. The sentence "the agent is still
   > private" is still true of the agent loop and no longer true of the
   > substrate.
3. ~~Package **Trailwatch** as the first Reference Body, seeded DB included.~~
   **Done**, and the quickstart is real: it ships `serve.py`, a stdlib MCP
   server over the seeded database, so it has no dependency on the private
   camera-gateway project. Verified from a clean working directory with the
   live data dir moved aside.
4. ~~Wire Trailwatch into the deployment generator as a template.~~ **Done.**
   De-Manusing the generator (OAuth, package name, license) is **still open**.

   > 2026-08-02: two of those three are done. `package.json` is named
   > `obc-deployment-generator` and there is a `LICENSE`. What remains is the
   > OAuth binding — `constants/oauth.ts`, `lib/_core/manus-runtime.ts`,
   > `app/oauth/callback.tsx`, `drizzle/schema.ts` and three others still carry
   > it, and `PUBLISHING.md` documents the choice: the login gates nothing, so
   > removing accounts costs ~800 lines and no feature. That is the one
   > remaining decision, and it is a decision rather than a task.
   >
   > 2026-09-06: **decided and done.** The OAuth round-trip went on 2026-08-21
   > (generator PR #10); the remaining stub — session shape, cookies, auth
   > router, drizzle/MySQL, the previewer bridge, the Manus bundle id and
   > scheme — went on the `chore/no-accounts` branch. Nothing in the generator
   > names the scaffolding platform any more except the history in
   > `PUBLISHING.md`. Left in §3 of that file: one look at the web build's
   > safe areas.
5. Lift Accelerapp's two good modules into `firmware/`. **Open** — confirmed
   2026-08-02: no `registry.py` or `obc_templates.py` anywhere in this repo.
6. ~~Decide on `SOUL.md`: wire it or cut it.~~ **Closed — cut.** See §6 blocker
   3. This was the same item as blocker 3 and both said "open"; the delete had
   already happened upstream.
7. **Migrate the agent piecewise.** Six crates are here as of 2026-08-02 —
   `obc-paths`, `obc-memory`, `obc-planner`, `obc-safety`, `obc-telemetry`,
   `obc-observability` — chosen by `scripts/extractability.py` in the core repo
   rather than by hand. `scheduler` (684 LOC, 16 tests) is the last module with
   zero blocking edges; after it, every remaining candidate needs an edge turned
   around first, the way `obc-safety`'s `RiskClass` edge was.

Also still open, in rough order of how much they'd embarrass a visitor:

- ~~**The generator is still private, and one thing still binds it to Manus.**~~
  **Closed 2026-09-06.** Package name and licence were fixed on 2026-08-02, the
  OAuth round-trip removed on 2026-08-21, and the last of the stub (session,
  cookies, drizzle/MySQL, previewer bridge, Manus bundle id) on 2026-09-06.
  What stands between the generator and being public is now only the
  repository's visibility setting — and `PUBLISHING.md` §4's warning that a
  *hosted* instance is an open proxy, which is a deployment decision, not a
  code one.
- ~~**CI only checks the manifest.** The `--upstream` job is written but commented
  out, because the core repo isn't readable from CI. Drift against the core
  agent is therefore *not* caught today — only hand-edits are.~~ **Closed
  2026-07-30.** Six jobs run now: `manifest`, `behaviour` (executes the WASM
  against the goldens), `substrate` (builds and tests the vendored crates),
  `peer`, `accelerapp` and `upstream`. The premise was wrong on the part that
  had kept the job commented out for weeks — the core repo is public, so
  `github.token` reads it and no secret was ever needed. Nobody had asked.
  **Seven** jobs as of 2026-08-02: `doclinks` was added after `docs/SAFETY.md`
  was found linking to a `SECURITY.md` this repo does not have.
- **`bodies/benchtop` has no runtime half**, only a generator inventory. Still
  true on 2026-08-02: `bodies/benchtop/` contains exactly `README.md` and
  `config.toml`, against Trailwatch's four files including a seeded database and
  a perception server. This is now the oldest genuinely-open item on the page.
- ~~**The operate token is stored in plaintext AsyncStorage** in the generator's
  fleet console, though `expo-secure-store` is already a dependency and is
  already used for the session token. That token authorises remote tool
  execution.~~ **Fixed.** `lib/_core/operate-token.ts` uses `SecureStore`, and
  reading migrates any plaintext copy and then deletes it — a move that left the
  old file in place would have fixed nothing. Web is memory-only and the UI says
  so, because `SecureStore` has no web implementation and `localStorage` would
  be the same plaintext plus XSS reach. Verified 2026-08-02.
