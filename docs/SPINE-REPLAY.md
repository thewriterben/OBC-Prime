# The replay counter

> **Built in half, 2026-09-13.** §2's ceiling scheme is running on the Heltec
> stations' existing 8-bit `seq` — not yet on the u32 counter the tag will
> carry — because the bench found the exact failure this document predicts,
> one layer down: a base station reset (a serial port opened with DTR was
> enough) restarted its `seq` at 0, and the bridge's 32-entry de-dup ring
> dropped its next commands as duplicates. Four recorded runs "sent" frames
> that never left the ring. `SeqCounter` in upstream's
> `firmware/heltec-lora-linktest/src/spine.rs` persists the ceiling in NVS
> (`spine/seq_ceil`), reserve 32 tied to the ring size by a test, fail-closed
> when NVS is unusable; six host tests pin §2's properties including a
> reboot never landing in a neighbour's ring across the 256 wrap. §6 steps
> 1–3 were run on the bench with DTR resets (unclean): 7 boots, counts
> strictly increasing, every gap 31 ≤ 32.
>
> **Finished the same evening, with SPINE-AUTH step 4.** The u32 counter
> rides on that `SeqCounter` unchanged (`seq` is its low byte), and §3 is
> built as written: `ReplayWindow` — 64-bit bitmap, per source, persisted as
> a ceiling `h + M` with **M = 8** — replaced the de-dup ring, which is
> deleted. **N stays 32.** Measured on a bridge reset
> (`scripts/bench_spine_auth.py reboot-gap`): the bridge's counter resumed 25
> above the last the base had accepted, the base accepted its first frames,
> and the bridge re-accepted the base after **3 skipped frames** — the
> bounded silence §3 promises, in the safe direction. One correction to §3
> found by the host tests: a window that resumes at its ceiling must resume
> with its bitmap *full*, not empty; empty accepts the replay of everything
> in the 64 below the ceiling, which is the hole the ceiling exists to
> close. §5.3–4 (what a rejection does beyond a console line) remain open.
>
> **Steps 4–5 run 2026-09-13 evening** (upstream `b3243fa`, walkthrough
> §A5o, `scripts/bench_seq_wear.py`, on the bridge). Step 4: 40 host-driven
> resets at 2–4 s — the counter resumed **exactly N = 32 higher on every
> boot**, one ceiling write per boot, never a repeat. Flash consumption was
> *not* measured: `nvs_get_stats().free_entries` (now on the boot line)
> stayed at 624 through 40 writes, so it does not see a rewrite of an
> existing key; wear stays inferred (one entry write per boot). Step 5,
> with the store poisoned at the `CeilingStore` boundary (a bench feature,
> not a corrupted partition): the station sent the 20 numbers it was
> already authorised, refused the next extension, went silent; the host
> read it offline at 94.6 s and presumed it lost 120 s later; a reset
> resumed at the last ceiling persisted before the fault. Step 6 still
> needs a third radio. The rest of this document is unchanged.

A design, not a decision, and deliberately **unbuilt** for the authenticated
counter it describes. Step 3 of
[`SPINE-AUTH.md`](SPINE-AUTH.md) — the counter that makes the tag from step 2
mean something over time — is the first item in that plan whose central claim
cannot be checked without a board. "The counter never goes backwards across a
reboot" is a statement about flash. Writing the code and marking it done on a
compile would be the kind of claim this project keeps catching itself making.

So: the algorithm is specified here in enough detail to implement from, the parts
that *are* testable off-hardware are marked, and §6 is a bench procedure for
whoever has the boards.

---

## 1. What the counter is for

The tag proves a frame came from a holder of the node key. It says nothing about
*when*. Without a counter, an attacker who records one authenticated
`gpio_write` can replay it forever, and every replay verifies perfectly — the
MAC is valid because the frame is genuine. It is just old.

`SPINE-AUTH.md` §3.2 puts a 32-bit counter inside the MAC, which is the right
shape and is only half the mechanism. The other half is that both ends have to
*remember* something, and remembering across a power cycle is where this gets
interesting.

The existing `seq` byte cannot do this job and is not being asked to: it wraps at
256 and exists to de-duplicate flood relays.

---

## 2. Sender: never reissue a counter

The rule is absolute. Two frames with the same `(node, ctr)` and different
contents are a forgery oracle; the same `(node, ctr)` twice at all destroys the
receiver's ability to tell a replay from a retransmission.

A counter held only in RAM repeats on every reboot. A counter written to flash on
every frame is correct and wears the flash out. The standard resolution is to
persist a **ceiling** rather than a position:

```
on boot:
    hwm = nvs_read(ctr_hwm)          # highest counter ever authorised
    ctr = hwm                        # start here
    nvs_write(ctr_hwm, hwm + N)      # authorise the next N, BEFORE using any
    ceiling = hwm + N

on send:
    if ctr + 1 >= ceiling:
        nvs_write(ctr_hwm, ceiling + N)   # extend before crossing
        ceiling += N
    ctr += 1
    transmit(ctr, tag(key, src, ctr, payload))
```

Two properties, and the second is the one that is easy to get backwards:

- **A crash costs at most N counters, and never repeats one.** Whatever was
  authorised is skipped, not reused. Gaps are fine; the receiver tolerates them
  by construction (§3).
- **The write happens *before* the counters are used, not after.** Persist-then-use
  loses counters on a crash. Use-then-persist *repeats* them. The failure modes
  are not symmetric and only one of them is survivable.

### Fail closed

If the NVS write fails — partition full, corrupt, worn out — the node must stop
transmitting authenticated frames. Continuing on an unbacked counter is exactly
the state the mechanism exists to prevent, and a node that goes quiet is a
condition the mesh supervisor already detects and escalates (`mesh.<node>.health`
→ offline → `safe-mesh-node-lost`). The failure has a home; it should be allowed
to reach it rather than being papered over.

### Exhaustion is not wraparound

At `u32::MAX` the node must refuse to transmit and require re-provisioning with a
fresh key. Wrapping to zero silently reopens the entire replay window at once —
the one moment where every captured frame in the node's history becomes valid
again.

The number this will never reach: at one frame per second, 2³² counters is about
136 years. It matters anyway, because "unreachable" arguments are how counters
wrap.

### The wear budget, honestly

One NVS write per N frames, plus one per boot. With N = 64 and a node sending a
frame a second, that is roughly one write a minute.

The number that actually constrains this is the flash endurance and the NVS
partition size, and I am not going to assert either from memory — ESP-IDF NVS
wear-levels across its partition, and the per-sector program/erase endurance is a
datasheet figure for the specific part. **Check it before choosing N.** The shape
of the answer: larger N means fewer writes and more counters lost per crash,
which costs nothing operationally, so N should be as large as the receiver
window's tolerance allows (§3) rather than as small as feels tidy.

One case is worth sizing deliberately: a node in a **crash loop** writes once per
boot, and a boot loop is seconds, not minutes. That is the fastest this design
can consume flash, it is a failure mode rather than normal operation, and it is
the one to bound in the bench procedure.

---

## 3. Receiver: a window, not a high-water mark

`SPINE-AUTH.md` §3.2 says *"the receiver rejects any counter at or below the
highest seen for that source."* Strictly implemented, that is wrong for this
mesh, and the evidence is already in the firmware: `spine.rs` carries a
de-duplication ring because **flood relay delivers the same frame more than
once, by design**. Duplicates are normal traffic here. So is re-ordering — a
frame that takes a two-hop path arrives after one that went direct.

Strict monotonicity drops every one of those as an attack. The mesh would appear
to be under constant assault by itself.

The standard answer is IPsec's anti-replay window (RFC 4303 §3.4.3), and it fits
here unchanged:

```
state per source: H (highest accepted counter), W (64-bit bitmap of the 64 below H)

accept(ctr):
    if ctr > H:              shift W left by (ctr - H), set bit 0, H = ctr  → accept
    if ctr <= H - 64:        → reject (too old to judge)
    if bit (H - ctr) set:    → reject (already seen)
    otherwise:               set bit (H - ctr)                              → accept
```

A 64-frame window absorbs relay duplicates and ordinary re-ordering while still
refusing anything older than the window, and refusing anything twice.

**This part is pure logic and is testable on the host today** — no flash, no
radio. It belongs in `obc-safety` with a mirror in the firmware, verified by the
same cross-implementation arrangement `spine_tag.rs` and `auth.rs` already use.
If step 3 gets built in halves, this is the half that can land first.

### Receiver persistence: the direction reverses

The receiver must also survive a restart, and here the safe rounding goes the
*other* way. The sender persists a ceiling above where it is, so a crash skips
counters. If the receiver persists a value below its true `H`, a restart accepts
replays of everything in between — the exact hole this is closing.

So the receiver persists a **ceiling too**: `H + M`, refreshed every M accepted
frames. After a restart it resumes at that ceiling, which is at or above the true
high-water mark. The cost is that up to M legitimate frames are rejected while
the sender catches up — a bounded, silent gap, in the safe direction.

Choose M by how long a gap is tolerable, not by symmetry with N.

### The asymmetry that makes this cheap

The high-rate direction is node → host telemetry, and there the **receiver is the
host**, which has SQLite and no flash-wear problem: persist every frame, choose
M = 1, lose nothing.

The node is a receiver only for host → node commands, which are
operator-initiated and rare. Per-frame persistence is affordable there too.

So the wear analysis in §2 applies to exactly one thing — the node's *sending*
counter — and the receiver side, which looked like the expensive half, is not.

---

## 4. What this does not solve

- **A cloned node.** An attacker who extracts the key from a flashed device holds
  a legitimate node. The counter does not care.
- **Confidentiality.** Still none. A MAC stops forgery, not reading.
- **A compromised host.** The host holds the root secret. Track 0's limit table
  on the microcontroller remains the only boundary that survives that.
- **The first frame after provisioning.** A receiver that has never heard from a
  source has no `H`. It must accept the first authenticated frame it sees and
  start the window there — which is a one-frame replay opportunity for a
  capture made before the receiver's state existed. Bounded, and the honest
  alternative (a provisioning handshake) is a larger design.

---

## 5. Decisions this does not make

1. **N and M**, which need the endurance figure from the datasheet and a view on
   tolerable post-restart gaps.
2. **Whether the window ships before the NVS binding.** The window is testable
   now; the persistence is not. Shipping the window alone authenticates nothing
   extra — it is inert until the counter is real — so this is a sequencing
   question, not a safety one.
3. **Where the host keeps its per-source state.** World memory is the obvious
   home and would make replay rejections visible to reflexes and to `status`,
   which has some appeal: "this source is sending counters I have already seen"
   is exactly the kind of thing a person should be told about.
   *Decided 2026-09-14* (DECISIONS.md): world memory, `spine.auth.<station>`
   `{ctr, accepted, rejected, last_rejected}`, M = 1 — as built on 09-13.
4. **What a rejection does beyond dropping the frame.** Silently discarding is
   correct for the wire. Whether it also raises a fact, escalates, or feeds
   `security/trust.rs` — which scores node behaviour and is already wired — is
   open, and 3 and 4 should probably be answered together.
   *Decided 2026-09-14* (DECISIONS.md), on 4827 frames with zero rejections:
   `BadTag` and `Replayed` open `spine.auth.<station>.alarm` (one per burst,
   self-clearing after ten minutes) and `spine.auth.alarm_count`, which the
   standard safing rule `safe-spine-forgery` escalates to System 2; `TooOld`
   (the bounded post-reset gap) and `Unsigned` (old firmware) stay on the auth
   fact and alarm nothing; `trust.rs` is not fed — the station is not the
   actor, and a forger spoofs the victim's id.
5. **Whether the host is told about frames the *station* refused.** Opened and
   closed 2026-09-15, while building the bench for item 4 — which could not be
   run as conceived, because a station forwards nothing it refuses and the
   host's parser drops the `SPINE ◄ REJECTED` line. So item 4's alarm is
   reachable only by a station that disagrees with the host about the root,
   never by a stranger transmitting forgeries at an honest station: on-air
   forgery produced no fact, no escalation, and a clean `status`.
   *Decided 2026-09-15* (DECISIONS.md): the host reads the refusal line the
   station already prints and raises a separate, weaker signal —
   `spine.air.<station>.refused` and the rule `safe-spine-on-air`, at
   `Warning` where `safe-spine-forgery` is `Critical`, because the evidence is
   the station's word over an unauthenticated console rather than the host's
   own cryptography. Only `BadTag` counts: `Seen` cannot be told from a relay
   duplicate at the station, and the rest is RF or the station's own
   bookkeeping.

---

## 6. Bench procedure (for whoever has the boards)

The point of writing this down now is that the person at the bench should not
have to re-derive what "it works" means.

1. **Counters never repeat across a clean reboot.** Flash, transmit a known
   number of frames, note the last counter, power-cycle, transmit again. The
   first counter after the reboot must be strictly greater than the last one
   before it. Repeat ten times.
2. **Counters never repeat across an *unclean* reboot.** The same, but cut power
   mid-transmission rather than resetting cleanly. This is the case the ceiling
   scheme exists for and the only one that distinguishes it from write-behind.
3. **The gap is bounded by N.** Across each reboot, the jump should be at most N.
   A larger jump means the ceiling is being extended more often than the design
   says, which is a wear problem hiding as a correctness pass.
4. **A crash loop is survivable.** Force a boot loop for a measured interval and
   confirm the counter and the NVS write count advance as predicted. This is the
   fastest flash consumption the design allows; measure it rather than reasoning
   about it.
5. **NVS failure stops transmission.** Fill or corrupt the partition and confirm
   the node stops sending authenticated frames rather than continuing, and that
   the supervisor escalates it as an offline node.
6. **The window tolerates real relay traffic.** With three radios and flood
   relay active, confirm duplicates and re-ordered arrivals are accepted exactly
   once and that nothing legitimate is rejected. This is the assertion that
   would have failed under the strict high-water-mark reading of §3.2, and it
   needs the third radio that Phase B's 3-hop relay item is also waiting on.

7. **A wrong root is caught, and by which of the two signals.** Added
   2026-09-15 with §5 item 5; the alarm and the advisory have different
   reachability and the bench has to exercise both, because each is invisible
   to the other's threat.

   *7a — the forger on the air.* Flash **the board that is not plugged into
   the host** with `bench-low-power,bench-wrong-root` and leave the host's
   station honest. Expect: `SPINE ◄ REJECTED … bad tag` on the honest
   station's console; one `spine.air.<station>.refused` fact for the burst
   with a climbing `count`, **not** one per frame; `spine.air.refused_count`
   1; `safe-spine-on-air` waking System 2 at `Warning`;
   `spine.auth.<station>.alarm` **absent**, because the host refused nothing;
   and — the assertion that matters most — genuine traffic from the honest
   station still arriving throughout. Then stop transmitting and confirm the
   burst closes after ten minutes and the count returns to zero.

   *7b — the replaced station.* Flash **both** boards `bench-wrong-root`, so
   they agree with each other and disagree with the host. Expect the mirror
   image: the stations accept each other on the air and print no refusals,
   the host refuses every forwarded frame as `BadTag`, one
   `spine.auth.<station>.alarm` for the burst, `spine.auth.alarm_count` 1, and
   `safe-spine-forgery` at `Critical`. This is the path the four `BadTag` of
   2026-09-13 came down, before the alarm existed to be tested.

   Reflash both boards to the field feature set afterwards. A
   `bench-wrong-root` board carries no deployment secret, so it is safe in a
   drawer, but it is also completely deaf and mute on the real mesh.

Steps 1–5 and 7 need one node (7 needs both stations). Step 6 needs three.
