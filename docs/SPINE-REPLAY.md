# The replay counter

A design, not a decision, and deliberately **unbuilt**. Step 3 of
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
4. **What a rejection does beyond dropping the frame.** Silently discarding is
   correct for the wire. Whether it also raises a fact, escalates, or feeds
   `security/trust.rs` — which scores node behaviour and is already wired — is
   open, and 3 and 4 should probably be answered together.

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

Steps 1–5 need one node. Step 6 needs three.
