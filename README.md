# Open Body Control

**An embodied agent system: one brain, a mesh of bodies, and a planner you can trust.**

OBC gives a language model a body — a mesh of microcontroller nodes,
cameras, sensors and actuators — plus the reflexes to react without waiting for
the model, and the judgement to escalate when reflexes aren't enough.

**Bring your own model.** Point it at Anthropic, OpenAI, OpenRouter or any
OpenAI-compatible endpoint with an API key and an ordered fallback chain — or
run it against a local Ollama and pay nothing per token. The provider is one
config block; nothing else in the system changes.

The bodies are yours either way. They run on your hardware, on your network, and
the reflex layer keeps working when the brain is unreachable.

> **Status: early.** Most of the core agent runs and is **not yet in this
> repository** — but twenty-one crates of it now are. `obc-paths`, `obc-memory`,
> `obc-planner`, `obc-safety`, `obc-telemetry`, `obc-observability`,
> `obc-scheduler`, `obc-conscience`, `obc-position`, `obc-cost`, `obc-tunnel`,
> `obc-a2a`, `obc-movement`, `obc-navigation`, `obc-tool-api`, `obc-reflex`,
> `obc-foresight`, `obc-learning`, `obc-fleet`, `obc-audio` and `obc-mission`
> are here, vendored and hash-checked, and CI builds and tests them: **658
> tests** covering the bitemporal world model, the deployment planner the parity
> claim below rests on, the Track 0 safety layer `docs/SAFETY.md` describes, the
> perception and reach gates `docs/CONSCIENCE.md` describes, the battery / link
> / sensor suites that feed the reflexes, the spans and counters the agent
> records about itself, the position sources that put a node on a map, the spend
> tracker, the tunnel providers that let a gateway on a home network be
> reached without opening a port, the A2A endpoint that lets another agent
> discover this one and send it work, the actuation path that every one of
> those safety bounds exists to constrain, the localization, SLAM and
> planning stack that decides where to go, and the reflex engine itself — the
> rules that fire on sensed state without waking the model, which this page has
> claimed since its first paragraph and could not show until now — plus the
> predictive layer above it, which fires on a *forecast* threshold crossing
> instead of a present one, and the layer above that, which mines the history
> for rules nobody wrote and holds them inert until someone approves them —
> plus, as of 2026-08-13, the multi-node coordinator that decides which robot
> takes which task, the audio suite that records what was heard and said as
> facts on the same footing, and the mission runner that advances a guarded
> sequence of steps across restarts.
>
> CI runs them twice: once as a workspace, and once per crate with no siblings —
> and that second pass runs both `cargo check` and `cargo test`, because a lib
> built as a test target links its dev-dependencies and can hide a dependency it
> genuinely needs. Both distinctions were found by a crate walking through the
> weaker check: obc-tunnel on the features, obc-a2a on the dev-dependency, and
> obc-mission on the same distinction read backwards — `cargo check -p` green
> while `cargo test -p --all-targets` failed on four `#[tokio::test]`
> attributes a check never builds. Three crates, three ways through, one job.
> The firmware is here in full — see [firmware/](firmware/README.md) — so there
> is something to flash and watch today, and `cargo run -p obc-demo` runs the
> safety gate, the planner and the perception gate on the host. What is still
> missing is the agent that drives them: no brain talks to a board yet. See
> [PLAN.md](PLAN.md) for what is landing and in what order. Self-hosted first;
> a hosted option is not foreclosed but is not being built. Expect things to move.

---

## The claim worth checking first

The deployment planner runs as **three executables from two implementations** —
the Rust planner inside the agent, a WASM build of that same source, and a
hand-written TypeScript port in the deployment generator.

> Corrected 2026-08-01. This paragraph said "three independent implementations".
> `parity/README.md` was fixed on 2026-07-29 and this one was not — the same
> one-leg-of-two miss that the parity gate itself was found guilty of. The
> hand-written port is the leg that can disagree on *logic*; the WASM build is
> the leg that can disagree on *age*. Naming them separately is what makes the
> gate legible, and the honest claim is still the strong one.

All three produce **byte-identical output**, enforced by golden fixtures and a
drift gate in CI:

```bash
python scripts/sync_upstream.py check --upstream ../core --peer ../generator
```

That means the deployment you design in a browser, with no backend and no
device attached, is provably the same deployment the agent will run on metal.
Planning tools that "should" agree with the runtime are common. Ones that are
tested to agree, byte for byte, are not.

See [parity/README.md](parity/README.md) for how it's enforced and what breaks
it.

---

## Safety

An agent that can move things needs its safety story stated, not implied.
[docs/SAFETY.md](docs/SAFETY.md) covers the threat model and every control —
including the two that are unusual:

- **The deterministic limit table is enforced on the microcontroller as well as
  the host.** A compromised host, a poisoned skill or a hallucinated tool call
  still cannot drive an actuator outside the bounds the node itself holds. The
  host is not in the trusted computing base for bounds enforcement.
- **Every physical action, including every refusal, is recorded in a hash-chained
  HMAC log** with optional Ed25519 detached signatures for third-party
  verification.

That document is equally explicit about what is *not* covered — semantic safety,
an unauthenticated spine, OCR'd text reaching the reasoner, and stale beliefs. If
you are evaluating this for anything that matters, read §4 first.

## Anatomy

The vocabulary is load-bearing — it maps directly onto the code.

| Term | What it is |
|---|---|
| **Brain** | The agent process. Talks to a local model, owns tools, memory and the gateway API. |
| **Body** | A deployment: boards, transports, roles and the peripherals attached to them. |
| **Senses** | Perception sources — cameras, audio, GNSS — folded into a world memory. |
| **Reflexes** | Rules that fire on sensed state without waking the model. Fast, cheap, always on. |
| **Escalation** | When a reflex can't resolve something, it wakes the model with a playbook. |

## Reference Bodies

A Reference Body is a complete, runnable deployment: config, firmware, and a
seeded database so **it runs before any hardware arrives**.

| Body | What it is | Hardware needed to try it |
|---|---|---|
| [`bodies/trailwatch`](bodies/trailwatch) | Wildlife / perimeter camera. Species detection into world memory, alert reflexes on verified person detections, mesh node health over LoRa. | None — ships with 14 days of seeded data |
| [`bodies/benchtop`](bodies/benchtop) | One ESP32-S3 over serial with a sensor. The smallest deployment that still exercises the whole brain-to-node path. | One dev board + a BME280 |

### Start here

Three steps, each one adding exactly one thing. Stop at any of them.

**1. A brain.** One environment variable, no config file:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # or OPENAI_API_KEY, OPENROUTER_API_KEY
```

No key at all is also fine — the agent falls back to a local Ollama, which needs
none. You do not write a config to get started; you write one to pin a choice
you have already made.

**2. Trailwatch — nothing plugged in.** The whole stack, on a laptop, in about
two minutes: perception → world memory → reflex → escalation → notification. It
ships 14 days of real recorded detections, so a camera sees a person, a reflex
fires *without waking the model*, and only then does it escalate. That System 1 /
System 2 split is the thing worth seeing before you buy hardware.

**3. Benchtop — one board.** Flash `obc-esp32-s3` (see
[firmware/](firmware/README.md)), wire a BME280, breathe on it. The reflex fires
on a real reading you caused. Read Benchtop's verification table first: it says
which parts have been run and which have not.

> Steps 2 and 3 need the core agent, which is **not in this repository yet** —
> see [Getting the agent](#getting-the-agent). Step 1 and the firmware are
> available today.

## Repository layout

```
crates/      memory, planner and Track 0 — vendored agent source this repo builds and tests
registry/    board + accessory registry (69 boards, 34 accessories) — SSOT, emitted by the core
parity/      golden fixtures + manifest that hold the three planner executables to identical output
wasm/        the planner compiled to WASM, so a planning service needs no Rust
bodies/      ready-to-run reference deployments
demo/        runnable demonstrations of the vendored crates (written here, not vendored)
scripts/     sync + drift tooling
docs/        design decisions and their reasoning
```

### The vendored substrate

`crates/` is the part of the agent this repository can *run* rather than only
hash. Everything else vendored here is data or a build; this is source, and
source that is never compiled is a listing:

```bash
cargo test --workspace     # 658 tests
cargo test -p obc-navigation # and once more per crate, with no siblings
```

And three things you can watch instead of read:

```bash
cargo run -p obc-demo -- gate        # Track 0 refusing an out-of-range command
cargo run -p obc-demo -- plan        # A* with and without a robot radius
cargo run -p obc-demo -- conscience  # the perception gate failing closed
```

`demo/` is the first host binary in this repository and the only Rust here that
is **not** vendored — it is written here, like `scripts/` and
`parity/verify_wasm.cjs`, which is why it sits outside `crates/`. It mocks
nothing: the gate is `obc_safety::SafetyGate`, the planner is
`obc_navigation::planning::plan`, the conscience is `obc_conscience::Conscience`.
When `gate` prints REFUSED, a deterministic limit table refused it.

That matters because "658 tests pass" and "you can see it refuse" are different
kinds of evidence, and only the second one survives someone who does not trust
the person showing it to them.

Twenty-one pieces have moved, and how they were chosen changed partway through.
The first eighteen were chosen by measuring what was separable — and two of
those were not chosen at all, `obc-foresight` and `obc-learning`, which fell out
of the crate before them. The last three were not separable when the day
started. They came out of upstream going after the dependency *cycles*
deliberately, and each was released by turning one edge around. Each carries the
tests it had upstream. The counts below are the 654 unit tests plus the 4
doctests; until 2026-08-02 this line said "370 tests" and counted only the unit
tests, which was the sort of quiet exclusion this page otherwise objects to.

**If you want to write something rather than read something, start with
`obc-tool-api`.** It is 175 lines and no implementation: the `Tool` trait, the
result type, and the Track 0 vocabulary — risk class, blast radius, rollout
stage, output trust — that a tool declares about itself. `obc-safety` is the
other half, the gate that reads `risk_class()` and decides. Between them you can
write a tool and watch it be refused without any of the agent being present.

It is also the first crate here extracted for a reason other than being
separable. Upstream's tool module is 9052 lines and sits in several of the
cycles that make the agent core unextractable; thirty of that core's measured
crossings were this one file, because three other modules needed the contract
and had to name the whole module to get it.

Not every arrival is a crate: `obc-conscience` gained its decision log, 163
lines that belonged inside it rather than beside it. And `obc-a2a` is here
later than it could have been on purpose — it was upstream's cleanest
extraction candidate for months precisely because nothing referenced it, which
is the same sentence read two ways. It was given an entry point first. A
protocol implementation nobody can start is worse in a public repository than
in a private one, because here it reads as a feature.

`obc-movement` is worth a sentence for the opposite reason. It was blocked for
months by **one** edge — a single `Arc<SpineClient>` field in the one actuator
sink that talked to the spine. Upstream moved that sink to the spine, where it
implements this crate's trait from the other side: 39 lines, one commit. Behind
it `obc-navigation` — 3714 lines of particle filter, pose-graph SLAM and A*
costmap, six times the size of the crate it was waiting on — followed the same
day, with nothing refactored and four of its nine files byte-identical. An
extraction queue is mostly not a queue of large jobs; it is a queue of small
edges pointing the wrong way, and this repository now has the two commits to
show for it.

The second command is not a nicety. `--workspace` unifies Cargo features across
every member, so a crate can use a feature of a shared dependency it never
declared as long as anything else in the graph declares it — and `obc-tunnel`
arrived doing exactly that, twice. The workspace build here caught one of the
two. The other was caught only by compiling that crate with nothing beside it.
CI now does both.

| crate | what it is | tests |
|---|---|---:|
| `obc-memory` | the bitemporal world model — provenance, a support graph, and the four withdrawal mechanisms (supersession, source liveness, dependency withdrawal, retention) described in [docs/BELIEF-REVISION.md](docs/BELIEF-REVISION.md) | 83 + 2 doc |
| `obc-planner` | the deployment planner, site plan and peripheral registry — the Rust leg of the parity claim above, and the source the vendored WASM is built from | 165 |
| `obc-safety` | Track 0: risk classification, the deterministic actuator limit table, the hash-chained Ed25519-signed audit, argument taint tracking, node pairing, `SecretString` (redacts in `Debug` and `Display`; the only way out is a greppable `.expose()`), and the frame authentication [docs/SPINE-AUTH.md](docs/SPINE-AUTH.md) specifies — tag, replay window and outbound counter — [docs/SAFETY.md](docs/SAFETY.md) | 104 |
| `obc-conscience` | Track 0 extended to the front of the pipeline: what the agent may **observe** (consent registry, default-deny for humans, fail-closed label classifier) and what it may **reach** (egress allowlist), plus decision replay, multi-party consent, and the append-only decision log replay runs on — [docs/CONSCIENCE.md](docs/CONSCIENCE.md) | 45 |
| `obc-telemetry` | body telemetry: battery, links and sensor streams classified into world-memory facts, each deriving a mode a reflex watches — `power.mode`, `net.mode`, `sensor.{quantity}` — plus `NodeState`, the heartbeat every other layer reads | 23 |
| `obc-observability` | the agent watching *itself* rather than its body: structured spans, a bounded span ring buffer, and the in-memory counters the gateway's metrics endpoint serves | 18 + 1 doc |
| `obc-position` | where a node actually is: MAVLink-style geodetic telemetry and raw NMEA 0183 `GGA` sentences, projected through a site frame into the `NodeState` the fleet coordinates on | 16 |
| `obc-scheduler` | cron, interval and one-shot tasks in SQLite, surviving restarts — what turns "check the perimeter every hour" into something the agent does unasked | 16 + 1 doc |
| `obc-tunnel` | Cloudflare, ngrok and Tailscale behind one interface, so a gateway on a home network can be reached without opening a port — the crate whose under-declared tokio features are why CI now compiles each crate alone | 14 |
| `obc-a2a` | Google's Agent-to-Agent v1.0: the wire types, the JSON-RPC task lifecycle and the HTTP transport, so another agent can discover this one and send it work — 5 of its tests drive a real socket | 23 |
| `obc-movement` | the act side of perceive→remember→reflex→act: typed actuator commands bounded by the Track 0 gate *before* they reach hardware, recorded into world memory as `actuator.{name}` facts, dispatched through a pluggable sink — the caller `obc-safety`'s limit table exists to constrain | 14 |
| `obc-navigation` | Monte Carlo localization against a beam model and likelihood field, pose-graph SLAM with loop closure, occupancy and inflation cost maps, A* with an admissible heuristic, frontier exploration, pose fusion — the largest piece moved so far, and the one that needed no refactoring to move | 55 |
| `obc-reflex` | System 1: a rule language of conditions and actions evaluated against world memory without waking the model, with debounce, rate limits, an escalation budget and a pluggable action sink — the same evaluator that runs mirrored on the node, and the half of this page's reflex claim that had no host-side code here until now | 29 |
| `obc-foresight` | Track 1: trend forecasts fitted to each entity's bitemporal history, and rules that fire on a *predicted* threshold crossing — `battery predicted ≤ 10% within 60s → return to base` acts while the pack is still at 20% and draining. Forecasts are written back into world memory, so a rule that fired on a bad forecast leaves the bad forecast behind as evidence | 11 |
| `obc-learning` | the layer that authors rules nobody wrote: mine the history for conditions that repeatedly preceded a bad outcome, propose an anticipatory rule with support and confidence, and hold it **inert** until a human or policy approves it. The approval gate is asserted upstream against a real engine, which is why the count here is small | 4 |
| `obc-fleet` | multi-node coordination: a registry of who is where with how much left, a task auction that allocates by cost rather than by turn, and frontier exploration handed out with a minimum separation so two robots do not crowd one pocket. Knows nothing about how a node is reached — the MQTT bridge that used to live here is on the transport's side now | 9 |
| `obc-audio` | hearing and speaking, both recorded into world memory as facts with an `Origin` — so what the agent *said* is evidence on the same footing as what it heard. Ships the `SpeechSink` trait and the one implementation that depends on nothing, which is what makes audio output a safe dry run until a real engine is wired | 6 |
| `obc-mission` | an ordered sequence of guarded steps advanced against world memory, so a multi-step job survives a restart and can say where it got to | 5 |
| `obc-tool-api` | the contract, with no implementation: the `Tool` trait, `ToolResult`, and the Track 0 vocabulary a tool declares about itself. The smallest crate here and the one to read first if you intend to write a tool | 0 |
| `obc-cost` | what the agent spends: per-call token accounting in SQLite, daily budgets and the warning before the ceiling — so "bring your own model" comes with a number attached rather than a surprise | 8 |
| `obc-paths` | where data lives, resolved in one place | 6 |

`obc-safety` is the one worth opening first if you are evaluating this. The
safety section above makes claims about bounds enforced below the host and about
an audit record that cannot be quietly rewritten. Until 2026-08-01 the document
making those claims was here and the code backing them was in another
repository, so the claims could be read and not checked. `docs/SAFETY.md`,
`docs/BELIEF-REVISION.md` and `docs/MEMORY-2026-07.md` all arrived before their
code, which is the wrong order and is now corrected for all three.

`docs/CONSCIENCE.md` was the fourth, and the worst instance of it. It went up on
2026-08-04 describing a consent registry, an egress allowlist and audited
refusals as wired and live, and cited `crates/obc-conscience/examples/` — a path
that existed in neither repository. The code was real and was not fabricated;
it sat on an upstream branch whose pull request had already merged, twenty-one
commits ahead of every main, where nothing was going to look at it again. It is
here now, so the document and the code arrived in the right order in the end,
two days apart. Recording the two days because the alternative is a repository
that only ever looks like it got things right the first time.

`obc-telemetry` backs half of a claim this page makes repeatedly: that the
reflex layer keeps working when the brain is unreachable. The node side of that
has been checkable since the firmware was vendored; the host side is these three
suites, which turn a battery reading, a link's health or a sensor sample into a
world-memory fact plus a coarse mode — and it is the mode a reflex rule watches,
because a rule cannot reason about millivolts and should not have to.

The other half — the reflex *engine* — is `obc-reflex`, and it arrived on
2026-08-12. That entry said it was "behind thirteen dependencies in the core
crate and cannot move yet", which was true when written and stopped being true
one edge at a time. The last of the thirteen was a single action sink holding an
`Arc<SpineClient>`: one field, one constructor parameter, two topic constants.
Upstream moved the sink to the spine, where it implements this crate's
`ActionSink` from the other side, and the crate followed. That is the third time
the same manoeuvre has been the answer — `obc-movement` and `obc-a2a` were the
other two — and it is worth stating plainly, because the counting instrument
upstream ranks candidates by how many edges block them and is therefore silent
about which edges are *cheap to turn around*. Thirteen and one looked like very
different numbers and were not.

One test did not come with it. A case asserting that an agent-*reported*
temperature must not actuate while a driver-*measured* one must needs the tool
layer to say what it means, so it is an integration test upstream now rather
than a unit test here. It is the one place the vendored copy is knowingly
thinner than the original, and this sentence is why the count says 28.

`obc-foresight` and `obc-learning` arrived the next day and neither was chosen.
`learning` was blocked by `foresight`, `foresight` was blocked by `reflex`, and
`reflex` was blocked by one action sink holding an `Arc<SpineClient>` — one
field, one constructor parameter, two topic constants. **2455 lines came out
from behind that one field**, across three commits, and the two crates above
moved no logic at all: eight paths spelled `crate::memory::world::` became
`obc_memory::`, names that had been a crate here since July and were still being
read through the agent's re-export table.

That is the third time in this list a large piece has followed a small one —
`obc-navigation` behind `obc-movement` behind 39 lines was the first — and it is
the reason the ranking upstream produces is a reading order rather than a work
order. A count of blocking edges says nothing about what each edge costs to
turn. `obc-reflex` was listed at thirteen and left on one move; `obc-navigation`
was listed at one and was worth 3714 lines.

One dependency in `obc-learning` is worth a sentence because it is the argument
for the second CI pass in miniature. The crate needs `anyhow`, which appears in
no `use` line anywhere in it — both call sites write `anyhow::Result<…>` inline
in a return type. That is the same shape that made upstream's extractability
survey report the config module as edge-free in its first version. No amount of
reading imports finds it; `cargo check -p obc-learning` found it in seconds.

`obc-fleet`, `obc-audio` and `obc-mission` arrived on 2026-08-13 and were chosen
differently from everything above them. Every crate before them left because it
was found to be separable. These three were not separable that morning. They
came out of upstream going after the dependency *cycles* directly, and each was
released by turning one edge around:

| crate | what was holding it | what moved |
|---|---|---|
| `obc-fleet` | a 60-line MQTT bridge inside the coordinator | the bridge, to the spine |
| `obc-audio` | two `SpeechSink` impls, one holding a spine client, one a TTS tool | both impls, to the spine and the tool layer |
| `obc-mission` | `obc-audio` | nothing — it came free |

`obc-fleet` is the one worth reading twice. The bridge it was carrying —
heartbeat ingress, assignment topic and payload — was a second implementation of
an integration the spine was *already* doing from its own side for the LoRa
transport. Two ends, one integration, and only one of the ends was the
transport. That is what a two-module cycle often turns out to be, and it is less
comfortable than a misplaced file, because both halves looked reasonable where
they sat.

What this repository is deliberately not printing: a cycle count. Upstream has
one and it moved a long way, but it also found that the script producing it had
been treating the config module as already-extracted — a regex with an optional
group matching `pub use config::Config;` — which made every edge *into* config
invisible and every count low. That is written up in upstream's
`docs/ENDGAME.md`. A number this repository cannot re-run is a number it should
not repeat, and the correction is more useful than the figure anyway.

`obc-observability` is the smallest honest thing in the
list: no claim on this page rests on it. It is here because it was next by the
measure below, it costs one dependency and no hardware to run, and it is what a
running body's spans and counters come from — the part you read when a reflex
fired and you want to know how long it took. Its Cargo.toml is worth a look for
one detail: upstream compiled the module in a scratch crate against nothing but
its six external dependencies *before* extracting it, so "self-contained" was a
compiler's verdict and not a survey's — and that build corrected the survey,
which had missed three attribute-macro dependencies it structurally cannot see.

None of them knows about tools, providers, the spine or the agent loop — that is
what made them separable, and it is the same test the next piece has to pass. It
is now a measured test rather than a judgement: the core repo's
`scripts/extractability.py` counts each module's outward edges. `obc-telemetry`
was the first piece chosen by that count and `obc-observability` the second.

`obc-position` is the first pair chosen by *changing* that count rather than
waiting for it. `aerial` and `gnss` each named exactly one thing from the fleet
coordinator — `NodeState`, a 25-line heartbeat struct — and that single import
pinned a 177-line and a 336-line module to an 823-line module neither otherwise
touches. Moving the struct to `obc-telemetry`, where it belonged, took both to
zero blocking edges in one commit. Turning an edge around is cheaper than
waiting for one to come loose, and it is the same manoeuvre that freed
`obc-safety`; the difference is that this one was done on purpose.

Like everything under `registry/`, `parity/` and `wasm/`, these are **copies**:
authored in the core repo, verified by SHA-256, and not to be edited here.

## Getting the agent

**The core agent is not public yet.** This repository currently holds the parts
that can stand on their own — the registry, the parity harness, and a reference
body you can read. Commands here that take `--upstream ../core` assume you have
the agent checked out beside this repo, which for now means you are the author.

[`firmware/`](firmware/README.md) **is here** — four firmwares with a flashing
guide. One ESP32-S3 and the Espressif toolchain gets you a node that runs its own
reflex and safing loops and self-safes with no host connected, which is the part of
the safety claim you can check yourself. Two LoRa boards get you a link. What you
cannot do yet is talk to a node from an agent, because the agent is the piece that
has not moved.

`registry/`, `parity/fixtures/` and `wasm/` are **vendored, not authored here**.
They are copied from the core agent by `scripts/sync_upstream.py` and verified
by hash. Editing them by hand is what the drift gate is there to catch.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) — in particular, which of the two repos a
change belongs in. Agent behaviour is developed upstream; the vendored
artifacts here are copies checked by hash and must not be edited in place.

## Licence

MIT. See [LICENSE](LICENSE). The vendored artifacts under `registry/`, `parity/`
and `wasm/` originate in the core agent repository and carry the same terms.
