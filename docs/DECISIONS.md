# Decisions

Short records of choices that are expensive to reverse, and why they were made.
New entries go at the top.

---

## 2026-08-14 — The mirror repository merges first, and the gate never said so

A sync that touches one of the generator's mirrored artifacts needs two pull
requests: the manifest and the vendored copy here, the rebuilt mirror there. The
`peer` job checks out the generator's **default branch**, so from the moment this
repository's PR opens until the generator's PR lands, the job reports:

    x wasm/obc-planner/obc_planner_wasm_bg.wasm: generator mirror DRIFTED

which is true, and points at the manifest, where nothing is wrong.

**Decision: the generator PR lands first.** Both orders leave one repository's
main briefly disagreeing with the other. Generator-first makes that window a job
that nothing re-triggers; here-first makes it a red main the moment the merge
button is pressed.

**Correction, same day.** The first version of this entry said the job "cannot be
fixed by making the job smarter", because a gate comparing two repositories has
to read *some* revision of the second and the only one it can name unaided is the
default branch. The second half is true; the conclusion was not. The job could
check out a generator branch whose name matches this PR's head ref when one
exists, and fall back to the default branch otherwise — an ordinary pattern, and
a real fix.

It is not taken, for a reason worth writing down rather than a reason to be
proud of: it makes a green CI run depend on a branch-naming convention that
nothing enforces. Name the generator branch differently and the job silently
falls back to the default branch and passes — which is the failure mode this
whole repository exists to avoid, moved one level up. Merge order is a rule a
person follows; branch-name matching is a rule CI *appears* to follow.

Revisit if a sync ever needs to prove a mirror before landing it. Until then the
order is the fix, and the sentence above is left in with its correction rather
than edited away, because an overstated claim in an append-only log is exactly
the thing the next reader would take at face value.

### The transferable part

The failure message was accurate and misleading, which is the same shape as three
other findings in this repository: the counts gate hiding a live number, the drift
gate measuring the wrong revision, the reachability survey guarding half its
inputs. A check that cannot distinguish "wrong" from "not yet" should say so in
the failure text, because the reader has no other source. Both the workflow
comment and the message itself now name merge order as the first thing to rule
out.

---

## 2026-08-13 — A crate owns its own configuration block, and that was the whole endgame

Recorded here because this repository has been following the rule since its
third crate without ever writing it down, and upstream's last seven dependency
cycles turned out to be the four places it had not been applied.

**The rule.** A module's configuration struct lives with the module. The root
`Config` composes it. `obc-planner` owns `DeploymentConfig`, `obc-conscience`
owns `ConscienceConfig`, `obc-cost` owns `CostConfig`, `obc-tunnel` owns its
own — every crate vendored here already works this way, which is why none of
them needed the root config module to exist in order to compile alone.

**What it cost to have four exceptions.** `ProviderConfig` was defined in the
root config module while two of its own field types lived in `providers`, and
all ten provider files imported the struct back. One struct, split across two
modules, pointing both ways — three cycles. `SpineConfig` and
`MeshSupervisorConfig` were four references and the entire dependency of a
5100-line module on anything else in the tree — four more cycles.
`AutonomyConfig` was two.

Moving each one to the module that reads it took the core from sixteen cycles
to zero. No interfaces were designed and no logic changed.

**Why it matters to a reader of this repository specifically.** The reason every
crate here can be built and tested with no siblings is this rule, applied by
accident at first and then on purpose. A crate that reaches into a central
config module for its own settings cannot stand alone, and the `substrate` job
would catch it — but only after someone had already written it that way. The
rule is the thing that stops it being written.

**One correction worth keeping**, because it is the argument for measuring
rather than reasoning. Upstream put `AutonomyLevel` and `AutonomyConfig` in
`agent` first, since the agent reads them. The cycle count stopped at two
instead of zero. Autonomy *level* is the approval policy — how much a human has
to confirm — and `approval` is the module that turns it into an
`ApprovalManager`. One module further, and the count went to zero.

The rule was right and the noun was wrong, and the instrument said so within
minutes. That is the more useful half of "measure rather than judge": not
measuring to prove you were right, but measuring so that being wrong is cheap.

---

## 2026-08-13 — At eight occurrences it is a rule, not a knack

An entry below, written yesterday, called turning an edge "the answer three
times now" and listed three. It is eight. Recording that as its own entry rather
than editing the count, because the number *is* the argument: three times is a
run of luck, eight times is a shape the codebase reliably produces.

| what left | what was in the way | what moved |
|---|---|---|
| `obc-movement` | `Arc<SpineClient>` in an actuator sink | the sink, to the spine |
| `obc-a2a` | nothing referenced it | an executor, written next to the agent |
| `obc-reflex` | `Arc<SpineClient>` in an action sink | the sink, to the spine |
| `tools -> agent` | two `use` lines in a `#[cfg(test)]` module | the tests, to `tests/` |
| `spine -> agent` | `Severity`, `DIGEST_PREFIX` in the notify module | the vocabulary, to `obc-reflex` |
| `agent <-> skill_forge` | `impl ReplayExecutor for Agent`, next to the trait | the impl, next to the type |
| `obc-fleet` | a 60-line MQTT bridge in the coordinator | the bridge, to the spine |
| `obc-audio` | two `SpeechSink` impls with dependencies | both impls, to the spine and the tool layer |

The shape: **a trait declared next to its caller, implemented next to its
caller, for a type that lives somewhere else.** Rust permits the implementation
in either place as long as one of them owns the trait, so the compiler never
objects. Only the dependency graph does, and only if something is looking.

Three of the eight were not production code at all — two test modules and a doc
comment. That is the least intuitive part and worth stating plainly: a `use`
line inside `#[cfg(test)]` and a rustdoc link are both dependency edges, and a
graph built from text cannot tell either one from a call in a hot loop.

`obc-fleet` is a genuinely different animal, and it is why this is a new entry
rather than `s/three/eight/`. The others were each one thing in the wrong place.
That one was the *same integration implemented from both ends* — the coordinator
bridging itself onto MQTT, while the spine was already bridging LoRa into the
coordinator from its own side. Both halves looked reasonable where they sat.
Neither is a mistake anyone made; it is what happens when two modules are each
maintained by someone who reasonably believes the integration is theirs.

The actionable consequence: **when a two-module cycle resists the "one misplaced
item" reading, look for a duplicated responsibility before looking for a design
problem.** It was faster to find than either.

---

## 2026-08-13 — Two crates arrived that nobody decided to move

`obc-foresight` (677 lines) and `obc-learning` (454) are here, and this entry
exists mostly to record that neither was a decision. They are the first
arrivals in this repository that were not selected — by reading imports, by
`extractability.py`, or by anyone weighing what the public repo most needed.
They fell out.

The chain, smallest thing last: `learning` was blocked by `foresight`,
`foresight` was blocked by `reflex`, and `reflex` was blocked by a single action
sink holding an `Arc<SpineClient>` — one field, one constructor parameter, two
topic constants. Turning that one edge released **2455 lines across three
crates** in three commits, and the two here moved no logic whatsoever: eight
paths spelled `crate::memory::world::` became `obc_memory::`, names that had
been a crate since 2026-07-30 and were still being read through the agent's
re-export table.

The entry below this one already argued that a blocking-edge count says nothing
about what an edge costs to turn. This is the same claim from the other end:
**turning one cheap edge can release work you were not planning to do.** The
useful consequence is scheduling, not philosophy — after any edge-turning
commit, re-run the survey before deciding what is next, because the answer may
have changed underneath the plan. Upstream's `docs/ENDGAME.md` predicted these
two specifically and was right about them, and wrong in the same paragraph
about which back-edges the move would break. Both halves are recorded there.

One thing here is a decision rather than a consequence: **the approval gate did
not come with `obc-learning`.** `tests/learning_approval_gate.rs` asserts that a
mined rule is inert until approved, and it does so against a real
`ForesightEngine` rather than a mock. Vendoring the crate without it would have
put a rule-synthesis engine in a public repository with its central safety
property untested here. Keeping it upstream is the honest option of the two
available — the alternative was a weaker local restatement — and it is why this
crate's row in the README says 4 tests rather than a number that flatters it.

---

## 2026-08-12 — Turn the edge; do not wait in the queue

`obc-reflex` is here, and the entry below it — dated 2026-08-01 — says the
reflex engine "is in the core crate's `agent/` behind thirteen blocking edges
and cannot move yet." That was true when written. What made it stop being true
is worth a decision record, because it changes how the queue is read.

The extraction queue is produced by upstream's `scripts/extractability.py`,
which ranks each module by how many outward edges point at something still in
the core tree. Read naively it is a work order: take the zeroes, wait on the
rest. Three times now the useful move has been the opposite — pick the edge
rather than the module, and reverse it:

| what left | what was blocking it | what moved |
|---|---|---|
| `obc-movement` | `Arc<SpineClient>` in one actuator sink | the sink, to the spine — 39 lines |
| `obc-a2a` | nothing; nothing referenced it either | an executor, written next to the agent |
| `obc-reflex` | `Arc<SpineClient>` in one action sink | the sink, to the spine |

The shape is the same each time: **the trait stays where the abstraction is, the
implementation goes where the dependency is.** The crate declares `ActionSink`
or `ActuatorSink` or `TaskExecutor`; the thing that needs the spine, or the
agent, implements it from the other side and stays behind. The dependency
arrow reverses without either side changing what it does.

The cost of not knowing this: `obc-navigation` is 3714 lines and was blocked by
`obc-movement`, which was blocked by 39 lines. Read as a queue, that is a large
job waiting on a medium job waiting on a small one. Read as edges, it is one
`Arc<SpineClient>` field holding back 4416 lines — `wc -l` across both crates'
`src/` as vendored here — and it took an afternoon.
`obc-reflex` at thirteen edges and `obc-navigation` at one looked like very
different problems and were not.

What the instrument cannot tell you, stated so nobody mistakes the ranking for
the answer: **a count of blocking edges says nothing about how expensive each
edge is to turn.** Thirteen small edges is a smaller job than one that runs
through a cycle. Upstream's `scripts/core_endgame.py` was written for the
second half of that sentence — what remains in the core is cyclic rather than
merely dense, and no ordering of extractions solves a cycle.

One other thing this entry records, because it is the same failure this
repository keeps documenting in its own code: **eleven crates arrived between
the entry below and this one, and none of them got an entry here.** The
narrative went into `scripts/sync_upstream.py` comments, the `substrate` job's
comment block and the README instead — all three of which are read more often
than this file, which is most of why it happened. The log was not wrong; it
just quietly stopped being the place the reasoning lived. It is not
back-filled here — inventing eleven contemporaneous records after the fact
would be worse than the gap — but the gap is now on the page rather than
implied by a date.

---

## 2026-08-01 — The next piece is chosen by a script now, and this is the first one

`obc-telemetry` — `power`, `comms`, `sensing`, 1,015 lines, 18 tests — is the
fourth crate vendored here and the first that nobody picked by reading imports.

The core repo now has `scripts/extractability.py`: per module, the outward
edges, split into *blocking* (points at something still in that tree) and *free*
(points at a crate that has already left, which a new crate can simply depend
on). It is the mirror of the existing `curation_survey.py`, and the two ask
opposite questions — who references this, versus what does this reference. Only
the second one predicts whether a piece can move. The three suites were among
six modules with zero blocking edges.

Two things about that script are worth carrying over here, because this
repository is downstream of its judgement:

- **Its first version was wrong, in the direction that would have cost a week.**
  Counting only `use crate::…` declarations, it reported `config` — 3,430 lines,
  58 dependents — as having no outward edges. It has six; its struct fields are
  typed with inline paths like `pub server: crate::mcp::McpServerConfig` that no
  `use` line records. That is the same failure the sibling script was corrected
  for in July, which is why the two now share one parser.
- **The verdict was then confirmed by a compiler**, before anything moved:
  `src/comms/mod.rs` compiled in a scratch crate whose entire universe was
  `obc-memory`, serde and anyhow. A survey saying "no blocking edges" and a
  compiler agreeing are different claims, and only the second is load-bearing.
  The extraction that followed needed no call-site changes at all.

Why these three and not `scheduler`, `a2a` or `observability`, which were
equally movable: the queue says what *can* move, not what *should*. The README
says the reflex layer keeps working when the brain is unreachable, on ten
separate lines, and backed it only with vendored firmware. The three suites are
the host side of that — each turns a raw reading into a world-memory fact plus a
coarse mode (`power.mode`, `net.mode`, `sensor.{quantity}` and a quality flag),
and the mode is what a reflex rule watches, since a rule cannot reason about
millivolts.

Stated plainly rather than left to be found: this backs half the sentence. The
reflex *engine* is in the core crate's `agent/` behind thirteen blocking edges
and cannot move yet. A claim half-backed and labelled as such is worth more than
one wholly unbacked and unlabelled, but it is not the same as done.

---

## 2026-08-01 — Track 0 comes here third, because the safety claim was the one a reader could not check

`obc-safety` is the third crate vendored from the core agent, after `obc-memory`
and `obc-planner`. The order was not chosen by importance — on importance this
one goes first. It was chosen by separability, which is the only thing that makes
a piece movable, and Track 0 did not become separable until upstream fixed a
dependency that pointed the wrong way.

Three of its files — `audit.rs`, `taint.rs`, `trust.rs` — imported `RiskClass`
and `BlastRadius` from `crate::tools`, so the safety layer depended on the
largest and least self-contained module in the tree. Those four types are the
*contract* the tool layer is checked against, not tool machinery. Upstream moved
them down into `obc-safety::risk` and had `tools::traits` re-export them, which
left the crate with no outward edges and made this vendoring a copy rather than a
negotiation. Extraction is usually blocked by exactly one edge pointing the wrong
way, and the fix is usually to move the contract down rather than the consumer up.

What this changes for a reader: `README.md` and `docs/SAFETY.md` claim that
actuator bounds are enforced below the host, that every physical action and every
refusal lands in a hash-chained Ed25519-signed record, and that a privileged call
whose arguments echo untrusted content is refused. Until today all three claims
were documented here and implemented somewhere else. `cargo test -p obc-safety`
now runs 65 tests of that code in this repository, in CI, on every push. The
document arriving before its code is the wrong order, and this is the third and
last of the three where that had happened.

Not fixed by this, and worth stating in the same breath: node **pairing** is
vendored here as `pairing.rs` and is inert upstream — `pair_node` and `is_trusted`
have no callers, so the spine is still unauthenticated (see `docs/SPINE-AUTH.md`
and `docs/MIGRATION.md` §2.4). Vendoring the code does not wire it. What it does
is put the primitive and its 386 tested lines where the design document that
depends on them already lives.

---

## 2026-08-01 — `sync` skips what `check` already skips

`sync` refused to run at all against a clean upstream checkout. Seven artifacts —
five wasm build outputs and two firmware `Cargo.lock`s — are gitignored upstream,
so they are simply absent from a fresh clone, and `do_sync` aborted on the first
missing source. `check --upstream` had known about exactly these seven since
2026-07-30, by name and with a reason each; `sync` did not. The same knowledge,
encoded in one command and not its sibling.

It surfaced the way these things do: vendoring `obc-safety` — twelve files with
nothing to do with WASM — was blocked by a WASM bundle that was never going to be
there.

`sync` now skips them and **carries their manifest entries forward**, which is
the part that had to be right. The manifest is rebuilt from what a run copied, so
skipping without carrying would have silently dropped seven artifacts from the
gate — turning "cannot sync" into "no longer checked", which is strictly worse
than the abort it replaces. The recorded hash wins over re-hashing the file on
disk, so a hand-edited vendored copy still fails `check` instead of being
laundered into the manifest by the next sync. Skips print on every run, like
`check`'s do.

---

## 2026-07-30 — The peer check keeps a credential, because the alternative is trusting a mirror

The `peer` job checks the 11 artifacts the deployment generator mirrors. It went
red on PR #2 and stayed red, and the interesting part is how long it took to stop
looking for drift.

Everything measurable said the mirrors were identical: 56 artifacts passing
locally; passing against `git archive main` of the generator, which is
byte-for-byte what `actions/checkout` produces; no CR anywhere; the same hash for
`registry.json` across the OBC-Prime worktree, the generator worktree, and the
generator's committed blob; the 13 crate artifacts correctly carrying no peer
path. Every one of those checks was about the comparison. The failure was
upstream of the comparison — the checkout — and no amount of hashing reaches it.

**The generator repository is private.** That is now measured rather than
asserted: the job failed on the peer checkout, a fine-grained PAT with
`Contents: read` went in as `PEER_REPO_TOKEN`, and all four jobs went green. An
earlier version of this workflow asserted the opposite — "the generator is public
and needs no token" — with nothing having checked, and `PLAN.md` saying otherwise
in the same tree.

The decision was whether to keep the job at all. The case for deleting it is real:
when it was written the generator had no CI, and it does now — `ci.yml` runs the
same four planner-parity tests against the same goldens, including the widened
`wasm-planner.test.ts` that compares the whole config instead of asserting it
contains `[peripherals]`. So this leg is no longer the only guard, and it is a
guard that needs a credential with an expiry to function.

Kept anyway. The generator's own CI proves its planner agrees with the goldens
*it has*; this job proves the goldens it has are the ones this repository
published. Those are different claims, and the second one is the entire point of a
mirror. A vendored copy nobody compares is a copy that has already forked and has
not been told.

The cost is honest and written into the workflow: when the PAT expires this job
fails on checkout with "Repository not found", which reads exactly like drift and
is not. A drift failure names a file and two hashes. That sentence is in
`parity.yml` so the next person spends a minute rather than an afternoon.

### The transferable part

When a check that compares two things fails, the reflex is to interrogate the two
things. The comparison was never reached. Read the log before reproducing the
comparison — one line of it would have replaced an hour of hashing, and the hour
of hashing produced only evidence that everything it could see was fine.

---

## 2026-07-30 — Hashes prove identity; only execution proves correctness

The stale-build entry below fixed the *detection* of a bundle built from old
sources. Confirming that fix exposed the gap one level up: **nothing in this
repository ran the bundle.** Every gate here compares hashes, which answers "is
this the file we recorded" and cannot answer "is this the right file".

The assertion that would have caught the original bug lived in the generator's
vitest suite — a different repository, which has no CI at all, and which needs an
npm install to run. So the public project could not check its own headline claim
without a private sibling and a toolchain.

`parity/verify_wasm.cjs` closes that. It loads the vendored bundle, runs
`plan_deployment`, `deployment_toml` and `plan_site` against the vendored
fixtures, and compares the whole generated config byte for byte. It needs node
and nothing else — the bundle is a CommonJS `--target nodejs` build and the
fixtures are in this repo — so it runs as a CI job rather than as a thing someone
remembers to do. Verified in both directions: green on the current bundle, and
failing with a line-by-line diff against the pre-rebuild one recovered from
`git show HEAD:`.

The manifest also now records the **toolchain** that built the bundle (rustc,
wasm-pack, and wasm-bindgen from the lockfile). It is not a gate and does not
fail anything: a compiler bump legitimately rewrites the `.wasm` with no source
change, and the drift gate is right to stay green for it. It is there so that a
200 KB binary moving for no visible reason is a one-line diff rather than an
hour of archaeology. It populates on the next `--rebuild-wasm`; back-filling it
with a guessed rustc version would be a wrong number written down, which this
file already records two instances of.

One process note, worth more than the code. The stale bundle was first
"confirmed still broken" after the rebuild — against a cached copy of the *old*
file, in a scratch directory, while the correct new file sat on disk a few paths
away. The wrong conclusion was reached with real evidence, cleanly presented. The
fix was to stop testing copies: `verify_wasm.cjs` runs against the vendored path
in the repository, and the artifact under test is never staged, mirrored or moved
first. Verifying a copy verifies the copy.

---

## 2026-07-29 — A hash gate cannot see a stale build

The parity mechanism hashes every vendored artifact and fails on any change. It
had been verified by corrupting a file and watching it fail. It was still blind
to the largest divergence in the repository, and blind by construction: **a
compiled artifact cannot drift from its own hash.**

`wasm/obc-planner/` was built on 11 July. On 28 July `src/deployment/planner.rs`
was rewritten three times — "one canonical config, fixtured whole", "align role
assignment, and delete the mask", and the `claude-sonnet-5` pin — and
`expected-config.toml` was re-blessed with it. Every hash in `MANIFEST.json`
still matched. `check --upstream --peer` reported all 43 artifacts identical.
The bundle emitted a 79-line config where the golden had 119, carrying the old
system prompt and a hardcoded `[provider] name = "openai" / model = "gpt-4o"`.

The test that should have caught it was the narrow-gate failure this project has
already documented once. `planner-parity.test.ts` carries a long comment about
how a golden covering only `[deployment]` hid a real divergence for months, and
that comment sits above an assertion comparing the *whole* config byte for byte.
Twenty lines away, `wasm-planner.test.ts` checked
`expect(scheme.config_toml).toContain("[peripherals]")`. The lesson was written
down, applied to one leg, and not carried to the other. Writing down a lesson is
not the same as applying it everywhere it holds, and the second leg is exactly
where nobody looks.

Two changes, because the two failure modes are different:

- **The manifest now hashes the WASM's build inputs**, not only its output —
  the twelve upstream sources `planner-wasm` compiles via `#[path]`, declared as
  `WASM_SOURCES`. `check --upstream` fails if any has changed since the recorded
  build. This is the only way a hash gate can see the age of a build.
- **`wasm-planner.test.ts` compares the whole generated config** to the golden,
  matching the assertion on the TypeScript leg.

Both were verified by observing them fail: the missing-build-inputs branch
against the real manifest, and the stale-source branch by injecting a
pre-rewrite hash for `planner.rs` and confirming the error names that file.

Cost, and it is a real one: **the gate is red until the bundle is rebuilt.**
`wasm-pack build planner-wasm --target nodejs`, then `sync --upstream`. It is
red because the repository is in the state it describes, and a gate that goes
green on a known-stale artifact to spare the commit would be the original bug
with extra steps.

> **Resolved 2026-07-30.** Rebuilt and re-synced. All four legs green; the
> vendored bundle now renders the 119-line golden config, and `verify_wasm.cjs`
> confirms it by execution. Only `obc_planner_wasm_bg.wasm` changed
> (223,822 → 235,572 bytes) — the JS glue, `.d.ts` and `package.json` are
> byte-identical, so `wasm-bindgen` had not moved and there was no API drift. The
> goldens did **not** need re-blessing: the planner sources were always right, it
> was only the build that was old.
>
> Two things were found while confirming it, and both are now closed:
>
> 1. **`sync` could clear the gate without earning it.** Recording the current
>    source hashes next to a bundle it had merely copied would launder the exact
>    staleness the mechanism exists to catch. The `wasm_build` block is now
>    written *only* by `--rebuild-wasm`, in the run that invoked wasm-pack, and
>    carries `built_by_this_script: true`. A plain `sync` carries the previous
>    hashes forward untouched.
> 2. **`sync` never updated the generator's mirrors.** Only `check` knew about
>    `--peer`, so a rebuild would land here and leave the generator's copy behind
>    — and the error message said `fix with: sync`, which for that case was
>    false. `sync --peer` now exists.

Two smaller things fell out of the same pass. The documented regeneration
command said `--target web`; the bundle is `--target nodejs` and the test
`require()`s it, so following the printed hint produced a bundle that broke the
suite. And `parity/README.md` called this "three implementations" running one
"in a browser" — it is two implementations in three executables, and the browser
one is not built.

---

## 2026-07-28 — Retention is declared; everything else is a consequence of the world

Three mechanisms withdraw a belief because something changed: a newer value
arrived, its author stopped reporting, or something it rested on went away.
Retention is the fourth, and the only one that fires because a human wrote a
rule. That asymmetry drives its whole design.

An agent's own note is unreachable by the other three — nothing rewrites
`incident.<subject>`, the agent does not stop existing, and an assertion rests on
nothing recorded. Six such notes were still believed ten days after the
investigation that produced them concluded. So the mechanism has to exist.

But its blast radius is a string someone typed, so it only ever does what it is
told: nothing expires by default, an empty prefix is rejected rather than treated
as "everything", malformed policies are reported at `ERROR` rather than skipped,
`source.*` can never be expired, and `due()` is a dry run.

Age comes from `ingested_at`, not `valid_from` — the latter is a caller-supplied
tool parameter, so postdating a claim would otherwise buy it immortality.

On a shared namespace the origin filter is the entire safeguard: `mesh.` holds
the radio's evidence alongside the agent's notes, and `origins = ["asserted"]` is
what keeps a retention rule from ageing out the mesh itself.

---

## 2026-07-28 — Debounce is a rate limit, not a novelty test

A reflex asked "has enough time passed since I last fired?". For a condition that
stays true, the answer is eventually always yes, so a rule watching a standing
state re-fires forever at the debounce interval. In practice the vision rules
escalated to a 30B reasoner every hour, indefinitely, on images from 6 July,
because "a verified person was detected" never stopped being true.

Snapshots now carry the **row id** of each fact, not just its value, and a rule
may require those ids to differ from the ids at its last fire. Two ticks reading
the same row are the same observation; two ticks reading different rows with equal
values are not.

Opt-in, and it must stay that way. A safing rule *should* keep firing while a
dangerous state holds — "the battery is still critical" is worth repeating, and
suppressing it because the reading has not changed is exactly backwards. Only the
vision rules opt in.

A snapshot with no ids never suppresses: value-only snapshots (a node, a
simulation) cannot speak to evidence identity, and missing identity is not
evidence of sameness.

Cost: the wire format grows a field, defaulted for compatibility, and rule state
grows a second map.

---

## 2026-07-28 — Restating a belief is not new evidence

Applied at both write boundaries, for the same reason and with very different
volumes.

Every write supersedes: it closes the open row and appends a new one with a fresh
timestamp. So a writer that reads a fact and writes it back makes a stale belief
look freshly confirmed — and if that writer is the agent, by an agent that learned
it from that same belief. It also defeats source liveness directly, since an echo
lands under `agent`, and a silent source the agent keeps restating never looks
silent.

The agent's `world_memory` tool now refuses a no-op restatement, and says what is
already there rather than returning an error to work around.

The same rule at the perception boundary is where the volume was: the ClawCam
poll re-read its source every 60 s and recorded everything it saw, turning 50
distinct events into 9,600 rows and a deer count of 5,418 from 28 real detections.
Ingest is idempotent on event id; dedup is per entity, not global, since one event
yielding two subjects is two beliefs; a detection with no event id is written
through, because duplicates are recoverable and missing detections are not.

Counters were an accumulator, so the error compounded rather than washing out and
had to be repaired by a recount from distinct events. Corrected, not deleted — the
inflated values remain in `history()`.

---

## 2026-07-28 — Unknown support and no support are different states

`world_facts.derived_from` records the facts a derived belief was computed from
— Doyle's JTMS in-list. It has three states, and the first two are deliberately
not merged:

- `NULL` — unknown support. Every row written before the column existed, and
  every caller that has not been taught to declare its inputs.
- `[]` — explicitly self-standing. A premise.
- `[ids…]` — rests on these.

The reason the distinction is load-bearing: `observe()` already defaults to
`Origin::Derived` as its fail-closed default, so most rows are typed `Derived`
without anyone having thought about where they came from. If an invalidation
sweep read `NULL` as "nothing supports this", its first run would retract the
entire store.

The column is **not backfilled**. `origin` was, partially, from source labels —
support cannot be, because a wrong in-list is worse than an absent one: the
absent one is inert, the wrong one gets walked. `dependents()` therefore cannot
see unknown-support rows at all, so sweeps under-retract rather than
over-retract. A corrupted in-list parses back to `NULL`, never to `[]`, since
`[]` is the stronger claim.

`dependents()` is deliberately not transitive. A belief with several supports
may survive one of them dying (`a+b`) or may not (`a·b`); making the query
transitive would decide that for every caller.

Cost: the graph is only as good as its coverage, which starts near zero and
grows one write site at a time. `support_coverage()` reports the gap so it
cannot be quietly ignored.

---

## 2026-07-28 — The name is Open Body Control

Keeps the `OBC` acronym, which is already the binary name, the config directory
and a decade of muscle memory in aerospace and robotics where it means
*On-Board Computer*. That existing meaning is inherited rather than fought.

"Open ..." positions this as a layer to build against rather than a product to
buy — the model is Open Sound Control. "Body" is the honest word: this is not a
chatbot with plugins, it is an agent with nodes, sensors and actuators.

The vocabulary that follows — brain, body, senses, reflexes, escalation — is
already the vocabulary of the code (`obc-brain`, the reflex controller, the
System 1 / System 2 split), so the naming and the architecture agree.

Rejected: *Onboard Control* (safer, less distinctive), *Open Brain & Claw*
(preserves heritage, doesn't explain itself), *Open Bot Core* ("bot" invites
exactly the chatbot association the project is trying to avoid).

---

## 2026-07-28 — A clean public repo, with the core agent as upstream

Rather than renaming the existing private repo, or building a monorepo of all
four projects.

The private repo carries a long changelog and a number of subsystems
that are declared, documented, and not wired up. A rename would make all of
that the public first impression. A four-way monorepo would additionally drag
in a codebase whose own headline CLI is broken.

The clean repo lets each piece move over when it is defensible, which is also
the order in which its documentation can be written honestly.

Cost: vendored artifacts must be kept in sync across repo boundaries. That cost
is paid by `scripts/sync_upstream.py` and the parity CI gate — see below.

---

## 2026-07-28 — Parity is enforced by hash, not by convention

The board registry, the golden fixtures and the planner WASM bundle exist in
three repositories. They were previously kept in step by hand-copying, with no
sync step and no verification. The only thing that caught a stale copy was a
test failing afterwards, in a different repository, for a reason that looked
unrelated.

Now: one declarative list of vendored artifacts, a manifest of SHA-256 hashes,
and a check that fails on any divergence — from the manifest, from upstream, or
from the generator app's mirrors.

The gate was verified by deliberately corrupting a vendored file and confirming
a non-zero exit with an actionable message, then restoring it. A gate that has
never been observed failing is not known to work.

> **Corrected 2026-07-29.** This said "a CI job that fails on any divergence".
> The *script* checks all three; **CI runs only the first**. `parity.yml` invokes
> a bare `check`, and the `--upstream` job is commented out. There has never been
> a `--peer` job at all. So on any given push, a hand-edit to a vendored file is
> caught and drift against the core agent is not — which is the more likely
> failure of the two, because the core agent is where the work happens. The
> capability was described as if the wiring existed. See §"A hash gate cannot see
> a stale build" for the second, worse gap in the same mechanism.

Deliberate limitation: a bare `check` can only prove nobody hand-edited a
vendored file. It cannot prove the manifest itself is current — that needs
`--upstream`. The tool says so in its output rather than implying a stronger
guarantee than it verified.

---

## 2026-07-28 — Reference Bodies ship with seeded data

A Reference Body is a complete deployment — config, firmware, and a database
with real recorded history — that runs before any hardware exists.

The reasoning is about the first two minutes. A newcomer who can clone, start
the agent, and watch a reflex fire on a real detection understands the System 1
/ System 2 split immediately. The same person reading a description of it does
not. Seeded data converts documentation into evidence.

It also makes the bodies genuinely reusable: Trailwatch becomes a security
perimeter or a livestock monitor by changing `alert_subjects`, with no code
change. The reflex rules and escalation playbooks are the transferable part,
and they are only legible when you can watch them run.

---

## 2026-07-28 — Delete the subsystems that were never wired, and stop hiding them

Release gate 3. `src/lib.rs` opened with
`#![allow(dead_code, unused_imports, unused_variables)]`. That one line is why
the curation problem existed at all: the islands were not a historical accident,
they were invisible **by configuration**. Nothing ever warned.

Removed: `dashboard`, `rag`, `satcom`, `hooks`, and `memory/personality.rs`,
plus the `[personality]` config section that outlived the store it configured —
2,036 lines that parsed, documented themselves, and did nothing. A config key
that loads cleanly and has no effect is worse than a missing feature, because
the config file is the surface a user actually reads. (Safe on upgrade: the root
`Config` does not `deny_unknown_fields`, so a leftover `[personality]` block is
ignored rather than becoming a parse error.)

**Kept, against the survey's advice: `a2a`.** The first pass cut it too. Then
`tests/evals.rs` — the release-gate eval file — failed to compile with thirteen
unresolved references. The survey only scanned `src/`. Integration tests are a
whole category of consumer it never looked at, which is a good argument for not
trusting a reference count you did not write the scanner for. `scripts/curation_survey.py`
now scans `tests/`, `examples/` and `benches/` too.

The blanket allow is gone and must not return. Suppression is now narrow, at the
item or file, with a stated reason: the chat-platform modules carry a scoped
`#![allow(dead_code)]` because their structs mirror a vendor's webhook payload
and deleting unread fields would make them a worse description of the wire.

What the lint found once it could speak: a mission could trip a guard, halt
navigation and end without a single log line saying why. The reason was going
into world memory but never to the operator's terminal. That is now logged.

Warnings went 0 (suppressed) → 32 → **4**, and all four are honest: a field or
method that is declared and genuinely not used yet. A short list of real
warnings is worth more than a clean build that means nothing.

---

## 2026-07-28 — Two repos, one statement of which is which

Release gate 4. Both repos were MIT and both had a LICENSE. What neither had
was a sentence saying which repo a change belongs in — so a stranger looking at
Oh-Ben-Claw could not tell it was the upstream core of this one, or that
`registry.json`, the golden fixtures and the planner WASM are emitted there and
vendored here by hash.

Both now open their CONTRIBUTING with the same routing table, and both READMEs
link to it. The vendored artifacts get an explicit licence sentence: they
originate upstream, same author, same terms.

The larger finding was in the four commands the upstream CONTRIBUTING had
always told contributors to run before opening a PR. Two of them had never
passed on a clean checkout: `clippy -- -D warnings` (the gate-3 warnings plus
an unexpected-cfg in the WASM crate) and `cargo fmt --all --check` (736 diff
hunks across 81 files, because it had never been run). CI ran both, so CI had
been failing too.

A check that fails on a clean checkout teaches everyone who meets it to ignore
that check, which then costs nothing to keep failing. That is the same failure
mode as the crate-wide `allow` removed in gate 3, in a different medium — and
it is why the fix was to make the commands pass rather than to soften them.
`-D warnings` stays, and `--all-targets` was *added*, because the survey that
skipped `tests/` is precisely how a live module nearly got deleted.

Cost, stated: the first `cargo fmt --all` is a 4,796-line mechanical commit
sitting on top of every `git blame`. Mitigated with `.git-blame-ignore-revs`
and one line of setup in CONTRIBUTING, not eliminated. Rustfmt defaults were
kept rather than tuning `max_width` until the diff got small, which would have
been tailoring the standard to the mess.

---

## 2026-07-28 — One data root, resolved once, movable by one variable

Release gate 5. The gateway turned out to be fine — host and port are config,
so "one per machine" was never welded in. The data was the problem, and it was
worse than a single-user assumption: there were two conventions running at the
same time.

Half the state used the platform data directory. The other half — approval
grants, harness records, the skill-evolution log, the install audit, the rollout
record, the gateway's staging directory — hardcoded `$HOME/.oh-ben-claw` by
reading `HOME`/`USERPROFILE` directly. The documentation named `~/.oh-ben-claw`
throughout, describing neither arrangement on Windows.

Consequence: a user's data was split across two directories, the docs named a
third, and nothing could move any of it. `OBC_CONFIG` relocated the config file;
there was no equivalent for data. Two agents on one machine shared one database,
one audit chain and one set of standing permission-to-act grants.

Now: `OBC_DATA_DIR` → `[paths].data_dir` → platform convention, resolved in one
module, twelve call sites through it. The platform convention rather than a home
dotdir, because `~/.oh-ben-claw` is a Linux habit that is wrong on the other two
platforms this project runs on.

The config search gains `config.toml` in the data root, above the platform
directory, which is what makes a relocated instance self-contained. The
environment beats the config key deliberately: a config file gets checked in and
copied between machines, and starting a second instance should not require
editing one the first instance reads.

**This is not multi-tenancy and is not claimed as such.** It removes the
single-tenant assumption from a dozen call sites so that a hosted deployment
needing per-tenant isolation changes a resolver instead of excavating. That was
the whole ask: don't foreclose it.

Verified by running two instances side by side, not by reading the code — one
relocated with its own config, database and agent name, the other untouched on
the platform default. `doctor` now prints the resolved root and which of the
three sources chose it.

Also found: the upstream README documented a `setup` wizard and a `service`
manager, neither of which has ever existed, and the install instructions told a
new user to run `oh-ben-claw setup` first. Corrected against `--help` output.
Gate 2 removed the need for a wizard anyway — a provider key in the environment
and no config file is a working first run.

---

## 2026-07-28 — The operate token belongs in the keychain, and arming is an act

The deployment generator's fleet console held the gateway's **operate token** in
`AsyncStorage` — a plaintext file in the app sandbox. That token is not a login:
presenting it on a mutating request lets the holder drive physical hardware
through a running gateway.

What made it clearly a bug rather than a judgement call was the asymmetry inside
the same app. `lib/_core/auth.ts` already used `SecureStore` for the session
token. The token that actuates a robot did not.

Three decisions in the fix:

- **The migration deletes the plaintext copy.** Moving the token into the
  keychain and leaving the old file behind fixes nothing and fails silently:
  everything keeps working, and the file everyone was worried about is still
  there. The test for this was watched failing against a version with the delete
  removed — a gate never observed failing is not known to work.
- **Web keeps it in memory only.** `SecureStore` has no web implementation and
  `localStorage` is no better than what is being replaced. So on web it survives
  only as long as the tab, and the UI says so rather than implying a protection
  that is not there.
- **Arming is no longer automatic.** The saved token is offered back into the
  input so nobody retypes a secret, but the console does not come up ARMED
  because it was ARMED yesterday. Elevation to physical control should be
  something you did, not a state you woke up in.

The console also now says when the gateway URL is plain `http`, because storing
a secret safely and then putting it on the wire in cleartext is a strange place
to stop. Not blocked — a trusted LAN is a legitimate deployment — just said.

---

## 2026-07-28 — Firmware is vendored, not moved

The plan said *move* the two Rust firmware crates here. Checking before cutting —
the habit the `a2a` near-miss bought — showed that moving would have deleted the
only tests that firmware actually runs.

`heltec-lora-linktest` builds for `xtensa-esp32s3-espidf`, so `cargo test` inside it
compiles its tests for the microcontroller and cannot execute them. Upstream,
`tests/firmware_spine_framing.rs` `#[path]`-includes `src/spine.rs` and compiles it
for the host, which is what puts the frame codec, the relay de-dup ring and the line
framer under ordinary `cargo test`. That harness exists because of a real incident:
the bridge transmitted two mid-string fragments after the host wrote two commands
back to back.

So the firmware joins the registry, the fixtures and the planner WASM as a vendored,
hash-checked artifact. Cost: contributors edit upstream and re-sync, same as the
others. Benefit: the flashing guide and the sources it describes cannot drift.

All four firmwares came over, not the two the plan named. Two are Arduino sketches,
which is the only entry point for the reader who has a board and no Rust toolchain —
and the first user this project is written for is someone with an ESP32 in a drawer.

### The thing that fell out of it

Vendoring 32 more text files made a latent bug impossible to ignore: **this
repository has never passed its own drift gate on a fresh Windows clone.** The
Windows Git installer sets `core.autocrlf=true` and there was no `.gitattributes`,
so cloning rewrote every text artifact to CRLF and every SHA-256 changed. The gate
then reported the three planner implementations as disagreeing when nothing had
diverged at all — on the one claim the README leads with, from the first commit.

Confirmed by cloning to a temporary directory and watching `check` fail on all 42
artifacts, `registry.json` included, then pass after `* text=auto eol=lf` — the same
`.gitattributes` the core agent already had, which is exactly why upstream never hit
this and this repo did.

---

## 2026-07-28 — Benchtop ships without hardware verification, and says which half

Trailwatch runs with nothing plugged in because it carries 14 days of real
recorded detections. Benchtop cannot: its whole point is the live path, and a
fabricated sensor history would be teaching a reader to trust numbers nobody
measured — the failure the bodies README already warns about.

The alternative to shipping it dishonestly was not shipping it, and that was
worse: the body existed as an inventory in the generator with no runtime half,
so the two places a Reference Body is supposed to live disagreed.

So it ships with a verification table at the top. Verified: the config parses and
the agent starts from it (`doctor` reports 0 errors, 2 reflex rules); the
`[deployment]` block is planner-emitted rather than hand-written; the hardware
resolves with zero capability gaps. Not verified: a BME280 actually firing the
reflex, and the Track 0 limit refusing a command on a physical node. **A
reference body you cannot fully run is worth shipping if it is honest about which
half you are getting.**

### Two findings from generating it rather than writing it

**The generator's emitted config had two dead keys and no brain.** `[agent] model
= "grok-4"` — `model` is not an `[agent]` key — and `max_iterations`, which is
spelled `max_tool_iterations`. Unknown keys are not rejected, so both parsed and
did nothing, in the first config a stranger ever receives. No `[provider]` block
at all. The Rust planner emits the correct schema, so this was TypeScript-only
drift that the parity gate never saw, because the fixtures cover the
`[deployment]` block and the site plan — **not** the config preview. The
byte-identical claim is true of what is fixtured and was not true of the section
a user pastes. `parity/README.md` now says so; widening the fixture is open work.

**An absent `[provider]` is not a stated one.** Gate 2 said an explicit config is
never second-guessed. Right about the file, wrong about a section it does not
contain: `serde`'s default supplied `openai/gpt-4o`, so a body that deliberately
left the brain unspecified greeted an Anthropic-key holder with "No API key found
for provider 'openai'". Resolution now fills an unnamed provider from the
environment. The test keys on `provider.name`, not on the `[provider]` table —
found by running the body, whose `[provider.retry]` block creates that table
without choosing a vendor and so silently opted itself back out.

---

## 2026-07-28 — A narrowed gate needs an expiry condition

The parity fixtures covered the `[deployment]` block and the site plan. The claim
they backed was "three implementations produce byte-identical output" — true of
what was fixtured, false of everything else, and everything else is the part a
user pastes into their config file.

Widening the golden to the whole generated config exposed two layers of
divergence, and the way each was handled is the decision worth recording.

**Layer one: the emitters had drifted into different sections.** Rust emitted
`[edge]` and a hardcoded `[provider]`; the TypeScript port emitted
`[fleet.lora_serial]`, `[memory]` and a different `[agent]`. Neither was a superset
of the other. Merged to one canonical output with **the agent's own config schema
as arbiter** — not a style call, because the root `Config` does not reject unknown
keys, so a key outside the schema parses cleanly and does nothing. Three had
accumulated that way, all in the first config a new user reads.

**Layer two: the planners disagreed about what the deployment does.** Given the
same hardware they assigned different tool sets. That could not be fixed in the
same change, and the tempting move — widen the fixture to exclude it — is exactly
what caused the original problem.

So the mask shipped with an **expiry assertion**: a test asserting the divergence
was *still present*, which fails the moment the mask stops being necessary. It
fired on the next change. The mask is gone and the comparison is now byte-for-byte
with nothing excluded.

**A gate narrowed to accommodate a known problem becomes permanent unless
something fails when the problem goes away.** That is the transferable part.

The alignment itself used the **tool registry** as arbiter, and found invented
names: the orchestrator was being handed `file_read`, `file_write`, `http_get` and
`memory_note` (the real tools are `file`, `http`, `memory`), while the TypeScript
orchestrator lacked the four delegation tools that are the reason an orchestrator
exists. It also surfaced a real bug the port had already fixed and the core had
not: `audio_sample` is the *microphone* capability, so testing it for "has a
speaker" described a listen-only board as playing synthesised speech through a
speaker it does not have.

---

## 2026-07-29 — CI was red, and only on the platform nobody was building on

Three CI jobs were failing. All three were invisible locally, because the author
develops on Windows and CI runs `ubuntu-latest`. Reproduced by exporting the tree
into a Linux container and running the CI steps verbatim rather than reading the
YAML.

**The wasm crate could never have compiled on Linux.** `#[path]` inside an
*inline* `mod peripherals { … }` block resolves against a directory named after
the module — which did not exist. Windows normalises the `..` components lexically
before touching the filesystem, so it resolved anyway. Linux requires every
component of a path to exist. The first step of build-and-test therefore failed on
every push.

That is the worst shape a build failure can have: **green for the only person who
can fix it.** Fixed by making the shim directories real.

**Four security advisories, for a feature that does not exist.** `rustls-webpki
0.102.8` carries four RUSTSEC advisories in certificate and CRL handling, arriving
solely through `rumqttc`'s `use-rustls` feature, with no upgrade path — rumqttc
0.25.1 pins the same version.

It was also unreachable: `src/spine/mod.rs` never calls `set_transport`, so
MQTT-over-TLS has never worked. The project was shipping a vulnerable
certificate-validation stack for a capability it does not have. Dropping the
feature removes the advisories rather than suppressing them.

Which forced the honest half: **`[spine] tls = true` now refuses to start.** Every
other dead config key in this codebase merely did nothing. This one told an
operator their broker link was encrypted when it was cleartext — and three tests
asserted the reassuring warnings it produced, which is how the missing feature
stayed hidden. A warning would not be enough; someone who set that key made a
security decision and is entitled to learn it did not take effect.

### The transferable part

A green local build is not evidence about CI when the two run different operating
systems, and neither is reading the workflow file. The cheap version of this check
is to run the CI steps on the CI platform once, which took one export and a
container.

Stated as not-verified: the aarch64 cross-compile job could not be reproduced —
`static.rust-lang.org` is unreachable from the sandbox, so the target's std would
not install. It runs on Linux and would have hit the same `#[path]` failure at step
one, so it is *probably* fixed by the same change. Probably is the honest word.
