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

> **Status: early.** The core agent runs, and is **not yet in this repository**.
> The firmware is — see [firmware/](firmware/README.md) — so there is something to
> flash and watch today, but nothing to talk to it with. See [PLAN.md](PLAN.md) for what is
> landing and in what order. Self-hosted first; a hosted option is not
> foreclosed but is not being built. Expect things to move.

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
