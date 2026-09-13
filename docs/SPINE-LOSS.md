# A lost spine

> **Written 2026-09-13; built the same evening** (upstream `7288c64`,
> vendored here). The brain lost its base station's serial port eleven
> minutes after opening it, ran headless for fourteen more, and the only
> place that said so was one `WARN` line in a seven-megabyte log. This is
> the design for what happens instead. Decision recorded in
> [DECISIONS.md](DECISIONS.md) (2026-09-13, *A lost spine is recorded, not
> survived silently, and never fatal*). §2.1–2.3 are `crates/obc-spine`
> (`lora_gateway::{GatewayLink, GatewayHandle, supervise_gateway}`,
> `mesh_supervisor::{MeshHealth::Unobservable, SpineView}`), in this
> repository; the wiring (§3, `src/main.rs`) is upstream. §4's tests exist
> and pass. §5 was run the same evening against the live brain (upstream
> `e344853`, walkthrough §A5n, `results/bench_spine_loss-20260913-170626.json`):
> **PASS 7/7** — the pull reproduced `os error 22`, `lost` in the same
> second, the node `unobservable` 2.4 s later, reopens at 1/2/4/8/16 then
> 30 s, no escalation for either node in 272 s, reopened on the first
> attempt after the replug, frames verified after the base's own
> power-cycle. Not run separately: the station DTR reset across a reopen.
> What §1 could not establish — the cause of the 18:56Z loss — is still
> open; the fact history will show its cadence if it recurs.

## 1. What was measured

The brain (release built 11:27, config with `[lora_gateway] port = "COM3"`,
`[descending] enabled`) opened the base station at 18:46:34 and verified
frames under the spine root without incident. Then, in order, from
`LLM___Oh_Ben_Claw.log`:

```
18:56:33.901  WARN  [lora_gateway] serial read error: The device does not
                    recognize the command. (os error 22)
18:56:33.901  WARN  LoRa gateway RX loop ended (serial link closed)
18:58:51.133  WARN  mesh supervisor: node presumed lost — offline for 120001 ms
                    node=gw-40
18:58:51.133  WARN  mesh supervisor: node presumed lost — offline for 120001 ms
                    node=obc-esp32-s3-001
19:09:13.330  WARN  descending posture NOT sent; will retry next turn
                    posture="default" error=serial I/O thread has exited
19:10:22      (operator restarted the task; port opened; posture confirmed
               on the third attempt)
```

Four things are true about those fourteen minutes, and the design has to
answer each:

1. **The port was gone and nothing tried to get it back.** The I/O thread in
   `open_split` returns on any read error that is not a timeout
   (`lora_gateway.rs`, the `Err(e) => { warn; return }` arm). The
   `run_gateway_rx` loop then ends because its channel closed, and `main.rs`
   logs one line. The `SerialCommandSink` keeps its dead channel handle and
   every later send fails with "serial I/O thread has exited".
2. **World memory said the nodes were lost. They were not.** The mesh
   supervisor derives `mesh.<node>.health` from the age of the last
   `mesh.<node>` fact and nothing else (`mesh_supervisor::decide`). With the
   host deaf, both nodes aged past `stale_ms` and then past
   `escalate_after_ms`, and two `Escalate` decisions fired for hardware that
   was beaconing normally the whole time. That is a false fact in the store
   the whole brain reasons from, and it is exactly the shape
   [DECISIONS.md](DECISIONS.md) 2026-09-12 refuses: *a check that could not
   run must not fail like a check that did.*
3. **The posture policy did the right thing and it was not enough.** It
   recorded `sent: false` with the error on the `descending.<node>` fact and
   retried next turn (`obc-agent/src/posture.rs`, as designed). But a turn is
   the only thing that retries, and the fact says a send failed, not that the
   spine is down. A reader has to infer the second from the first.
4. **Restarting fixed it, which means the fix is cheap.** The same
   `open_split` call, the same DTR/RTS-low sequence, the same auth window
   resumed from the persisted `spine.auth.gw-XX` ceiling
   ([SPINE-REPLAY.md](SPINE-REPLAY.md) §3, M = 1 on the host) — nothing about
   the reopen needs to be new. The auth window's resume-with-bitmap-full
   rule means a reopen admits no replay of what was accepted before the
   loss.

**What caused the loss is not established.** `os error 22` is
`ERROR_BAD_COMMAND`; on a Windows serial read it is what a surprise-removed
USB device produces. The likeliest story is the CP2102 on the base station
re-enumerating — a cable, a hub, or the base rebooting — but nothing
observed it, and the operator does not recall touching the bench at 18:56.
The design below does not depend on the cause; it depends only on the port
being able to come back, which the restart proved.

## 2. The decision

The brain keeps running. A lost spine is a change in the world, recorded
the way every other change is, and reopened until it returns. Three parts,
and the order is the order of value.

### 2.1 The spine has a fact

`spine.gateway`, source `lora-gateway`, origin `observed`, written on every
transition and on every reopen attempt:

```json
{ "state": "open" | "lost" | "reopening",
  "port": "COM3",
  "since_ms": 1789325... ,        // when this state began
  "error": "The device does not recognize the command. (os error 22)",
  "attempts": 3,                  // reopen attempts in this outage; 0 when open
  "next_attempt_ms": 1789326... } // reopening only
```

One entity, not one per station: it describes the host's serial link, and
the stations' own liveness stays in `mesh.gw-XX` and `spine.auth.gw-XX`
where it already is. The value is that `status`, the mesh supervisor,
System 2's context window and a person reading world memory all get the
same answer to "can the brain hear the mesh right now", instead of three
different inferences from three different symptoms.

### 2.2 Unobservable is not offline

`MeshHealth` gains a fourth state, `Unobservable`. `decide` takes the
gateway state as an input alongside the node views; while it is anything
but `open`, every node's health is `Unobservable` with reason
`"gateway <state>: <error>"`, no `Escalate` is emitted, no recovery probe
is queued (there is nothing to write it to), and the continuous-offline
clock does **not** run. When the gateway returns, health goes back to being
derived from message age — but `last_seen_ms` is what it was before the
loss, so a node will read `Offline` for one tick and then `Online` on its
next beacon. That one tick is honest: the host has not heard it since
before the outage. It must not count toward escalation, so the offline
clock restarts at the reopen, not at the last beacon.

`Unobservable` is emitted on change like the others, so an outage costs one
health fact per node, not one per tick.

This is the part that fixes the false claim. The reopen in §2.3 makes
outages shorter; this makes them true.

### 2.3 Reopen with backoff, forever

`open_split` becomes the inner call of a supervisor loop that owns the port
for the life of the process:

- On I/O-thread exit for any reason other than the receiver being dropped,
  write `spine.gateway = lost`, then loop: wait, write `reopening` with the
  attempt count, call `open_split` again. Backoff 1 s, doubling, capped at
  30 s. No attempt limit — a body that is meant to run unattended does not
  give up on its own spine because a hub blinked at 3 a.m.
- Each successful open creates a new `(line_rx, cmd_tx)` pair. The
  `SerialCommandSink` therefore holds the writer behind an
  `ArcSwap`/`RwLock` that the supervisor replaces on reopen, so the sink
  the posture policy and `mesh_command` were handed at startup keeps
  working across outages. While `lost`/`reopening`, `send_command` fails
  fast with the gateway state in the error — the same words as the fact —
  rather than "serial I/O thread has exited".
- `run_gateway_rx` is respawned per open with the *same* `LoraAuth`: its
  per-station windows are already persisted and resumed by ceiling, so a
  reopen after a base reset re-accepts the base after the bounded silence
  [SPINE-REPLAY.md](SPINE-REPLAY.md) §3 describes. No new auth state.
- A reopen is logged at `INFO` with the outage duration and attempt count,
  and writes `open` with `attempts` carrying the final count so the outage
  is legible from the fact history alone.

### 2.4 What does not change

- **The posture policy.** It already retries on the next turn and records
  the failure on the node's fact. Two retry loops for one `descend` is how
  a node gets the same frame four times; the gateway does not retry
  anything it was asked to send while down. It drops the command, fails the
  send, and the caller decides.
- **The startup refusal.** `[descending]` enabled with no gateway at start
  is still a hard error. A misconfiguration at boot and a lost port at
  runtime are different things and get different answers.
- **`mesh_command`'s reply-awaited retry.** Unchanged; it reads replies from
  world memory and will simply see none.

## 3. Where it lands

All upstream, `Oh-Ben-Claw`:

| Change | Where |
|---|---|
| `spine.gateway` fact, state machine, backoff loop | `crates/obc-spine/src/lora_gateway.rs`, `serial` module — a `GatewaySupervisor` around `open_split` |
| Swappable writer in the sink | same file, `SerialCommandSink` |
| `MeshHealth::Unobservable`; `decide` takes gateway state | `crates/obc-spine/src/mesh_supervisor.rs` |
| Wire supervisor + pass gateway state to the mesh supervisor tick | `src/main.rs`, the Phase B block |
| `status` shows the spine line | wherever `status` renders `mesh.<node>` today |

Vendored here afterwards under the usual parity rules
(`scripts/sync_upstream.py`), since `obc-spine` is already in the manifest.

## 4. Tests that would pin it

Known answers, not pinned outputs:

- **Loss is recorded.** A mock port whose read returns `ErrorKind::Other`
  after N lines: `spine.gateway` history reads `open → lost → reopening
  (attempts 1) → … → open`, and the `attempts` on the final `open` equals
  the number of failed opens plus one.
- **Backoff is bounded and monotone.** The waits between attempts are
  `1, 2, 4, …, 30, 30, 30` seconds; a test drives the clock.
- **The sink survives an outage.** A `send_command` before the loss
  succeeds, during it fails with the gateway state in the error, after the
  reopen succeeds on the *same* `Arc<dyn CommandSink>`.
- **Nodes are unobservable, not lost.** `decide` with gateway `lost` and a
  node view aged past `escalate_after_ms` yields one `Health { unobservable }`
  and **no** `Escalate`; the same view with gateway `open` yields the
  escalation it does today. Proves the supervisor's existing behaviour is
  untouched when the spine is up.
- **The offline clock restarts at reopen.** A node unheard since before a
  five-minute outage is `Offline` after the reopen with `offline_for` ≈ 0,
  not ≈ 300 000.
- **Auth resumes.** Reopen after a simulated base reset: the first frame
  under the old ceiling is rejected, frames above it are accepted — the
  SPINE-REPLAY reboot-gap property, now exercised across a reopen rather
  than a process restart.

## 5. Bench procedure

With the brain running and `[descending]` enabled:

1. Pull the base station's USB cable. Within one read timeout (250 ms) the
   log says `lost` and `spine.gateway` reads `lost` with the error.
2. Wait two minutes. `mesh.obc-esp32-s3-001.health` reads `unobservable`,
   **no** `mesh.<node>.escalation` fact exists, and no Telegram escalation
   arrived. (Today: both nodes escalate at 120 s.)
3. Send the brain a novel objective. The `descending.<node>` fact reads
   `sent: false` with `error: "gateway lost: …"`.
4. Plug the cable back in. Within 30 s the log says the port reopened with
   the outage length; `spine.gateway` reads `open`; the next beacon flips
   the node to `online`; the next turn's posture send goes through and is
   confirmed.
5. Repeat step 1 with a DTR-reset of the base instead of a pull
   (`scripts/probe_reset_station.py`), to exercise the auth resume path
   across a reopen.

Record the run under `results/` as the other bench scripts do.

## 6. Open

- **Root cause of the 18:56:33 loss.** Unknown. If it recurs with this
  design in place, the fact history will show the cadence; if it is the base
  rebooting, the base's `spine.auth.gw-XX` ceiling will have jumped at the
  same moment, which is the tell.
- **Host → node heartbeat.** Separate question, surfaced the same evening:
  the node declares the host lost 30 s after its last *command* (upstream
  `7c6a92c`, deliberately), and the brain sends none unprompted. A node in
  offline safing while the host hears it fine is the mirror image of §1,
  item 2.
  Not this document; belongs with the WILD port.
- **Rules do not survive a node reboot.** Also surfaced the same evening:
  host-pushed reflex rules and limits are RAM-only on the node and the push
  path is USB. The host hears the boot beacon and does nothing with it.
  Same family, same owner as the heartbeat question.
