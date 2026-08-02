# Authenticating the spine

A design, not a decision. Written 2026-07-30 against the code as it stands, to
answer the gap [`SAFETY.md`](SAFETY.md) §4.3 names: *"`p2p` and MQTT have no
authentication story… treat the spine network as trusted, and make sure that is
actually true."*

That sentence is accurate and it is the weakest claim in this project, because
Open Body Control already publishes the firmware for that spine. The
unauthenticated transport is the part a stranger reaches first.

---

## 1. What exists today, measured

| transport | authentication | integrity | confidentiality |
|---|---|---|---|
| MQTT (`src/spine/mod.rs`) | broker username/password, optional | none | **none** — `spine.tls = true` is a hard error because MQTT-over-TLS is not implemented |
| P2P (`src/spine/p2p.rs`) | none | none | none |
| LoRa (`firmware/heltec-lora-linktest/src/spine.rs`) | none | none | none |
| Serial | physical possession | n/a | n/a |

The MQTT row deserves emphasis: `validate()` refuses to start when `tls = true`,
deliberately, because the alternative was telling operators the link was
encrypted while it was cleartext. So every MQTT deployment is cleartext by
construction and knows it.

**The LoRa wire format** is the binding constraint on everything below:

```
[src:u8][seq:u8][ttl:u8][payload ≤ 240 bytes]
```

- `src` is the low byte of the originating MAC. One byte. Spoofable by
  construction and colliding across 256 nodes.
- `seq` is a per-source counter that wraps at 256. It exists to de-duplicate
  flood relays, not to prevent replay, and it cannot do the second job.
- `ttl` drives flood relay. An injected frame propagates across the mesh.

**The node has nothing to build on.** `firmware/obc-esp32-s3/Cargo.toml` pulls in
no SHA, HMAC or mbedtls crate, and the firmware makes no use of NVS. Both the
primitive and the persistent storage a replay counter needs are new work. The
one piece of good news: ESP32-S3 has hardware SHA acceleration, so the cost is
silicon rather than cycles.

> **Half of that is fixed, 2026-08-01.** The bridge firmware
> (`firmware/heltec-lora-linktest`) now carries `hmac`/`sha2`/`hkdf` and
> `src/auth.rs`, so the primitive exists on the node side and is checked against
> the host's. NVS is still untouched — the replay counter in step 3 remains
> entirely new work, and it is the half that cannot be tested without a board,
> since "a counter that survives reboot" is a claim about flash.
>
> `firmware/obc-esp32-s3` is also still untouched: the sentence above was written
> about the compute node and the work so far has been on the bridge. Two
> firmwares, and only one of them can currently compute a tag.

**The host half already exists and is unwired.** `NodePairingManager` implements
HMAC-SHA256 tokens with a five-minute replay window and quarantine status.
`pair_node` has no callers, `is_trusted` has none, and `require_pairing = true`
is validated and enforces nothing (see `ROADMAP.md`, Phase 3). Roughly half the
host-side work is written; none of it runs, and it has no counterpart on a node.

> **Wired 2026-08-01** (§6 step 5). `pair_node` has callers on both transports,
> `require_pairing` refuses, and per-message tags cover inbound results and
> outbound calls. The counterpart on a node now exists too, for the bridge
> firmware — `auth.rs`, cross-verified against the host's copy.
>
> What is still true in this section: the **LoRa frame itself carries no tag**,
> and the compute-node firmware cannot compute one. This paragraph described a
> host-side gap that is closed; the transport-side gap in the table above is
> not.

---

## 2. What authentication is for here

Worth stating precisely, because it is easy to overclaim and this project has
been overclaiming.

**It prevents:** an attacker on the network commanding an actuator; an attacker
injecting telemetry that poisons the world model and fires reflexes; an attacker
impersonating a node to receive tool calls intended for it; replay of a captured
`gpio_write`.

**It does not prevent:** anything a compromised host does — the host holds the
keys. Track 0's limit table on the microcontroller remains the only boundary
that survives host compromise, and nothing here replaces it. Authentication and
Track 0 answer different questions: *who may ask*, and *what may be done*.

**The asymmetry that shapes the design.** Host→node tool calls actuate; that is
the safety-critical direction. Node→host telemetry does not actuate directly,
but it lands in world memory, and reflexes act on world memory without waking
the model. A forged `battery.soc = 3` fires a safing rule. Both directions need
authentication; only one of them is obvious.

---

## 3. The design

### 3.1 Keys

A root secret per deployment, held by the host. Each node's key is derived:

```
node_key = HKDF-SHA256(root_secret, salt = "obc-spine-v1", info = node_id)
```

The host derives on demand and stores one secret. Each node is flashed with only
its own key and cannot impersonate a sibling. Revoking one node means
re-deriving with a new root and reflashing, which is the honest cost of
pre-shared keys and the reason §5 lists an asymmetric option.

Provisioning rides on the existing path: the deployment generator already emits
per-node firmware config (`SAFETY_OUTPUT_PINS` is rendered into `config.rs`
today), so `NODE_KEY` joins it. That keeps the key out of the repository and in
the artifact the operator flashes.

### 3.2 The tag

Append a truncated HMAC-SHA256 to every frame:

```
[src:u8][seq:u8][ttl:u8][ctr:u32][payload ≤ 224][mac:8]
```

- **`mac` is 8 bytes, not 32.** On a 240-byte budget a full tag is 13% of every
  frame; eight bytes is 3.3%. Truncated to 64 bits, an online forgery attempt
  succeeds with probability 2⁻⁶⁴ per try, against a radio link that manages a
  few frames per second. That is the right trade here, and it is a trade — say
  so in the docs rather than implying 256-bit security.
- **`ctr` is a 32-bit monotonic counter**, not the existing `seq`. It must
  survive reboot, so it lives in NVS, written every N (say 64) and advanced by N
  on boot to bound flash wear while never going backwards. The receiver rejects
  any counter at or below the highest seen for that source.
  *(Superseded 2026-08-01 — that last sentence is wrong for a flood-relay mesh,
  which delivers duplicates and re-orderings as normal traffic. It needs a
  sliding window; see [`SPINE-REPLAY.md`](SPINE-REPLAY.md) §3.)*
- The MAC covers `src ‖ ctr ‖ payload`, and deliberately **not** `ttl`, which
  relays decrement in flight.

Cost: 12 bytes of the 240-byte budget, payload down to 224. Worth measuring
against real traffic before committing — if the common tool call is near the
limit today, this design forces fragmentation, and that is a different project.

> **Measured 2026-08-01** — `tests/spine_payload_budget.rs` in the core repo. Not
> a radio capture: the host builds every one of these payloads, so the
> distribution is a property of the code, and the census runs as a standing test
> rather than sitting here as a number that quietly stops being true.
>
> | | bytes | spare of 240 | spare of 228 |
> |---|---:|---:|---:|
> | `gpio_write` / `sensor_read` / `capabilities` | 100–121 | 119–140 | 107–128 |
> | `reflex_tick`, four quantities | 183 | 57 | 45 |
> | fleet heartbeat / assignment | 59–82 | 158–181 | 146–169 |
> | `set_limits`, one allowed pin | 228 | 12 | **0** |
> | `set_limits`, two allowed pins | 230 | 10 | **−2** |
> | `set_reflex_rules`, one rule | 344 | **−104** | −116 |
>
> **The tag fits.** Everything that carries actuation, telemetry or coordination
> keeps 45–169 bytes of headroom, so §3.2 stands as written and steps 2–4 are
> not invalidated.
>
> **The tag is not free**, and the thing it costs is not a tool call. Pushing a
> deterministic limit table — `set_limits`, the Track 0 configuration — lands on
> exactly 228 bytes with one allowed pin and 230 with two. The command that
> configures the safety gate is the command the safety tag would break.
>
> **The margin already exists in the frame.** `mesh_command` spends **36 bytes on
> a UUIDv4 correlation id**, three times the whole tag, on a link where the id
> need only be unique among a handful of in-flight requests. Shortening it frees
> 34; the tag needs 12. So step 4 should carry the correlation-id change with it,
> and then authentication costs less than nothing.
>
> **`set_reflex_rules` was already broken**, at 344 bytes — 104 over the frame we
> have, before any authentication. The node's line framer discards an over-length
> line whole, so it never arrived, and the host reported `sent: true`. Now
> refused host-side (`NodeCommand::fits_one_frame`). That one is not an auth
> question: pushing a rule set over LoRa needs fragmentation or a different
> transport either way.

### 3.3 MQTT and P2P

The same tag, carried as a field rather than a prefix, since neither transport
has a byte budget worth defending:

```json
{ "call_id": "...", "tool_name": "...", "args": {...},
  "ctr": 1837, "mac": "b3f1…" }
```

MQTT keeps broker credentials as a coarse first gate; the per-message MAC is
what actually matters, and it is what makes cleartext MQTT tolerable rather than
alarming. Confidentiality is a separate question and out of scope here — a MAC
stops forgery, not eavesdropping.

### 3.4 Wiring the host half

`NodePairingManager` gets its callers, finally:

- Verify the MAC and counter on every inbound frame, before the payload reaches
  the world model or the tool dispatcher.
- Refuse announcements from unpaired nodes when `require_pairing = true` — the
  behaviour that key already promises and does not deliver.
- Sign outbound tool calls.
- `security/trust.rs` becomes true. Its header says *"OBC already authenticates
  nodes (HMAC pairing) … that trust is static"* and builds behavioural hardening
  on that premise. Today the premise is false. This makes it accurate rather
  than aspirational.

---

## 4. What it costs

**A wire-format change is a cross-repository event.** The firmware is vendored
into Open Body Control — 32 hash-checked artifacts — so this lands as: change
upstream, rebuild, `sync_upstream.py sync --upstream … --peer …`, and a manifest
update in the same commit. `tests/firmware_spine_framing.rs` compiles the node's
`spine.rs` host-side and will need cases for tag verification, which is exactly
where they belong.

**Backward compatibility.** Old and new frames are distinguishable by length
alone, which invites a permissive mode that accepts both. Resist it, or scope it
hard: an authentication layer with a fallback to no authentication is an
authentication layer an attacker turns off. If a migration window is needed, make
it a config key that logs loudly, defaults off, and has an expiry — the pattern
`DECISIONS.md` already used for the planner tool-set mask.

**Nodes need reflashing.** There is no over-the-air path for a key that isn't
itself authenticated, and bootstrapping trust over an untrusted channel is the
one problem this design cannot solve on its own.

---

## 5. Decisions this does not make

1. **Symmetric or asymmetric.** Pre-shared HMAC is small, fast, and has no
   revocation story short of reflashing. Ed25519 signatures are 64 bytes — 27% of
   a LoRa frame, likely disqualifying there but fine on MQTT — and would let a
   node be revoked without touching its siblings. A split (Ed25519 on MQTT, HMAC
   on LoRa) is defensible and is two protocols to maintain.
2. **Tag length.** 8 bytes is proposed. 16 costs another 3% of the budget and
   buys margin nobody can currently justify with a measurement.
3. **Whether telemetry is authenticated from day one**, or only the actuating
   direction. Doing the dangerous half first ships sooner; doing half of an
   authentication scheme is also how you get a scheme people believe is complete.
4. **Where this meets MCP.** `RESEARCH-2026-07.md` §3.2 argues the more valuable
   contribution is a *physical-actuation authority profile* over MCP —
   reversibility class, blast radius, velocity bound, geofence, lease and
   preemption — and that transport authentication is the floor beneath it, not a
   substitute. That argument is good and the two should be designed together, but
   the floor comes first: an authority model over an unauthenticated transport is
   a lock on an open door.

---

## 6. Suggested order

1. ~~**Measure the payload distribution** on the bench mesh. If typical frames sit
   near 240 bytes, everything above needs rethinking before it is built.~~
   **Done 2026-08-01** — see the box in §3.2. Steps 2–4 stand; the tag fits
   everything that carries actuation, telemetry or coordination. Two additions
   to the plan came out of it: **step 4 must also shorten the correlation id**
   (36 bytes of UUID, against a 12-byte tag — otherwise `set_limits` becomes
   collateral), and `set_reflex_rules` needs fragmentation or another transport
   regardless of authentication, since it never fitted.

   It was measured from the code rather than from the air, which was not the
   plan and is better than the plan: the host builds every payload, so the
   census is a test that fails when a shape changes rather than a figure in a
   document that does not.
2. ~~**Node-side HMAC-SHA256 with hardware SHA**, verified against a host-side test
   vector in `firmware_spine_framing.rs`. No wire change yet.~~ **Done
   2026-08-01.** `crates/obc-safety/src/spine_tag.rs` is canonical and vendored
   here; `firmware/heltec-lora-linktest/src/auth.rs` is the node's mirror, also
   vendored here; the core repo's `tests/spine_auth_vectors.rs` compiles both and
   fails if they disagree. `cargo test -p obc-safety` runs the host half in this
   repository, so the document above and the arithmetic it specifies are finally
   in the same place.

   Two deviations from the line as written, both deliberate:

   - **Portable `sha2`, not the ESP32-S3's hardware SHA.** The silicon is the
     right destination and an optimisation; a portable implementation compiles
     on the machine writing it, so this could be tested immediately rather than
     at the next bench session. Swapping in mbedtls later has a known answer to
     check against, which is a better position than the reverse.
   - **A separate `auth.rs`, not `spine.rs`.** Step 2 says *no wire change yet*
     and `spine.rs` is the wire. Nothing calls `auth` — no frame carries a tag,
     no receiver checks one.

   The verification is three layers, and only the third is independent:
   agreement between the two implementations (which two copies of one mistake
   would also pass), frozen vectors (a regression pin generated from this
   implementation, so an error would be frozen with it), and **RFC 4231 §4.2 +
   RFC 5869 §A.1** — constants published years ago, which is what makes the
   first two mean anything.
3. **NVS counter**, with the wear-bounded advance-on-boot scheme, and a test that
   a reboot never reissues a counter. **Designed 2026-08-01, deliberately
   unbuilt: [`SPINE-REPLAY.md`](SPINE-REPLAY.md).** It is the first step here
   whose central claim — a counter that never goes backwards across a power cut
   — is a statement about flash, so it cannot be checked without a board.
   Writing it and marking it done on a compile is the kind of claim this project
   keeps catching itself making.

   Two things the design changed about the sketch in §3.2 above:

   - **"Reject any counter at or below the highest seen" is wrong for this
     mesh.** Flood relay delivers duplicates by design — `spine.rs` carries a
     de-duplication ring because of it — and re-orders frames across paths.
     Strict monotonicity drops all of that as an attack. It needs an IPsec-style
     sliding window (RFC 4303 §3.4.3), which is pure logic and *is* testable on
     the host today, unlike the rest of step 3.
   - **The receiver's persistence rounds the opposite way from the sender's.**
     The sender persists a ceiling above its position, so a crash skips
     counters. A receiver that persists below its true high-water mark accepts
     replays of everything in between, so it must persist a ceiling too and lose
     a bounded number of legitimate frames after a restart instead. Getting that
     direction backwards is the classic form of this bug.

   `SPINE-REPLAY.md` §6 is a bench procedure, so the person with the boards does
   not have to re-derive what "it works" means.
4. **Wire format v2** behind a config key that defaults to strict, with the old
   format rejected rather than tolerated.
5. ~~**Wire the host half** — `NodePairingManager` gets its callers, and
   `require_pairing` starts meaning something.~~ **Done 2026-08-01, for MQTT and
   P2P.** All three bullets of §3.4 except the LoRa frame, which is step 4:

   - **`require_pairing` refuses unpaired announcements.** It had been validated
     at boot and gated nothing — any node that could publish on the topic got
     its tools registered. Gated now on both transports, and on P2P especially,
     where discovery is a UDP broadcast with no broker and no handshake.
   - **Inbound tool results are verified.** The non-obvious direction: a result
     does not actuate, it lands in world memory, and reflexes act on world
     memory without waking the model.
   - **Outbound tool calls are signed**, and on P2P *verified*, because both
     ends of a P2P call are the agent rather than firmware. That half is a round
     trip today rather than a promise about step 4.

   Two things the work established that this document did not say:

   - **The sender's counter has a host-side answer that is not NVS: the clock.**
     Seeding each counter at the current Unix second means a restart cannot go
     backwards unless the clock does, which is exactly the guarantee flash is
     needed for on a node that has no clock at boot. See
     [`SPINE-REPLAY.md`](SPINE-REPLAY.md) §2 for what the node still needs.
   - **`ToolCallRequest` carried no sender identity at all.** The frame said
     what to do and never said who was asking, so a P2P receiver could not have
     verified anything even in principle. `from` now selects the key; the tag is
     what makes the claim mean something.

   `[security] require_frame_auth`, default off, deriving per-node keys from the
   existing `pairing_secret`. Off by default because the moment it is on, a node
   that has not been upgraded goes silent — the migration window §4 asks for.
6. **Re-sync firmware into OBC-Prime** and update `SAFETY.md` §4.3 from "no
   authentication story" to what it then is, including what it still is not.

Step 1 was a morning and did not invalidate steps 2–4. It was still the right
thing to do first: it changed step 4, and it found a command that had never
worked.
