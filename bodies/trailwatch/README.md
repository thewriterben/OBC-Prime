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

```bash
# 1. point the agent at this body
export OBC_CONFIG=$PWD/bodies/trailwatch/config.toml     # PowerShell: $env:OBC_CONFIG=...

# 2. run
obc start
```

Within seconds of startup you should see, in the log:

```
ClawCam MCP bridge connected (actuation + poll)
Phase 18 reflex controller spawned rules=12
ClawCam detections folded into world memory count=25
reflex: escalated to System 2 reason="person detected (verified) on a camera"
```

That last line is the point. A camera saw a person, a reflex rule fired without
waking the language model, and only then did it escalate to the model with a
triage playbook. That's the System 1 / System 2 split working.

## What's in the body

| File | Purpose |
|---|---|
| `config.toml` | The whole deployment: brain, perception, reflexes, escalation, gateway |
| `clawcam_gateway.db` | Seeded detections — 14 days, ~25 detections, one anomaly spike |
| `README.md` | This file |

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
- **`mesh_supervisor` is off by default.** With no LoRa board attached, every
  node reads as "presumed lost" and escalates on a loop — a critical alert for
  the fact that nothing is plugged in. Turn it on when you have a mesh.
- **Vision costs a model swap.** Image analysis loads a vision model; on a 12GB
  card that evicts the main model. Expect a pause on the way in and out.

## Going live

1. Replace `clawcam_gateway.db` with your gateway's real database.
2. Set `capture_node` to a real node id.
3. Set `require_state = "unreviewed"` if you want alerts before human review.
4. Enable `mesh_supervisor` once nodes exist.
5. Set `webhook_url` under `[notifications]` to reach a real destination.
