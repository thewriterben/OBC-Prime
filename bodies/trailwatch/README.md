# Trailwatch — reference body

A wildlife and perimeter camera deployment. **Runs with no hardware attached**:
it ships with a seeded database of 14 days of detections, so you can watch the
full stack work before deciding whether to build anything.

What it exercises, end to end:

```
camera detections  ->  world memory  ->  reflex rules  ->  escalation  ->  notification
                                              |
                                     LoRa mesh node health
```

## Try it in two minutes

Needs Python 3 (standard library only) and a running model provider. Nothing to
edit, nothing to install.

```bash
cd bodies/trailwatch
export OBC_CONFIG=config.toml      # PowerShell: $env:OBC_CONFIG="config.toml"
obc start
```

Run it **from this directory** — the paths in `config.toml` are relative to the
working directory, and the agent also needs somewhere writable to work.

Within a second of startup you should see:

```
Loaded config from "config.toml" (explicit)
ClawCam MCP bridge connected (actuation + poll)
ClawCam detections folded into world memory count=50
reflex: escalate to System 2 reason="person detected (verified) on a camera"
System 2: waking the slow reasoner
Gateway listening url=http://127.0.0.1:8090
```

Those middle lines are the point. A camera saw a person, a reflex fired without
waking the language model, and only then did it escalate — with a triage
playbook attached. That's the System 1 / System 2 split, running on your
machine, with nothing plugged in.

Exactly two escalations should appear: the verified person, and a
calibration-drift warning (the seeded model is deliberately miscalibrated —
83.9% precision against a 90% target, with 0.79 suggested as a better accept
threshold).

If you also see a stream of "a mesh node is presumed lost", that is **not** this
body — it means the agent's world memory already holds a
`mesh.escalated_count >= 1` from some earlier deployment on the same machine.
The rule is doing its job; the fact is stale. Clear that entity, or start with a
fresh data directory. On a clean install this body produces no mesh escalations
at all, because a missing entity never satisfies the condition.

## What's in the body

| File | Purpose |
|---|---|
| `config.toml` | The whole deployment: brain, perception, reflexes, escalation, gateway |
| `serve.py` | Standalone MCP perception server over the seeded database |
| `clawcam_gateway.db` | Seeded detections — 13 days, 187 classifications, one anomaly day |
| `README.md` | This file |

### serve.py

The production perception source for this body is a separate camera gateway
project with its own virtualenv. Depending on it would mean nobody could try
Trailwatch without installing something else first, so this body ships its own
server: standard library only, reading the seeded SQLite.

It is also the shortest readable specification of what a perception source has
to implement — a three-method JSON-RPC handshake over stdio and seven tools.
Swap it for your real gateway when you have one; the agent cannot tell the
difference as long as the tool names and payload shapes match.

One detail worth copying if you write your own: `tools/call` returns
`{"content": [{"type": "text", "text": "<json>"}]}`, and the agent parses *that
string* as JSON. The payload is not the JSON-RPC result itself. Getting this
wrong is the quietest way to have a perception source that connects fine and
returns nothing.

### What's in the seeded data

187 classifications over 13 days from one camera (`node-001`): white-tailed
deer (93), red fox (42), coyote (37), person (15). 94 verified by human review,
18 rejected, 75 unreviewed — which is what makes the calibration report
meaningful, since only reviewed rows have ground truth.

## The parts worth stealing

**Perception polling.** `[perception.clawcam_poll]` runs a detection source over
MCP and folds results into world memory on an interval. Any MCP server that
lists observations can be swapped in here.

**Vision rules.** `[perception.vision_rules]` turns observations into alerts:
which subjects matter, whether unreviewed detections count, and how long to
debounce. Change `alert_subjects` from `["person"]` and this becomes a
livestock monitor, a loading-bay watcher, or a lab-door alarm without touching
code.

**Escalation budget.** `[system2]` caps model wakes per hour and suppresses
repeats within a novelty window. Without this an always-on agent with a noisy
sensor will wake the model continuously and pin your GPU.

## Tuning notes learned the hard way

- **`interval_ms` on a static database re-folds the same rows forever.** The
  seeded DB doesn't change, so a 5s poll produced the same 25 detections
  endlessly and re-fired the same reflexes. It's set to 60s here. With live
  cameras, tune to your capture rate.
- **`debounce_ms` is doing real work.** At 10s against static data the same
  person detection escalated every eleven seconds. It's 1h here.
- **`mesh_supervisor` is off by default.** It is what *writes*
  `mesh.escalated_count`, so with no LoRa board attached it would mark every
  configured node lost and escalate on a loop — a critical alert for the fact
  that nothing is plugged in. Turn it on when you actually have a mesh. The
  safing rule that reads that count stays enabled, and is silent until then.
- **Vision costs a model swap.** Image analysis loads a vision model; on a 12GB
  card that evicts the main model. Expect a pause on the way in and out.

## Going live

1. Replace `clawcam_gateway.db` with your gateway's real database.
2. Set `capture_node` to a real node id.
3. Set `require_state = "unreviewed"` if you want alerts before human review.
4. Enable `mesh_supervisor` once nodes exist.
5. Set `webhook_url` under `[notifications]` to reach a real destination.
