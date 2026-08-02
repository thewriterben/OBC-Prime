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
> repository** — but five crates of it now are. `obc-paths`, `obc-memory`,
> `obc-planner`, `obc-safety` and `obc-telemetry` are here, vendored and
> hash-checked, and CI builds and tests them: **370 tests** covering the
> bitemporal world model, the deployment planner the parity claim below rests
> on, the Track 0 safety layer `docs/SAFETY.md` describes, and the battery /
> link / sensor suites that feed the reflexes.
> The firmware is here in full — see [firmware/](firmware/README.md) — so there
> is something to flash and watch today, but nothing to talk to it with. See
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
scripts/     sync + drift tooling
docs/        design decisions and their reasoning
```

### The vendored substrate

`crates/` is the part of the agent this repository can *run* rather than only
hash. Everything else vendored here is data or a build; this is source, and
source that is never compiled is a listing:

```bash
cargo test --workspace     # 370 tests
```

Four pieces have moved, each chosen by measuring what was separable rather than
what sounded impressive, and each carrying the tests it had upstream:

| crate | what it is | tests |
|---|---|---:|
| `obc-memory` | the bitemporal world model — provenance, a support graph, and the four withdrawal mechanisms (supersession, source liveness, dependency withdrawal, retention) described in [docs/BELIEF-REVISION.md](docs/BELIEF-REVISION.md) | 83 |
| `obc-planner` | the deployment planner, site plan and peripheral registry — the Rust leg of the parity claim above, and the source the vendored WASM is built from | 165 |
| `obc-safety` | Track 0: risk classification, the deterministic actuator limit table, the hash-chained Ed25519-signed audit, argument taint tracking, node pairing, and the frame authentication [docs/SPINE-AUTH.md](docs/SPINE-AUTH.md) specifies — tag, replay window and outbound counter — [docs/SAFETY.md](docs/SAFETY.md) | 98 |
| `obc-telemetry` | body telemetry: battery, links and sensor streams classified into world-memory facts, each deriving a mode a reflex watches — `power.mode`, `net.mode`, `sensor.{quantity}` | 18 |
| `obc-paths` | where data lives, resolved in one place | 6 |

`obc-safety` is the one worth opening first if you are evaluating this. The
safety section above makes claims about bounds enforced below the host and about
an audit record that cannot be quietly rewritten. Until 2026-08-01 the document
making those claims was here and the code backing them was in another
repository, so the claims could be read and not checked. `docs/SAFETY.md`,
`docs/BELIEF-REVISION.md` and `docs/MEMORY-2026-07.md` all arrived before their
code, which is the wrong order and is now corrected for all three.

`obc-telemetry` is the newest, and it backs half of a claim this page makes
repeatedly: that the reflex layer keeps working when the brain is unreachable.
The node side of that has been checkable since the firmware was vendored; the
host side is these three suites, which turn a battery reading, a link's health
or a sensor sample into a world-memory fact plus a coarse mode — and it is the
mode a reflex rule watches, because a rule cannot reason about millivolts and
should not have to. The half still missing is the reflex *engine* itself, which
is behind thirteen dependencies in the core crate and cannot move yet.

None of them knows about tools, providers, the spine or the agent loop — that is
what made them separable, and it is the same test the next piece has to pass. It
is now a measured test rather than a judgement: the core repo's
`scripts/extractability.py` counts each module's outward edges, and
`obc-telemetry` was the first piece chosen by that count. Like everything under
`registry/`, `parity/` and `wasm/`, these are **copies**: authored in the core
repo, verified by SHA-256, and not to be edited here.

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
