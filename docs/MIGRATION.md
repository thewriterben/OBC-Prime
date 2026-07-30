# Migration — Oh-Ben-Claw → Open Body Control

Written 2026-07-30, from a read of all four repos, a clean `cargo check` of the
core workspace, and a first-hand run of the parity artifacts.

Decided going in: **development stays upstream in Oh-Ben-Claw and migrates
piecewise**, each piece moving to Open Body Control when it is defensible. That
is what `CONTRIBUTING.md` already says in both repos. This document is about
what "defensible" has to mean in practice, and what has to be true before the
first piece of *source* — as opposed to vendored artifacts — can move.

---

## 1. Where the core actually stands

Better than the docs suggest in the code, worse in the documentation.

**The code.** 83,253 LOC across 37 directory modules. `cargo check --workspace
--all-targets` is clean: **0 errors, 0 warnings**. 1,417 test functions in `src/`
plus 14 integration suites. The panic surface is unusually disciplined — 1
`TODO`, 0 `FIXME`, 0 `todo!`, 0 `unimplemented!`, and of 94 non-test
`unwrap`/`expect` calls, 76 are mutex-poison unwraps. The single-user
assumptions that would normally block a public release are already gone:
`OBC_DATA_DIR` resolves through one module, there are no hardcoded drive letters,
no personal paths, and every hardcoded IP is inside a `#[cfg(test)]` block. Two
instances have been run side by side.

That is a codebase in much better shape than "77k lines of half-finished phases"
implies. The obstacle to migration is not code quality.

**The documentation.** `ROADMAP.md` no longer describes the system. Six `[x]`
rows cite modules deleted in the 2026-07-28 curation pass, and one `[x]` row
claimed a sandbox that has never been wired.

> **Corrected 2026-07-30.** This paragraph originally said the roadmap had no
> phase for nine modules totalling "roughly 8,900 LOC", none of them evaluated.
> Measured with `scripts/subsystem_ledger.py`: **five** modules have no roadmap
> presence — `foresight`, `power`, `gnss`, `comms`, `aerial`, **1,826 LOC** — and
> most of the nine I named are covered by integration suites. The original figure
> came from counting module names in `ROADMAP.md`, which undercounts anything
> discussed by feature name rather than by directory. A number derived from a word
> count, presented as an inventory.

This still matters because of the migration policy. "Each piece moves when it is
defensible" needs a list of pieces and a defensibility status per piece, and that
list did not exist. It does now: `scripts/subsystem_ledger.py` in the core repo
derives it, and `ROADMAP.md` carries the generated table under **Subsystem
ledger**. The instrument, not the snapshot, is the deliverable — a hand-maintained
inventory is what produced the problem in the first place.

---

## 2. The three things blocking migration

Not "blocking release" — blocking the *piecewise migration* specifically.

### 2.1 The public repo's headline claim was false, and its gate could not see it

Open Body Control's README leads with the parity claim: three planner
implementations, byte-identical output, enforced in CI. I checked it by loading
the vendored WASM under Node against the golden fixtures.

`deployment_toml` matched. `config_toml` did not:

```
wasm: 79 lines          golden: 119 lines
L5   name = "Oh-Ben-Claw (NanoPi-Neo3 Reference Deployment)"   vs  name = "nanopi-neo3-reference-deployment"
L13  [provider]                                                vs  # Uncomment to pin one instead:
L14  name = "openai"
L15  model = "gpt-4o"
```

The bundle was built 11 July. On 28 July `src/deployment/planner.rs` was
rewritten three times and `expected-config.toml` re-blessed with it. **Every
hash in `MANIFEST.json` still matched. `check --upstream --peer` reported all 43
artifacts identical.** It had to: a compiled artifact cannot drift from its own
hash. The manifest was hashing the output and nothing was hashing the inputs.

The test that should have caught it is the narrow-gate failure this project has
already diagnosed once, in writing. `planner-parity.test.ts` carries a long
comment about how a golden covering only `[deployment]` hid a real divergence for
months — and that comment sits directly above an assertion that compares the
whole config byte for byte. Twenty lines away in `wasm-planner.test.ts`, the
equivalent assertion read `expect(scheme.config_toml).toContain("[peripherals]")`.

The lesson was written down, applied to one leg, and not carried to the other.

> **Closed 2026-07-30.** Rebuilt, re-synced, all four legs green, and confirmed
> by *executing* the bundle rather than hashing it. Only the `.wasm` changed;
> the goldens did not need re-blessing, because the planner sources were always
> right and it was only the build that was old.
>
> The deeper gap that surfaced while confirming it: **nothing in OBC-Prime ran
> the bundle.** Every gate compared hashes. The assertion that would have caught
> the original bug lived in the generator's vitest suite — another repo, with no
> CI, needing an npm install. So the public project could not check its own
> headline claim unaided. `parity/verify_wasm.cjs` now does, in CI, with node and
> nothing else. See `docs/DECISIONS.md`, *Hashes prove identity; only execution
> proves correctness*.

While in there: it is **two implementations in three executables**, not three.
`planner-wasm` compiles the host crate's sources verbatim via `#[path]` — its own
`src/` contains three shim files and no planner logic. The README and
`parity/README.md` both said "three independent implementations". The honest claim
is still strong and worth leading with — a hand-written TypeScript port held byte-
identical to the Rust that deploys is the hard part — but it should be the claim
that is true.

### 2.2 The spine has no authentication, and the public repo already ships its firmware

`docs/SAFETY.md` §4.3 states it plainly: `p2p` and MQTT have no authentication
story, cites the Unitree CVEs, and says "treat the spine network as trusted, and
make sure that is actually true."

That is a defensible position for a bench. It is a much harder one for a public
project whose README leads with a safety claim, because Open Body Control **has
already published four firmwares** for that spine — that was the right call for
onboarding, and it means the unauthenticated transport is the part a stranger
reaches first. The safety story currently reads: the microcontroller enforces
limits even if the host is compromised, and anyone on the network can talk to the
microcontroller.

`docs/RESEARCH-2026-07.md` ranks perception/transport hardening as gap 2 of 5 and
its §5 ordering puts it second overall. Nothing in `DECISIONS.md` has picked it
up. Of everything in this document, this is the item I would treat as gating the
first *source* migration, because it is the one where a knowledgeable visitor's
first question has no good answer.

### 2.3 Three subsystems carry a claim their evidence does not reach

**This section replaces a wrong one.** It previously asserted that navigation,
SLAM, fleet coordination and foresight had "no phase, no eval and no bench
evidence", and that the Nav2/Cartographer comparison would not survive scrutiny.
Both halves were wrong, and the ledger is what caught it:

- `navigation` has **55 test functions** and is exercised by three integration
  suites (`embodied_full_stack`, `embodied_hil_loop`, `spine_fleet_e2e`). `fleet`
  has three. `mission` and `movement` likewise. Only `foresight` was
  unit-tested-only. Three of the four subjects were mischaracterised.
- `docs/SOTA-COMPARISON.md` is not an overclaim. Its own opening states that OBC's
  *architecture* sits in the SOTA families while its *implementations* are
  "deliberately simplified, interpretable baselines", and every section ends in an
  **honest gaps** verdict naming what is missing — no inflation layer, no
  kinodynamic feasibility, relaxation instead of sparse least-squares, spatial
  rather than feature-based loop closure. It is a self-critical assessment, not a
  claim awaiting puncture. Softening it, which §5 previously floated as a
  decision, is not needed.

What the measurement does show, and what stands:

| module | LOC | why it blocks |
|---|---:|---|
| `foresight` | 677 | The only SOTA-compared subsystem with no integration suite **and** no roadmap row. |
| `learning` | 454 | Self-authored reflexes — mine → propose → approve → activate. The thinnest coverage in the tree (4 tests) on the one pipeline that ends by activating a rule which can actuate hardware. Its approval gate is the safety story and has no integration test. |
| `runtime` | 417 | Unwired. Decision, not testing. |

1,548 LOC, three decisions. That is a materially smaller and more actionable
problem than the one this section originally described, and the difference between
the two is the difference between counting words and measuring.

---

### 2.4 Documented-but-unwired features, at three granularities

Found 2026-07-30, after the module-level ledger in §1 was built and called
sufficient. It was not.

`scripts/file_reachability.py` in the core repo asks the ledger's question one
level down — per *file* rather than per module — and cross-references what it
finds against README and ROADMAP. Result: **17 unwired files, 6,698 LOC, of which
14 are presented as shipped (6,048 LOC).** Six confirmed by hand so far:

- **Four of the eleven advertised channels** — `feishu`, `mattermost`, `irc`,
  `signal`, 1,524 LOC. Each file's only external reference is its own `pub use`
  line in `channels/mod.rs`. Nothing constructs them. The README says eleven
  channels.
- **`mission/bt.rs`** — the behavior-tree engine, 648 LOC. `BtSpec`, `BtContext`,
  `Bt`, `BtRunner`: zero references each. The README cites `src/mission/bt` and
  `SOTA-COMPARISON.md` devotes a section to missions-versus-BTs.
- **`peripherals/fusion.rs`** — 662 LOC, all six public types unreferenced.
  ROADMAP had it as `[x] Sensor fusion`.
- **`memory/heartbeat.rs`** and **`memory/journal.rs`** — both named in the
  README's Memory paragraph. `has_tasks`, `actionable_tasks`, `build_prompt`,
  `append_task`: no callers.

And a third shape that **neither** survey can see, which is the one that matters
most:

**`security/pairing.rs` — nodes are not authenticated.** 386 tested lines.
`NodePairingManager` *is* referenced, so file-level reachability clears it: it is a
field on `SecurityManager` and it is constructed at startup. But `pair_node` has
zero callers, `is_trusted` has zero, the `pairing` field is never read, and
`[security] require_pairing = true` is consulted only by config validation — it
refuses to boot without a secret, then gates nothing. Reachable, instantiated,
unit-tested, inert.

This sharpens §2.2 rather than replacing it. `src/security/trust.rs` — dynamic
trust scoring, which *is* wired and does work — opens its header with "OBC already
authenticates nodes (HMAC pairing) ... that trust is *static*" and builds
behavioural hardening on that premise. The premise is false. Trust decays on
misbehaviour; nothing establishes it. And it means spine auth is a bigger job than
§3 item 4 implied: the host-side primitive exists but is unwired, the **node side
does not exist at all** (no HMAC anywhere in `firmware/`, and `SpineFrame` has no
signature field), so it is a wire-format change touching firmware, the vendored
firmware copies and the parity manifest.

The README and ROADMAP claims for pairing, HEARTBEAT and the journal are struck.
The remaining eight flagged files need a look each; the script is the instrument,
and it says outright that it is a name-based proxy, not a compiler.

| shape | found by |
|---|---|
| module nothing references | `scripts/curation_survey.py` |
| file nothing references | `scripts/file_reachability.py` |
| type constructed, never interrogated | **nothing — read the code** |

The third wants method-level call-graph analysis. Until it exists, "documented and
tested" cannot be read as "runs".

## 3. What I would work in, in order

**Now, before any source moves:**

1. ~~**Rebuild the WASM and clear the gate.**~~ **Done 2026-07-30.** All four
   legs green, plus a new behaviour gate that executes the bundle. The headline
   claim is true again, and now checkable by anyone with node.
2. ~~**Reconcile ROADMAP.md with the code.**~~ **Done 2026-07-30.**
   `scripts/subsystem_ledger.py` derives the inventory — LOC, tests, reachability,
   which integration suites exercise each module, roadmap presence, claim strength
   and evidence strength — and `ROADMAP.md` carries the generated table. Bench and
   hardware validation are *declared* with citations, since no static analysis can
   see them. Remaining: give `power`, `comms`, `gnss` and `aerial` phase rows, and
   resolve the three ⚠ rows in §2.3.
3. **Decide `src/runtime/`: wire it or cut it.** 417 LOC, the only genuine island
   in the crate. `DockerRuntime::run_shell` is real; `WasmRuntime` is a
   self-described stub with no `wasmtime` dependency; `ShellTool` spawns `sh -c`
   directly and always has. I struck the doc claims today, so nothing false is
   published — but a `[~]` row is a bug in the roadmap as much as in the code.
   Wiring it is not a one-liner: the trait takes `(cmd, args, timeout)` and
   `ShellTool` takes one opaque string for `sh -c`.

**Then, the thing that unblocks the migration:**

4. **An authentication story for the spine.** `RESEARCH-2026-07.md` §3.2 already
   contains the shape of the answer, and it is more interesting than a pre-shared
   key: a physical-actuation authority profile over MCP — reversibility class,
   blast radius, velocity/force bound, geofence, dwell, energy budget, preemption
   rights — plus a lease model, using MRTR elicitation as the confirm gate. The
   research note calls this the clearest white space in the field and says *don't
   fork MCP, profile it.* I agree, and I would add: it is also the only item on
   the list that closes a release gate and stakes a differentiating claim with the
   same work. Node pairing (HMAC-SHA256) already exists in `src/security/pairing.rs`
   and is the obvious foundation.

**Then, and only then, the capability roadmap:**

5. Phase 19 (Real-Time Multimodal) and Phase 20 (Edge-Native Intelligence).

On that last point I want to be direct, because it is a disagreement with the
roadmap. `ROADMAP.md` says 19 and 20 are next and calls them "the user-facing
payoff". Under a migrate-piecewise policy I think that is the wrong order.
Phases 19 and 20 add substantial new surface — a realtime voice channel, on-device
models, wake-word, a new class of ambient node — to a system whose existing
surface is not yet documented accurately enough to migrate. Every capability added
before the ledger exists is another undefended piece in the queue. The research
doc's ordering (harden, then name what exists, then calibrate) is the one that
serves the migration; the roadmap's ordering serves a demo.

There is also an overdue item worth closing or explicitly deferring: Phase 15's
last open box, "flip default mode when the final spec ships (July 28)". The date
has passed; `ProtocolMode::default()` is still `Legacy2024`. I did not flip it,
because flipping a protocol default is a compatibility decision, not a
maintenance one — MCP servers that only speak `2024-11-05` are the reason the
dual mode exists, and I could not find a negotiation fallback that would make the
flip safe. Either add the fallback and then flip, or move the box and say why.

---

## 4. What I changed today

All verified. Where a gate was added, it was verified by making it fail.

**Oh-Ben-Claw**

| File | Change |
|---|---|
| `README.md` | Struck the sandbox claim in three places (Operations list, module tree, comparison table). The `\| Sandboxes \| ✗ \| ✅ native / docker / wasm \|` row asserted a security boundary that has never existed; a boundary a reader infers but does not get is worse than an absent one. Replaced with a short "Not a sandbox" note saying what `src/runtime/` is and is not. |
| `ROADMAP.md` | Six stale `[x]` rows for modules deleted on 2026-07-28 (`dashboard`, `hooks`, `rag`, `PersonalityStore`, `build_system_prompt()`, `PersonalityConfig`) now read `[-]` with the date and reason. The sandbox row reads `[~]`. Added a legend for both markers: `[~]` = written but not wired, `[-]` = removed, with the date. |
| `docs/playbooks/mesh-node-lost.md` | Told the operator to paste the procedure into `SOUL.md`. `PersonalityStore` read that file and was never called, so the instruction had never worked. Now points at `[agent].system_prompt`. |
| `scripts/curation_survey.py` | **Rewritten.** It reported four islands and three were wrong: its regex could not match `use oh_ben_claw::{config, gateway, …}`, so it named `gateway` (2,313 LOC, binds the whole HTTP API) and `tunnel` as removable. Use-trees are now brace-matched and expanded, including nested groups; the module list comes from `pub mod` in `lib.rs` so `src/bin/` is excluded by construction. Corrected output: **one** island, `runtime`, 417 LOC. |
| `src/tools/mod.rs` | Three new tests. Two types both return `"audio_transcribe"` with different required parameters — `AudioTranscribeTool` (`file_path`, registered) and `AudioTranscriptionTool` (`path`, never registered). Harmless today, a fabricated-answer bug the day someone registers it. `default_tools_have_unique_names` guards the registered set; `default_tools_are_describable` checks every tool has a usable schema; `audio_transcribe_name_is_still_claimed_twice` pins the hazard so it cannot be forgotten. |

The tools tests were run: 25 passed. The uniqueness guard was then verified by
adding the orphan to `default_tools()` and observing
`two tools registered under one name: audio_transcribe (x2)`, then reverting.
`cargo check --workspace --all-targets` is clean afterwards.

**OBC-Prime**

| File | Change |
|---|---|
| `scripts/sync_upstream.py` | Added `WASM_SOURCES` — the twelve upstream files `planner-wasm` compiles via `#[path]`. `sync` records their hashes in `MANIFEST.json` under `wasm_build`; `check --upstream` fails if any changed since. This is the only way a hash gate can see the *age* of a build. Also fixed the printed regeneration command from `--target web` to `--target nodejs` — the bundle is CommonJS and the generator `require()`s it, so following the old hint produced a bundle that broke the suite. |
| `parity/README.md` | "Three implementations" → two implementations in three executables, with the two failure modes named separately (the port can disagree on logic; the build can disagree on age). Removed the claim that the WASM runs "in a browser" — it is a `--target nodejs` build. |
| `docs/DECISIONS.md` | New entry, *A hash gate cannot see a stale build*. Also corrected the 2026-07-28 entry that said "a CI job that fails on any divergence — from the manifest, from upstream, or from the generator app's mirrors": the script checks all three, CI runs only the first. |
| `.github/workflows/parity.yml` | Added the `peer` job. The generator is public and needs no token, so this leg could always have run — it just never existed, commented or otherwise. Also corrected the `upstream` job's comment: repo access is not the only blocker, `planner-wasm/pkg/` is gitignored upstream so a plain checkout has no bundle to compare. It needs a `wasm-pack build` step too. |

**OBC-deployment-generator**

| File | Change |
|---|---|
| `tests/wasm-planner.test.ts` | Replaced `expect(scheme.config_toml).toContain("[peripherals]")` with a byte-for-byte comparison against `expected-config.toml`, matching the TypeScript leg. Comment explains the measurement and says not to re-narrow it. **This test fails until the WASM is rebuilt** — that is the point. |
| `.gitattributes` | Added. `core.autocrlf` was rewriting every file on checkout; `git status` showed 96 modified files whose content diff was empty. Matters more here than usual because this repo mirrors SHA-256-verified artifacts. |

**Accelerapp**

| File | Change |
|---|---|
| `.gitattributes` | Added. Same cause, 559 phantom-modified files → 0. |

---

## 5. Decisions only you can make

1. **`src/runtime/`** — wire it (Docker only, and delete the wasm stub) or cut it.
2. **The MCP default-mode flip** — add a negotiation fallback and flip, or move
   the deadline and record why.
3. **Phase 19/20 versus hardening.** §3 argues for hardening first. It is your
   call, and the case for 19/20 is real: they are the demo that makes people care.
4. ~~**Whether navigation/SLAM/fleet keep their SOTA comparison.**~~
   **Withdrawn.** This rested on the mistaken reading corrected in §2.3.
   `docs/SOTA-COMPARISON.md` already states its own gaps per component and calls
   its implementations simplified baselines. There is nothing to soften. The real
   question is narrower and is now row 1 of the ledger: `foresight` is compared
   against the state of the art and has no integration test.
5. **Accelerapp.** Its two good modules (`hardware/registry.py`, 210 LOC, 16
   tests; `firmware/obc_templates.py`, 123 LOC, 9 tests) are stdlib-only and
   correct, and both load fine in isolation. They are *not importable through the
   package*: `accelerapp/__init__.py` pulls in `core` which needs pydantic, and
   `core.py`/`core/`, `config.py`/`config/`, `exceptions.py`/`exceptions/` are all
   shadowed. Lifting the two files into `firmware/` is an afternoon; fixing the
   package is not. The repo is also 18 days stale relative to the other three.

---

## 6. What I could not verify

- ~~**The WASM rebuild.**~~ Done on 2026-07-30, on the author's machine —
  `static.rust-lang.org` is unreachable from this sandbox, so the wasm32 target
  could not be installed here. The result was then verified from this side by
  executing the rebuilt bundle against the goldens **on the device**, rather than
  against a staged copy. That distinction matters: the first attempt at this
  verification read a cached copy of the pre-rebuild bundle and wrongly reported
  the rebuild as ineffective.
- **The generator's 143 tests.** `node_modules/` is a Windows install, so
  `vitest` dies on a missing `@rollup/rollup-linux-x64-gnu` before collection. The
  substance of the widened assertion is verified — `parity/verify_wasm.cjs` makes
  the same comparison and now runs in CI.

  **Resolved 2026-07-30.** The suite was run against a clean `pnpm install`
  outside the Windows tree: **12 files, 155 tests, all passing**, including the
  widened whole-config assertion. `pnpm check` (tsc) and `pnpm lint` are clean
  too. The generator now has `.github/workflows/ci.yml` running all three, so its
  four TypeScript-port parity tests — the only automated check on the one
  implementation that can disagree with the Rust on *logic* — no longer depend on
  someone remembering. Note the count: 155, not the 143 quoted earlier, which came
  from grepping `it(`/`test(` and undercounted.
- **Accelerapp's 25 tests.** No pydantic, no pytest, no network in the device VM.
  Structural findings only.
- **The full core test suite.** I ran `cargo check --workspace --all-targets`
  (clean) and the `tools::tests` module. I did not run all 1,417 tests.
- **Navigation, SLAM, fleet, foresight behaviour.** Not tested. §2.3 is a claim
  about the absence of evaluation, not about the presence of bugs.
