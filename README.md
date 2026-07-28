# Open Body Control

**An embodied agent system: one brain, a mesh of bodies, and a planner you can trust.**

OBC gives a local language model a body — a mesh of microcontroller nodes,
cameras, sensors and actuators — plus the reflexes to react without waiting for
the model, and the judgement to escalate when reflexes aren't enough.

It runs entirely on your own hardware. No cloud, no API keys, no per-token cost.

> **Status: early.** The core agent runs. This repository is the public home
> being assembled around it — see [PLAN.md](PLAN.md) for what is landing and in
> what order. Expect things to move.

---

## The claim worth checking first

The deployment planner exists in **three independent implementations** — the
Rust planner inside the agent, a WASM build of it, and a TypeScript port that
runs in the browser-based deployment generator.

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
| `bodies/benchtop` *(planned)* | One ESP32-S3 over serial. The five-minute on-ramp. | One dev board |

Start with Trailwatch. It exercises the entire stack — perception → world
memory → reflex → escalation → notification — in about two minutes, on a
laptop, with nothing plugged in.

## Repository layout

```
registry/    board + accessory registry (69 boards, 34 accessories) — SSOT, emitted by the core
parity/      golden fixtures + manifest that hold the three planners to identical output
wasm/        the planner compiled to WASM, so a browser plans exactly as the device does
bodies/      ready-to-run reference deployments
scripts/     sync + drift tooling
docs/        design decisions and their reasoning
```

## Getting the agent

**The core agent is not public yet.** This repository currently holds the parts
that can stand on their own — the registry, the parity harness, and a reference
body you can read. Commands here that take `--upstream ../core` assume you have
the agent checked out beside this repo, which for now means you are the author.

`firmware/` is likewise not here yet; node sketches and codegen land once the
firmware bridge moves over. Better to say so than to ship an empty directory.

`registry/`, `parity/fixtures/` and `wasm/` are **vendored, not authored here**.
They are copied from the core agent by `scripts/sync_upstream.py` and verified
by hash. Editing them by hand is what the drift gate is there to catch.

## Licence

MIT. See [LICENSE](LICENSE).
