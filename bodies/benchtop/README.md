# Benchtop — reference body

One ESP32-S3 on a USB cable with an environmental sensor, and a small Linux host
to run the brain. The smallest deployment that still exercises the whole
brain-to-node path.

```
BME280 reading  ->  world memory  ->  reflex rule  ->  escalation  ->  the model
                                           |
                                  Track 0 limit refuses a command
```

## What has and has not been verified

Trailwatch ships 14 days of real recorded detections and can be run end to end
with nothing plugged in. **This body cannot**, and inventing a sensor history to
make it look like it could would be teaching you to trust numbers nobody
measured. So here is the honest split:

| | Status |
|---|---|
| `config.toml` parses, and the agent starts from it | **verified** — `OBC_CONFIG=config.toml oh-ben-claw doctor` reports 0 errors, 2 reflex rules loaded |
| The `[deployment]` block matches the Benchtop inventory in the generator | **verified** — emitted by the planner, not hand-written |
| Board and accessory names resolve in the registry, zero capability gaps | **verified** — `tests/reference-bodies.test.ts` in the generator |
| A BME280 on a real FireBeetle 2 produces `sensor.humidity` and fires the reflex | **not verified** — needs the hardware |
| This body's limit table refuses pin 14, an out-of-range value, and a too-fast repeat | **verified** — `cargo run -p obc-demo -- bench` parses *this* `config.toml` and runs the gate over it |
| The node enforces the same table the host does | **verified** — the same demo pushes the table to `firmware/obc-esp32-s3/src/safety.rs` as JSON and compares both gates' verdicts |
| A physical ESP32-S3 refuses the command and the wire does not move | **not verified** — needs the board; see [the bench procedure](#the-bench-procedure) |

Until 2026-08-21 those last three were one row reading *"the Track 0 limit
refuses an out-of-range `gpio_write` on this board — not verified here"*. That
was true and it was doing two jobs badly. Two of the three claims needed nobody
to plug anything in: they needed someone to read the file and run the gate over
it. Only the third needs a board, and saying so makes it a job someone can
actually finish.

If you build it and either of the unverified rows behaves differently, that is
worth an issue: it is the gap between a template that parses and a template that
works.

## The bench procedure

Everything above the last row is checked in CI. This is the part that is not,
written so that running it produces a result worth recording rather than an
impression.

**You need** a DFRobot FireBeetle 2 ESP32-S3 (or any ESP32-S3 the registry
knows) with `firmware/obc-esp32-s3` flashed, an LED or scope probe on **pin 12**
and on **pin 14**, and the host running this body.

1. **Confirm the node took the limits.** The host pushes the table on connect
   over the retained `obc/nodes/bench-001/limits` topic. Ask the node what
   policy it is holding — it should report pins `[12, 13]`, values `0..=1`,
   interval `500`. If it reports the boot default instead, the push did not
   land, and everything below would be testing the wrong policy.

2. **In policy.** Drive pin 12 high. The LED lights. This is the control: it
   proves the path works, so that a refusal later is a refusal and not a
   disconnected wire.

3. **The refusal.** Ask for pin 14. Expect a refusal from the host gate — and
   then the part that matters: **pin 14 must not move.** Watch the pin, not the
   log. A gate that refuses in the log while the pin twitches is the failure
   this whole row exists to rule out.

4. **The mirror, without the host.** Stop the agent. Send the node a
   `gpio_write` for pin 14 directly over serial. It must refuse on its own.
   This is the one claim in `docs/SAFETY-CASE.md` §4 called load-bearing —
   that the deterministic limit survives a compromised or absent host — and
   step 4 is the only place it is ever actually tested.

5. **Rate limit.** Two writes to pin 12 within 500 ms. The second must be
   refused, and the pin must hold its first value rather than flicker.

**Record what happened**, including the boring parts: firmware commit, board
revision, and whether step 1 reported the pushed policy or the boot default. A
row that says "verified" with no date and no commit is the kind of claim the
rest of this repository spent a week removing.

## What you need

- Any Linux host that runs the agent. The inventory names a **NanoPi Neo3**
  because that is what it was planned against; a Pi or any x86 box is fine, and
  only the `[[deployment.hardware]]` entry describes it.
- A **DFRobot FireBeetle 2 ESP32-S3** (or any ESP32-S3 the registry knows) with
  `firmware/obc-esp32-s3` flashed — see [the flashing guide](../../firmware/README.md).
- A **BME280** on I²C. Swap it for any I²C sensor in the accessory registry and
  the generated firmware follows.

## Run it

```bash
cd bodies/benchtop
export ANTHROPIC_API_KEY=sk-ant-...     # or OPENAI_API_KEY / OPENROUTER_API_KEY
export OBC_CONFIG=config.toml           # PowerShell: $env:OBC_CONFIG="config.toml"
oh-ben-claw start
```

There is **one line to edit first**: `path` under the serial board, which must
match what your board enumerates as — `/dev/ttyACM0` or `/dev/ttyUSB0` on Linux,
`COM3` or similar on Windows.

There is no `[provider]` block, on purpose. The agent uses whichever provider key
is in your environment, and falls back to a local Ollama if there is none.

Running two bodies on one machine? Give each its own data root, or they share one
database and one set of standing approval grants:

```bash
export OBC_DATA_DIR=~/obc/benchtop
```

## The parts worth stealing

**A reflex on a threshold you can cross by hand.** `humidity-spike` fires when
`sensor.humidity` goes above 75. Breathe on the sensor and the whole System 1
path is observable in one action — no model wake, no network, no waiting.

**`fire_on_change`, and where it must not go.** The humidity rule sets it: a
spike is an *event*, and re-firing on the same reading tells you nothing new. The
thermal rule deliberately does not: a node that is *still* too hot is worth
saying again. Debounce alone cannot express that difference — it only asks
whether enough time has passed, and for a standing condition the answer is
eventually always yes.

**A Track 0 limit narrow enough to test.** `bench-001` may drive pins 12 and 13,
values 0–1, no faster than twice a second. Ask the agent to write pin 14 and the
gate refuses in code, before anything reaches the wire — and the node holds its
own copy, so a compromised host cannot talk it round.

**Retention on notes only.** Sensor readings are never expired: they are
*superseded* by the next reading, which is a different mechanism with different
provenance. The agent's own notes have nothing to supersede them and nothing to
orphan them, so without `[[perception.expiry]]` they would be believed forever.

## Adapting it

Change the accessory and the desire together. `EnvironmentalSensing` with a
BME280 is what makes the planner report zero gaps; a bare `esp32-s3` with no
accessory carries `camera_capture` and `audio_sample`, so the planner claims it
as a vision node and then reports "no `sensor_read` hardware found" about the
board that is holding the sensor. Trust the gap-warning test over your intuition
about what a board can do — that failure is in the bodies README because it
happened while writing this one.
