# Decisions

Short records of choices that are expensive to reverse, and why they were made.
New entries go at the top.

---

## 2026-09-16 — A node's name has to come from the chip, because the second board answered to the first one's

The firmware carried `const NODE_ID: &str = "obc-esp32-s3-001"`, with a doc
comment saying it "should be read from NVS in production". The comment had been
right and ignored for months, which is the normal fate of a comment that names a
problem instead of failing on it.

Tonight the second XIAO was flashed for camera bring-up and booted announcing
`Node ID: obc-esp32-s3-001` — the live mesh node's identity — and immediately
began emitting `link_state` JSON under that name on its spine UART. The mesh
supervisor keys everything on node id. Two boards sharing one is the same
identity confusion the on-air forgery work exists to detect, except arriving from
inside the fleet, where nothing is watching for it.

Nothing reached the air, for one reason: that board's UART was not yet wired to a
radio. **Step 4 of the plan was to wire it to one.**

It nearly happened earlier and more stupidly, too. The step before was "flash the
spare XIAO", and when the ports were enumerated the only ESP32-S3 attached was
the live node. Both boards are the same model from the same batch; their MACs
differ only in the last three bytes. Nothing on the desk or on the screen told
them apart.

**Identity now derives from the chip's factory MAC.** A small roster maps known
MACs to readable names, so `obc-esp32-s3-001` stays attached to the board the
host already has world memory, pushed limits and bench records for — renaming it
would have been a large, pointless blast radius. An unrostered board self-names
`obc-esp32-s3-<last three bytes>`.

That fallback is ugly on purpose, and the ugliness is the design. **A fixed
fallback is what caused this**, exactly as a default pin map let `camera.rs`
claim the wrong board through two corrections. There is now no default to be
wrong: a board either has a name someone wrote down against a measured MAC, or it
has one no other board can hold.

Rejected: **NVS provisioning**, which the old comment promised and whose
machinery already exists. It buys renaming-without-reflash, which nothing needs,
and it owes an answer for an unprovisioned board — the one question with no safe
default. Revisit when a board must be renamed in the field. Rejected: a
**build-time env var**, which is the cheapest code and can be set *wrong*
silently, which is the failure being fixed.

The fix created its own hazard, and it is the hazard this repo keeps re-learning:
the roster now lives in three places — firmware, the host's peripheral registry,
and the bench script that decides which port is safe to flash. `camera.rs`
contradicted its own `Cargo.toml` two directories away for weeks *because nothing
compared them*. So `tests/firmware_identity_roster.rs` compares all three and
fails on drift, and the gate script moved into the repo to be comparable at all —
a control that exists only on one bench machine is not a control.

The mapping also moved into its own ESP-free module so the host test executes the
real code, the same split as `sensor_math` / `sensors`. Behind an `esp_idf_svc`
import it could never run, and a rule about fleet identity that nothing can
execute is a rule on trust.

### The transferable part

Two things. First: a comment that says "in production this should be X" is a
known defect with no due date, and it will be paid on the day a second unit
exists. The cheap version of this fix was available for months.

Second, and sharper — **the boot log now prints the MAC beside the name, always.**
A name alone is an assertion. The collision was invisible because both boards
asserted the same thing with equal confidence and nothing underneath it was
visible. A shared name with the MAC beside it is a contradiction you can see in
one board's log, instead of a fleet-wide comparison nobody runs.

---

## 2026-09-16 — A cargo feature cannot isolate the camera build, and half of it can be isolated anyway

Bringing up a camera node needs three things the default firmware build does not
have: a pin map, PSRAM, and the `espressif/esp32-camera` IDF component. Only the
first is a cargo feature. The other two are ESP-IDF-level and, as the tree stood,
both were global — so building the camera changed what a *default* build of the
tree produces, and the only thing stopping a wrong binary reaching the live mesh
node `obc-esp32-s3-001` was me saying not to.

That is the shape this project keeps finding: a rule that exists only as prose.
It is the same failure as `camera.rs` claiming a board it had never been checked
against. So the two halves were settled separately, and honestly.

**PSRAM: isolable, mechanically.** `esp-idf-sys` 0.37.2 reads
`ESP_IDF_SDKCONFIG_DEFAULTS` as a `;`-separated list (`build/config.rs:25-27`,
`parse::list` at `config.rs:187-202`), later entries winning. The camera overlay
now lives in its own `sdkconfig.defaults.camera`, and a camera build names both
files in that variable. A default build does not set the variable and therefore
cannot see the overlay. The isolation is the *absence* of an environment
variable, not a promise in a document.

Two sharp edges are recorded where they bite rather than here: the variable
**replaces** the list instead of appending (`set_when_none`, `config.rs:139-144`),
so omitting `sdkconfig.defaults` silently drops the 32 KB main-task stack that
three crashes and a measurement bought on 2026-08-22 — a boot loop whose cause
would look nothing like its origin. And the automatic `sdkconfig.defaults.<x>`
suffix expansion (`common.rs:263-300`) cannot express "camera": `<x>` resolves
from cargo's `PROFILE`, which is only ever `debug` or `release`
(`common.rs:259-261`). That dead end is written into CAMERA.md so the next person
does not spend the same hour on it.

**The component: not isolable, and that was verified rather than assumed.**
`extra_components` is passed to `try_from_env()` as an exclude
(`cargo_driver/config.rs:72-74`); its doc comment says outright "This option is
not available as an environment variable." And the `cargo metadata` invocation
that reads it passes no feature flags (`config.rs:107-113`), while `CARGO_FEATURE_*`
appears nowhere in esp-idf-sys's `build/`. The build script cannot observe the
feature set of the build it is part of. With the block uncommented, a
camera-feature-*off* build still downloads the component, compiles it into the
IDF, and emits the bindings module.

So there is no mechanism, and inventing one would mean a second firmware crate
duplicating the command loop for a single board. **Chosen instead: the block stays
commented on `main`; camera bring-up happens on a `camera-bringup` branch.** The
containment is still social, but it is now *visible* — a tree that would flash the
wrong binary to the live node is a branch name in the prompt rather than a
paragraph nobody re-reads. Prose that you can see is not the same as prose that
you must remember.

Rejected, with triggers to revisit:

- **A separate `obc-esp32-s3-camera` crate.** Clean isolation by construction, but
  it duplicates the command loop and spine plumbing to serve one board, or forces
  a shared-library split today for a node that has never booted. Revisit when a
  *second* camera board needs a different component set, or when the camera node's
  code diverges enough that the shared main is fiction.
- **The optional-dependency seam.** `extra_components` is also collected from
  direct dependencies (`cargo_driver/config.rs:283-297`), so an optional dep
  carrying the block might drop out when its feature is off. The explore pass
  flagged this as *unverified* — whether cargo's resolve graph actually omits an
  unenabled optional dep there was not tested. One untested mechanism for one use
  is speculative abstraction. Revisit only if the branch discipline actually
  fails, and verify it before building on it.

### The transferable part

"Can this be gated?" is a question about someone else's build script, and the
answer is in its source, not in its name or its README — that crate's own
`BUILD-OPTIONS.md` is stale in three places against the code. Twenty minutes of
reading turned one guess into one mechanism and one honest "no mechanism
exists", and the honest no is worth more than a clever workaround would have
been: it names what is protecting the live node, which is discipline, so the
discipline could at least be made visible.

---

## 2026-09-16 — The board the brain is plugged into is not a node, and it is the one thing on the mesh it cannot hear

Third variant of one root cause in a single evening, which is why it gets its own
entry rather than a line in the one below.

**The shape.** The host's model of the mesh is built from `SPINE ◄` lines on one
station's console. Everything it knows arrives as a *received* frame. But the
station at the end of that cable never receives its own frames — it transmits
them, and a transmitted frame is a `SPINE ►` line. **The board the brain is wired
to is structurally invisible to the brain.** Tonight that produced three separate
failures, each of which looked like something else:

1. *Frames the station refuses* → printed as `SPINE ◄ REJECTED`, dropped by the
   parser for want of a `seq=`. On-air forgery was invisible. (Entry below.)
2. *The node's uplink*, when the node is jumpered to that same station → wrapped
   and transmitted, logged `SPINE ► (uart)`, dropped by category. The node looked
   dead for a whole session while beaconing every 30.78 s.
3. *The station's own liveness* → never heard at all, so the mesh supervisor
   presumed it lost. `gw-40`, "offline for 43.5 hours", `escalated_count` pinned
   at 1, `safe-mesh-node-lost` firing at Critical every tick until the System 2
   wake budget swallowed it. The log shows `System 2: suppressed (wake budget)`
   on repeat — a real node loss at that moment would have been indistinguishable
   from the noise.

**Why the existing guard missed it.** `snapshot` already refuses to invent nodes
from entity names: a node exists only if its rollup carries `Origin::Observed`,
which closed the 2026-07-17 phantom loop. `mesh.gw-40` passes that check
honestly — it *was* heard on the air, for weeks, while it was the field bridge.
Then the console cable moved to it and it went silent forever. The guard asks
"was this ever real?", and the answer was yes. The question that needed asking is
"can this still be heard?".

**Decision.** Discovery is authoritative *and* liveness must be. The operator
declares which board the console belongs to (`[lora_gateway] station`, recorded
as the fact `spine.station`), and `snapshot` excludes it: a board that cannot be
heard is not a node whose silence means anything. Its liveness already has a
correct and separate signal — `spine.gateway`, the console link itself. Standing
conclusions from before the declaration are *withdrawn* on the next tick with a
reason, not merely dropped from the count: `escalated_count` recomputes from the
views either way, but an "escalated" fact nobody will ever revisit is worse than
the count it stopped feeding.

**The claim is checked, not trusted.** The host cannot discover its own station —
it never sees the boot banner, because the gateway deliberately holds DTR/RTS low
so opening the port does not reset the board. So this is an operator's assertion,
and it is stamped `source: "config"` to say so. But it is falsifiable: the host
can never legitimately *receive* a frame whose `src` is its own station, so one
arriving means the setting names the wrong board — or something is impersonating
the board the brain is wired to. Either way the gateway says so at error level,
naming the consequence (the supervisor is skipping that id on the strength of the
setting).

**Options not taken.** *Learn it from the banner* — the host never sees one, and
resetting the station to provoke one trades a real outage for a label. *Exclude
every `gw-` prefixed id from node escalation* — a lost **bridge** is real news
and the mesh is partitioned; only the console's own board is unhearable.
*Ingest the station's own `SPINE ►` lines* — they carry no `ctr=`/`mac=`, so
`LoraAuth` would have nothing to verify and the host would be trusting a console,
which is the boundary SPINE-AUTH exists to hold. *Leave it and let the operator
ignore the escalation* — that is alarm fatigue written into the product, and it
was already suppressing wakes tonight.

**Consequences.** One optional config key; unset, behaviour is exactly as before
and the gateway warns at startup that the console's board will be judged as a
node. A bench whose stations swap roles needs the key updated — and will be told
loudly if it is not, by the frame that proves it wrong. The deeper lesson is
recorded in `BENCH-PINOUT-CARDS.md` Card 0, whose jumper block had named a board
outright and so quietly became the failure mode when the boards swapped.

## 2026-09-15 — A frame the station refuses is invisible to the brain, and the fix is a weaker signal, not a louder one

Found while preparing the bench for the alarm the entry below decided. The
bench could not be run as conceived, and the reason is worth more than the
bench was.

**What the code says.** A station verifies every frame at the radio and
forwards nothing it refuses — `heltec-lora-linktest/src/main.rs`: *"Order
matters: the tag first, so an attacker cannot move a window with a frame
they cannot sign … Nothing unverified reaches the UART, the log line the
host parses, or the relay."* A refusal becomes one console line,
`SPINE ◄ REJECTED src=… ctr=… : bad tag …`, which carries no `seq=`; the
host's `parse_gateway_line` requires `seq=` and returns `None`. So the
line is printed, read off the wire by the host, and discarded.

**The consequence, stated plainly.** `spine.auth.<station>.alarm` fires
only when the host refuses a frame *the station accepted*, which happens
only when the station forwarding to the host holds a different root than
the host — a replaced or mis-provisioned base station. That is the threat
`lora_gateway.rs` documents ("the host trusts the station's radio, not its
console") and it is the one the 09-13 bench exercised: the four `BadTag`
in the entry below came from a wrong-root *build*, not from a third party
on the air. **A stranger transmitting forged frames at an honest station
produces no fact, no alarm and no escalation — `status` stays clean.**
That is the inverse of which threat is likely.

**Decision.** The host learns to read the refusal line the station already
prints, and raises a **separate and deliberately weaker** signal:
`spine.air.<station>.refused` `{kind, count, since_ms, last_ms}`,
burst-shaped like the auth alarm (one fact per burst, the count travelling
on the clear), driving a new standard rule at lower severity than
`safe-spine-forgery`. Only `BadTag` counts: `Seen` cannot distinguish a
relay duplicate from a replay at the station and is normal traffic,
`Runt`/`SeqMismatch` are RF and foreign protocols, and `TooOld`/`Store`
are the station's own local conditions.

The weakness is the point and must not be papered over: **this signal is
asserted by the station over an unauthenticated console**, so anyone who
can write to that serial line can fabricate it — the same wire
`DECISIONS.md` 2026-09-13 already flags for the bridge. It therefore
advises and must never safe the mesh, and it does not touch
`spine.auth.<station>`, whose meaning stays exactly what the entry below
gave it: *the host refused a frame*, cryptographically, on its own
evidence.

**Options not taken.** *Have the station forward refused frames to the
host* — it would hand an unauthenticated stranger a write into the host's
parser, which is the one thing the radio-side check exists to prevent.
*Raise the existing `spine.auth` alarm from the refusal line* — it would
let console access manufacture an incident indistinguishable from a
cryptographic one, destroying the fact's meaning to gain a signal.
*Escalate at the same severity* — a forgeable input must not be able to
page a person at the same volume as an unforgeable one. *Report
`Runt`/`SeqMismatch` too* — that is a jamming and noise-floor signal,
which may be worth having, but runts are also just RF; revisit if the
bench shows a useful rate.

**Consequences.** One more entity per station and a ninth standard rule.
On-air forgery becomes visible for the first time, at a severity that says
how much the evidence is worth. Two distinct benches now exist where one
was thought to: a wrong-root board *in front of the host* fires the
authenticated alarm (never run — the alarm postdates the 09-13 rejections
that motivated it), and a wrong-root board *transmitting at an honest
station* fires the new advisory.

## 2026-09-14 — A replay or a bad tag is an incident, not a log line; a post-reset gap is neither

Closes SPINE-REPLAY.md §5, items 3 and 4, which the 2026-09-13 build left
open: where the host keeps its per-source anti-replay state, and what a
rejected frame does beyond being dropped.

**What the evidence says.** Since host-side verification shipped
(2026-09-13 12:46) the brain has judged **4827 frames from the bridge and
rejected none** — through a base power-cycle, forty station resets and a
poisoned NVS. The only rejections ever recorded were the ones the bench
manufactured: four `BadTag` from a wrong-root build, three `TooOld` at a
station after a reboot gap. The SX1262 drops CRC failures in hardware, so
a bad tag that reaches the host is never corruption in flight: it is a
wrong root or a forgery. On this mesh a rejection is signal.

**Decision.**

*Item 3 — state lives in world memory*, as built: `spine.auth.<station>`
holds `{ctr, accepted, rejected, last_rejected}` with M = 1, written on
every frame. Recorded here so it stops being an open item.

*Item 4 — three kinds of rejection, two responses.* `BadTag` and
`Replayed` raise `spine.auth.<station>.alarm` — a fact derived from the
auth fact, one per burst, carrying the reason, the counter and the RSSI —
and the standard safing rule set escalates it to System 2 the way
`mesh.escalated_count` drives `safe-mesh-node-lost`. The alarm clears
itself after ten minutes without a further rejection from that station,
so a burst is one incident with a start and an end. `TooOld` and
`Unsigned` do **not** alarm: `TooOld` is the bounded post-reset gap §3
chose, in the safe direction, and is expected after every station reboot;
`Unsigned` is a station on pre-step-4 firmware — a provisioning error the
auth fact already shows, not an attack.

**Options not taken.** *Feed `security/trust.rs`* — it scores actuating
nodes by command latency and success and gates their physical actions; a
station is not the actor, and a forger spoofs the victim's `src`, so the
penalty would land on the one being impersonated. *Alarm on every
rejection* — a station reboot would then page a person for the gap the
design deliberately accepts. *Alarm on a rate rather than the first
`BadTag`* — the first one is already never legitimate here; a threshold
would only delay the page. *Silence (leave it on the fact)* — "this
source is sending counters I have already seen" is exactly what §5.3 said
a person should be told about.

**Consequences.** One more entity per station in world memory and one
more standard safing rule; a wrong-root station plugged into the bench
will now wake System 2 once, which is the point. What a rejection does on
the *station* (its own console line) is unchanged — the station has no
one to tell.

## 2026-09-14 — A port that is not there at boot is an outage, not a misconfiguration

Reverses one line of the 2026-09-13 SPINE-LOSS entry below, which kept
the startup refusal: *"a misconfiguration at boot and a port that
vanishes at runtime are different things."* They are, and a port that is
absent at boot is the second kind. It bit three times in one day: twice
because a bench script held COM3 when the task restarted, and at 09:10
the next morning because the bench was simply unplugged when the machine
came back — the brain exited, and stayed down until someone looked.

**Decision.** The first open is still tried synchronously, so the common
case starts verified from the first frame. When it fails and world
memory is on, the gateway supervisor starts *in* the outage: `spine.gateway`
is `lost` with the open error from t = 0, the nodes read unobservable, the
command sink refuses with the same words, and the port is taken the
moment it appears, on the same 1 → 30 s backoff. `[descending]` refuses
to start only when nothing could ever produce a sink: no `[lora_gateway]`,
no `hardware` feature, or no world memory (a link nobody can record cannot
be supervised, and that body keeps the old rule).

**Options not taken.** *Keep the refusal and document the restart* — that
is the state that failed three times. *Drop the `[descending]` refusal
entirely* — a body with the policy on and no gateway configured is still
misconfigured, and should still say so at boot.

**Consequences.** A brain started with the bench unplugged now comes up,
records why it cannot hear the mesh, and hears it when the cable is in.
`status` shows the link line from the first second. The distinction the
09-13 entry drew survives in narrower form: configuration errors are
fatal, absences are outages.

## 2026-09-13 — Rules survive a node's reboot; limits do not, and the host puts them back

A node's host-pushed reflex rules and its Track 0 limits both lived only in
RAM. On 2026-08-22 the boot posture became deny-all so a reset could never
*widen* policy, and the node was made to announce its boot so a host could
notice. Nobody built the noticing. On 2026-09-13 the brain's first live
posture (`descend`, novelty 0.372 → slot 0 = 0.15) arrived at a node whose
die-temperature rules had died in a power cycle hours earlier: 154 reflex
reports that afternoon, every one `safe-link-offline`, the LED rule gone
and nothing saying so. The SPINE-LOSS entry below deferred the question to
the WILD port; this decides it.

**Decision.** The two halves are treated differently because they are
different things.

*Limits stay RAM-only and deny-all at boot.* They are actuator authority.
The host holds them (`[[safety.limits]]`), and the mesh supervisor
re-pushes them whenever a node names a boot the host has not pushed
against — `boot_id` on the boot announcement, on every beacon (with
`policy: "deny-all"` until a push lands), and on every reply — retrying
while the beacon still says deny-all. A `set_limits` fits a mesh frame.

*Rules persist on the node, in NVS,* tagged with firmware version and
schema, restored at boot through the same validation a push gets, and
cleared with a one-boot announcement (`stale` / `corrupt`) when they do
not pass. They carry no authority — every write a rule fires still goes
through the gate — and they do not fit a mesh frame (one rule is 330 bytes
against 228), so the host *cannot* put them back in the field. A rule set
that survives its own node's reboot is System 1 keeping its promise: "keeps
reacting when the host is unreachable" includes just after a reboot.

When limits land, the reflex engine *rearms*: a new policy is a new world,
and a standing condition whose write the old gate refused fires once more.

**Options not taken.** *Persist limits too* — reverses 08-22 for
convenience; a stale allow-list surviving a reflash is exactly the widening
that decision exists to prevent. *Re-push rules from the host* — requires a
chunked mesh push that does not exist, for a payload the census showed does
not fit; and the base station could not even carry a `set_limits` until
this work (its console read from a 128-byte FIFO — a claim in a census is
not evidence, only the air is). *A host heartbeat to nodes* — decided
against for now: a mesh node's "host link" means "commanded recently" and
is not read as a fault by anything; airtime spent to make a rule feel
better. *Rules re-pushed on USB only* — that is the state that failed.

**Consequences.** A node reset now ends with the node whole — rules from
its own flash within a second, limits from the host within a minute — with
nobody touching it; measured end to end on the bench
(`bench_rules_persist.py --live`, 62 s). The stored record's wire form is
now something a firmware version bump must consider (schema constant in
`rules_store`). Filed with the WILD port thread: `Oh-Ben-Claw/docs/WILD-2026-09.md`.

## 2026-09-13 — A lost spine is recorded, not survived silently, and never fatal

The first evening the brain ran with the mushroom body, the posture policy
and an authenticated LoRa gateway all live, the gateway's serial port went
away eleven minutes in (`os error 22`, the surprise-removal kind). The I/O
thread returned, the RX loop ended, one `WARN` was written, and the brain
ran for fourteen more minutes believing two healthy nodes were lost —
the mesh supervisor escalated both at 120 s — while a posture send failed
with "serial I/O thread has exited". An operator restart fixed it in
seconds. Design in [SPINE-LOSS.md](SPINE-LOSS.md).

**Decision.** The brain does not stop, and it does not pretend. Three
things, in order of value: a `spine.gateway` fact in world memory that
says whether the host can hear the mesh, written on every transition;
`MeshHealth::Unobservable`, so that while the gateway is down every node
is *unobservable* rather than *offline*, no escalation fires and the
offline clock does not run; and a reopen loop around `open_split`, 1 s
doubling to 30 s, forever, behind a writer the existing command sink swaps
in place so the sink handed out at startup survives the outage. The auth
window resumes from its persisted ceiling; no new auth state.

**Options not taken.** *Refuse to keep running without the spine when
`[descending]` is enabled* — consistent with the startup refusal, and
wrong: a misconfiguration at boot and a port that vanishes at runtime are
different things, and killing Telegram, memory and the episode record over
a USB hub blinking turns one lost link into a lost body. *Retry the failed
`descend` from inside the gateway* — the posture policy already retries on
the next turn and records the failure on the node's fact; a second retry
loop for the same idempotent command is how a node gets the same frame
four times. *A bounded number of reopen attempts* — a body meant to run
unattended does not give up on its own spine at 3 a.m. because the count
ran out.

**Consequences.** `decide` gains an input (the gateway state) and a fourth
health value, which every consumer of `mesh.<node>.health` must accept.
The 2026-09-12 entry below — *a check that could not run must not fail
like a check that did* — now applies to the mesh supervisor, which had
been the largest remaining place it did not. Two questions surfaced the
same evening are recorded in SPINE-LOSS.md §6 and deliberately not decided
here: whether the host owes the node a heartbeat (the node declares the
host lost 30 s after its last command, by design), and whether the host
should re-push RAM-only rules when it hears a node's boot beacon. Both
belong with the WILD port, and both are the mirror image of this one.
Nothing is built yet; this entry precedes the code, which is not the
usual order here, because the decision was needed to know what to build.

## 2026-09-13 — No language model on a node, and what would reopen it

The question was whether the ESP32 nodes should run a language model of their
own, so that a node cut off from the gateway could still reason. The survey
is `EDGE-LM-2026-09.md`; this records what it settled.

On the S3 N16R8 boards on the bench, nobody has demonstrated a model that
follows an instruction at a usable speed. The demonstrated points are a
sub-1M dense core writing children's stories at ~10 tok/s, and a real 135M
instruct model at forty-five minutes per answer. The one measured runtime
(slvDev, 2026-07-21) is PSRAM-bandwidth-bound at 60.7 MB/s with no vector
unit to speak of; its author says the lever is bytes-per-token, not compute,
and that his 28.9M parameter count is "never a capability multiple". The
vendor's own agent framework, ESP-Claw, runs rules and memory on the chip
and calls out for reasoning — which is the shape this repo already has.

**Decision.** The spinal tier stays what upstream `CONNECTOME-2026-09.md` §2.2 describes:
local reflex rules that run whether or not the gateway is reachable, and a
descending command that is a small modulation vector. Reasoning lives on the
gateway, and on the SBC edge loop when one is present (`edge.rs`). No node
firmware carries a language model, and no roadmap item assumes one.

**Options not taken.** *A tiny model on the S3* — the demonstrated ones cannot
follow an instruction, and a node that generates prose it cannot act on is
a heater. *An instruct model streamed from SD* — demonstrated at 45 minutes
per answer, which is not a reflex tier at any definition. *The ESP32-P4* —
the only board with a demonstrated instruction-follower (a 180M ternary MoE
at ~9 tok/s, tool-calling described by its own author as unreliable, and
unmeasured by anyone else). The P4 has no radio on-chip, so a P4 node is a
P4 plus a radio MCU plus a UART between them — the unauthenticated serial
wire the entry below already flags for the bridge, now on every node. That
is a different node design, not a faster one, and it would have to be
decided on its own terms before a board is bought.

**What would reopen this.** Not a bigger model on a newer chip, and — 
corrected the same day, after reading `obc-reflex` and `posture.rs` rather
than the survey — not a bandwidth benchmark either. A `descend` is at most
sixteen levels in `[0, 1]`; a node-side policy that produced them from its
own sensor snapshot would be a map of a few dozen weights, which fits an S3
without a single trick from the survey. Compute was never the question. What
is missing is a **metric** for what a better posture is and **data** on
which the current one-bit policy (novel → cautious) has been scored, and
the one-bit policy has not yet run live at all. So: the harness
`crates/obc-memory/tests/posture_real_effect.rs` (upstream) reads the
`descending.*` and `mesh.<node>.reflex` facts the brain already records and
prints three candidate metrics — whether posture is mechanically live at
all, whether caution buys Track 0 refusals, and the lost-frame natural
experiment on outcomes. When it has run against weeks rather than hours,
and one metric has been chosen and recorded here, a learned policy has
something to beat. That would be its own ADR. A language model still would
not be the object under discussion.

**Consequences.** The int8 wake-word spotter in V2-IMPLEMENTATION is
unaffected; it is TinyML, not a language model, and this decision does not
touch it. `V2-STRATEGY.md` §F's "small-model reflex tier" is confirmed as
an SBC feature and should not drift toward the MCU in later revisions. A
node that loses the gateway degrades to its rules, and says so in its
announcement, which is the behaviour the safety model already assumes.

## 2026-09-13 — The stations hold the root secret, and there is no permissive mode

SPINE-AUTH.md §3.1 provisions each *node* with only its own derived key, so
a captured node cannot impersonate a sibling. Step 4 put the tag on the wire
between the two Heltec stations, and the first question was which key a
station carries.

A station is not a node. It is the infrastructure that verifies every frame
on the air, from every source — the base verifies the bridge, the bridge
verifies the base, and a third station would verify both. A station holding
only its own key can sign and cannot check, which is the half of
authentication that catches nothing. It needs every source's key, and every
source's key is, by construction, the root.

**Decision.** Each Heltec station is built with the deployment's root
(`OBC_SPINE_ROOT`, a build-time environment variable; a build without it
fails and says what to set) and derives `HKDF(root, "gw-XX")` for any `src`
on first hearing it. The root never enters the repository; the boot log
prints two bytes of its SHA-256 so two boards can be compared without
printing it.

**Options not taken.** *A key table per station* (each peer's derived key
flashed in, no root) is the same secret material in a different shape: a
table of every derived key lets an attacker sign as every station, exactly
as the root does, and it has to be regenerated and reflashed on every
station whenever a station is added. *Asymmetric keys* (§5.1) would let a
station verify without being able to sign as anyone — the real fix — and
cost 64 bytes per frame on a 240-byte radio budget. Still the right answer
for MQTT; still disqualified on LoRa by arithmetic.

**Consequences.** Extracting the root from a station's flash is the "cloned
node" threat of SPINE-REPLAY.md §4, one station wider: the attacker can
sign as any station, not just one. That widening is accepted because the
stations are the same physical class as the nodes and are deployed the
same way, and because the alternative was a scheme that verifies nothing.
Revocation is reflash-everything, as §3.1 already said. Nodes on the far
side of a station's UART are outside this entirely — the bridge signs what
it forwards, and the node ↔ bridge serial wire is unauthenticated.

**And no permissive mode.** §4 asked for a strict-by-default config key
with a migration window; the built form has no key and no v1 path. The
fleet is two stations on one desk; a migration window with nobody in it is
a fallback with only one user, and §4 names who that is. If a third station
arrives running v1 it will be rejected loudly, one line per frame, which is
the correct thing to happen to a station that has not been provisioned.

## 2026-09-12 — A check that could not run must not fail like a check that did

`parity`'s `peer` job compares the 12 generator mirrors against the generator's
own copies. The generator is private, so the comparison needs `PEER_REPO_TOKEN`
— a fine-grained PAT with a **30-day life**. Issued 2026-07-30, green
2026-08-22, dead by 2026-09-06, and dead again on 2026-09-11.

When it lapses, `actions/checkout` dies with "Bad credentials" and the job goes
red. On the run list that red is indistinguishable from a mirror that genuinely
drifted, and the obvious first move — open the manifest and look for the file
that moved — is the wrong one. The measured shape of the 2026-09-11 failure:
eleven of twelve jobs green, `peer` dead at its second step, **nothing
compared at all**.

`parity.yml` has said exactly this in a comment since 2026-09-06: *"Either way
it reads like drift and is not — a drift failure names a file and two hashes."*
That was right, and it was a comment. It did not stop the same confusion
happening five days later, because a comment is read by whoever is already
reading the file, and the person looking at a red run is looking at the run.

**Decision.** `scripts/check_peer_access.py` runs **before** either checkout and
makes one API call to the repository endpoint. It separates the four states that
"Bad credentials" collapses into one:

| | meaning | fix |
|---|---|---|
| no token, 200 | the generator went public | correct this file and `parity.yml` |
| no token, 404 | the secret was never set | set it |
| token, 401 | expired or revoked | re-issue the PAT |
| token, 403 | SSO not authorised, or rate-limited | authorise, don't re-issue |
| token, 404 | valid, but not granted this repository | widen the grant |

**It does not let the job pass.** That was the tempting version and it is wrong:
unreadable peer means the mirrors are unverified, and unverified is not
verified — the same rule that makes a Blender-less `verify-artifact` exit 3
rather than 0 in OpenDesignCore. What changes is only that the red states its
own cause, in the step summary as well as the log.

The diagnosis function is pure and `--selftest` drives all seven cases through
it, asserting among other things that **no two produce the same headline**. A
preflight whose messages read alike would be this same defect one layer further
in.

**And a second decision, because the first one only fixes half of it.** Making
the red legible does not change *when* anyone sees it: still whenever someone
next pushes. `peer-token.yml` runs the same probe on a daily schedule, so a
lapse surfaces within a day of happening — and, where GitHub reports the token's
expiry, up to a week before it. Two things about it are deliberate:

* **It is its own workflow, not a `schedule:` on `parity.yml`.** That file has
  twelve jobs, one building every vendored crate twice and another installing
  cargo-audit from source. Twenty minutes a day to check one credential, with
  the answer buried among eleven other results, against a notification that
  says "peer token".
* **It survived the fix.** The PAT was replaced on 2026-09-12 with one that
  **does not expire**, which removes the clock that caused both lapses and none
  of the other ways the token can die: revocation, an organisation policy sweep,
  a repository rename. A non-expiring token is arguably the *most* likely to be
  swept, because it never prompts a review. All of those arrive as the same
  "Bad credentials".

**An early-warning path was written and deleted the same day.** It read GitHub's
`github-authentication-token-expiration` header and warned a week ahead. Against
a token that does not expire, that branch cannot fire — so it would have shipped
a warning that can never happen, dressed as a safety net, for a hypothetical
future PAT nobody has decided to issue. Deleted under the same rule as an
unreachable module: not added, because nothing calls it.

Recording one loose end rather than losing it: the header was never confirmed to
arrive at all. It was tried against a `gho_` OAuth token (no expiry, no header)
and then against the new PAT (no expiry, no header) — both observations equally
consistent with GitHub not sending it for these token types. Anyone re-adding
this on an expiring token should verify the header exists **before** building on
it, rather than inheriting the assumption from here.

This is the second time this repository has converted a prose warning into a
gate for the same reason. `check_vendored_mods.py` exists because
`sync_upstream.py` described "the exact failure mode this script exists to
prevent" in a comment; a fortnight later that failure mode happened. The
pattern is worth naming: **when a file has to explain how to read its own
failure, the explanation belongs in the failure.**

---

## 2026-09-11 — A bundle we did not build is not a bundle we can vendor

`sync` copies five wasm artifacts out of upstream's `planner-wasm/pkg/`. That
directory is **gitignored upstream**: it holds whatever the last `wasm-pack` run
left there, and nothing says which branch that run was on.

Without `--rebuild-wasm` the script already declined to describe such a bundle —
the `wasm_build` block is only written by a run that did the build, on the stated
grounds that a sync which merely copied a bundle "has no standing to say what
that bundle was compiled from". That reasoning was applied to the metadata and
not to the bytes: the copy happened anyway.

Found on 2026-09-11. A sync on the `mcp-respawn-dead-server` branch pulled in the
bundle left over from the `registry-lilygo-t-camera-plus-s3` build. `check
--upstream` did catch it, because `registry.rs` is a recorded build input and had
changed between the two branches — but that was luck. A foreign bundle whose
`WASM_SOURCES` happen to match would have passed every gate: the artifact hashes
cannot see it (a compiled file never drifts from its own hash), the build-input
hashes would agree, and only `verify_wasm.cjs`'s behavioural goldens stood
between it and being vendored.

**Decision.** `sync` refuses, and copies nothing, when it is not rebuilding and an
incoming wasm artifact's bytes differ from the vendored one. Identical bytes are
not refused — there is nothing new to vouch for — and `--rebuild-wasm` is the
supported way to change the bundle. It costs about thirteen seconds.

**Consequences.** A sync whose only obstacle is the bundle now stops instead of
half-applying, and says which file and which two hashes. The refusal is exercised
by `python scripts/sync_upstream.py selftest`, which drives the decision over a
scratch tree in three states and runs in CI beside the other gates: this
repository's rule is that a gate whose first run is green has proved nothing.

The narrower mistake that went with the discovery is worth recording too. The
first commit on that branch staged `parity/MANIFEST.json` without the wasm file
it described, so the manifest claimed a hash the committed bundle did not have.
That is a different failure, and the existing `check` catches it exactly as
designed — reproduced against the commit afterwards, and it reports "edited since
sync" with both hashes. No gate was missing there; the `git add` was selective.

---

## 2026-08-14 — The mirror repository merges first, and the gate never said so

A sync that touches one of the generator's mirrored artifacts needs two pull
requests: the manifest and the vendored copy here, the rebuilt mirror there. The
`peer` job checks out the generator's **default branch**, so from the moment this
repository's PR opens until the generator's PR lands, the job reports:

    x wasm/obc-planner/obc_planner_wasm_bg.wasm: generator mirror DRIFTED

which is true, and points at the manifest, where nothing is wrong.

**Decision: the generator PR lands first.** Both orders leave one repository's
main briefly disagreeing with the other. Generator-first makes that window a job
that nothing re-triggers; here-first makes it a red main the moment the merge
button is pressed.

**Correction, same day.** The first version of this entry said the job "cannot be
fixed by making the job smarter", because a gate comparing two repositories has
to read *some* revision of the second and the only one it can name unaided is the
default branch. The second half is true; the conclusion was not. The job could
check out a generator branch whose name matches this PR's head ref when one
exists, and fall back to the default branch otherwise — an ordinary pattern, and
a real fix.

It was not taken at first, on the grounds that it makes a green CI run depend on
a branch-naming convention nothing enforces: name the generator branch
differently and the job falls back to the default branch.

**Second correction, same day — that objection was also wrong, and the job now
does the branch matching.** The fallback does not pass quietly, which was the
whole force of the argument. If the names do not match, the job checks the
default branch and reports drift, exactly as before. There is no path through
branch matching that turns a real mismatch into a pass.

What is true is a different hazard, and it needed a different guard. A PR that
goes green on a peer *branch* invites merging this repository first, which is
the single order that puts a red on `main`. So the second answer is scoped to
`pull_request` only — the `push: main` run reads the default branch and nothing
else, so main cannot go falsely green — and when the second answer is used, the
job emits a warning and a step summary saying that main will be red until the
generator PR lands. Green with a stated debt, rather than green.

**The decision therefore stands unchanged: the generator PR lands first.** What
changed is that the PR check no longer blocks on it, and that the requirement is
now stated by the tooling in three places instead of living in whoever last hit
it — the failure text, the job summary, and the peer revision line that `check`
now prints alongside the upstream one.

Both superseded sentences are left above with their corrections beneath rather
than edited away. An append-only log that quietly fixes its own claims is not
one, and the shape of the mistake is the useful part: twice I reached for a
structural reason ("cannot be fixed", "would pass silently") when the actual
reason was a preference for the simpler rule. The first is an argument the next
reader cannot check; the second is one they can disagree with.

### The transferable part

The failure message was accurate and misleading, which is the same shape as three
other findings in this repository: the counts gate hiding a live number, the drift
gate measuring the wrong revision, the reachability survey guarding half its
inputs. A check that cannot distinguish "wrong" from "not yet" should say so in
the failure text, because the reader has no other source. Both the workflow
comment and the message itself now name merge order as the first thing to rule
out.

---

## 2026-08-13 — A crate owns its own configuration block, and that was the whole endgame

Recorded here because this repository has been following the rule since its
third crate without ever writing it down, and upstream's last seven dependency
cycles turned out to be the four places it had not been applied.

**The rule.** A module's configuration struct lives with the module. The root
`Config` composes it. `obc-planner` owns `DeploymentConfig`, `obc-conscience`
owns `ConscienceConfig`, `obc-cost` owns `CostConfig`, `obc-tunnel` owns its
own — every crate vendored here already works this way, which is why none of
them needed the root config module to exist in order to compile alone.

**What it cost to have four exceptions.** `ProviderConfig` was defined in the
root config module while two of its own field types lived in `providers`, and
all ten provider files imported the struct back. One struct, split across two
modules, pointing both ways — three cycles. `SpineConfig` and
`MeshSupervisorConfig` were four references and the entire dependency of a
5100-line module on anything else in the tree — four more cycles.
`AutonomyConfig` was two.

Moving each one to the module that reads it took the core from sixteen cycles
to zero. No interfaces were designed and no logic changed.

**Why it matters to a reader of this repository specifically.** The reason every
crate here can be built and tested with no siblings is this rule, applied by
accident at first and then on purpose. A crate that reaches into a central
config module for its own settings cannot stand alone, and the `substrate` job
would catch it — but only after someone had already written it that way. The
rule is the thing that stops it being written.

**One correction worth keeping**, because it is the argument for measuring
rather than reasoning. Upstream put `AutonomyLevel` and `AutonomyConfig` in
`agent` first, since the agent reads them. The cycle count stopped at two
instead of zero. Autonomy *level* is the approval policy — how much a human has
to confirm — and `approval` is the module that turns it into an
`ApprovalManager`. One module further, and the count went to zero.

The rule was right and the noun was wrong, and the instrument said so within
minutes. That is the more useful half of "measure rather than judge": not
measuring to prove you were right, but measuring so that being wrong is cheap.

---

## 2026-08-13 — At eight occurrences it is a rule, not a knack

An entry below, written yesterday, called turning an edge "the answer three
times now" and listed three. It is eight. Recording that as its own entry rather
than editing the count, because the number *is* the argument: three times is a
run of luck, eight times is a shape the codebase reliably produces.

| what left | what was in the way | what moved |
|---|---|---|
| `obc-movement` | `Arc<SpineClient>` in an actuator sink | the sink, to the spine |
| `obc-a2a` | nothing referenced it | an executor, written next to the agent |
| `obc-reflex` | `Arc<SpineClient>` in an action sink | the sink, to the spine |
| `tools -> agent` | two `use` lines in a `#[cfg(test)]` module | the tests, to `tests/` |
| `spine -> agent` | `Severity`, `DIGEST_PREFIX` in the notify module | the vocabulary, to `obc-reflex` |
| `agent <-> skill_forge` | `impl ReplayExecutor for Agent`, next to the trait | the impl, next to the type |
| `obc-fleet` | a 60-line MQTT bridge in the coordinator | the bridge, to the spine |
| `obc-audio` | two `SpeechSink` impls with dependencies | both impls, to the spine and the tool layer |

The shape: **a trait declared next to its caller, implemented next to its
caller, for a type that lives somewhere else.** Rust permits the implementation
in either place as long as one of them owns the trait, so the compiler never
objects. Only the dependency graph does, and only if something is looking.

Three of the eight were not production code at all — two test modules and a doc
comment. That is the least intuitive part and worth stating plainly: a `use`
line inside `#[cfg(test)]` and a rustdoc link are both dependency edges, and a
graph built from text cannot tell either one from a call in a hot loop.

`obc-fleet` is a genuinely different animal, and it is why this is a new entry
rather than `s/three/eight/`. The others were each one thing in the wrong place.
That one was the *same integration implemented from both ends* — the coordinator
bridging itself onto MQTT, while the spine was already bridging LoRa into the
coordinator from its own side. Both halves looked reasonable where they sat.
Neither is a mistake anyone made; it is what happens when two modules are each
maintained by someone who reasonably believes the integration is theirs.

The actionable consequence: **when a two-module cycle resists the "one misplaced
item" reading, look for a duplicated responsibility before looking for a design
problem.** It was faster to find than either.

---

## 2026-08-13 — Two crates arrived that nobody decided to move

`obc-foresight` (677 lines) and `obc-learning` (454) are here, and this entry
exists mostly to record that neither was a decision. They are the first
arrivals in this repository that were not selected — by reading imports, by
`extractability.py`, or by anyone weighing what the public repo most needed.
They fell out.

The chain, smallest thing last: `learning` was blocked by `foresight`,
`foresight` was blocked by `reflex`, and `reflex` was blocked by a single action
sink holding an `Arc<SpineClient>` — one field, one constructor parameter, two
topic constants. Turning that one edge released **2455 lines across three
crates** in three commits, and the two here moved no logic whatsoever: eight
paths spelled `crate::memory::world::` became `obc_memory::`, names that had
been a crate since 2026-07-30 and were still being read through the agent's
re-export table.

The entry below this one already argued that a blocking-edge count says nothing
about what an edge costs to turn. This is the same claim from the other end:
**turning one cheap edge can release work you were not planning to do.** The
useful consequence is scheduling, not philosophy — after any edge-turning
commit, re-run the survey before deciding what is next, because the answer may
have changed underneath the plan. Upstream's `docs/ENDGAME.md` predicted these
two specifically and was right about them, and wrong in the same paragraph
about which back-edges the move would break. Both halves are recorded there.

One thing here is a decision rather than a consequence: **the approval gate did
not come with `obc-learning`.** `tests/learning_approval_gate.rs` asserts that a
mined rule is inert until approved, and it does so against a real
`ForesightEngine` rather than a mock. Vendoring the crate without it would have
put a rule-synthesis engine in a public repository with its central safety
property untested here. Keeping it upstream is the honest option of the two
available — the alternative was a weaker local restatement — and it is why this
crate's row in the README says 4 tests rather than a number that flatters it.

---

## 2026-08-12 — Turn the edge; do not wait in the queue

`obc-reflex` is here, and the entry below it — dated 2026-08-01 — says the
reflex engine "is in the core crate's `agent/` behind thirteen blocking edges
and cannot move yet." That was true when written. What made it stop being true
is worth a decision record, because it changes how the queue is read.

The extraction queue is produced by upstream's `scripts/extractability.py`,
which ranks each module by how many outward edges point at something still in
the core tree. Read naively it is a work order: take the zeroes, wait on the
rest. Three times now the useful move has been the opposite — pick the edge
rather than the module, and reverse it:

| what left | what was blocking it | what moved |
|---|---|---|
| `obc-movement` | `Arc<SpineClient>` in one actuator sink | the sink, to the spine — 39 lines |
| `obc-a2a` | nothing; nothing referenced it either | an executor, written next to the agent |
| `obc-reflex` | `Arc<SpineClient>` in one action sink | the sink, to the spine |

The shape is the same each time: **the trait stays where the abstraction is, the
implementation goes where the dependency is.** The crate declares `ActionSink`
or `ActuatorSink` or `TaskExecutor`; the thing that needs the spine, or the
agent, implements it from the other side and stays behind. The dependency
arrow reverses without either side changing what it does.

The cost of not knowing this: `obc-navigation` is 3714 lines and was blocked by
`obc-movement`, which was blocked by 39 lines. Read as a queue, that is a large
job waiting on a medium job waiting on a small one. Read as edges, it is one
`Arc<SpineClient>` field holding back 4416 lines — `wc -l` across both crates'
`src/` as vendored here — and it took an afternoon.
`obc-reflex` at thirteen edges and `obc-navigation` at one looked like very
different problems and were not.

What the instrument cannot tell you, stated so nobody mistakes the ranking for
the answer: **a count of blocking edges says nothing about how expensive each
edge is to turn.** Thirteen small edges is a smaller job than one that runs
through a cycle. Upstream's `scripts/core_endgame.py` was written for the
second half of that sentence — what remains in the core is cyclic rather than
merely dense, and no ordering of extractions solves a cycle.

One other thing this entry records, because it is the same failure this
repository keeps documenting in its own code: **eleven crates arrived between
the entry below and this one, and none of them got an entry here.** The
narrative went into `scripts/sync_upstream.py` comments, the `substrate` job's
comment block and the README instead — all three of which are read more often
than this file, which is most of why it happened. The log was not wrong; it
just quietly stopped being the place the reasoning lived. It is not
back-filled here — inventing eleven contemporaneous records after the fact
would be worse than the gap — but the gap is now on the page rather than
implied by a date.

---

## 2026-08-01 — The next piece is chosen by a script now, and this is the first one

`obc-telemetry` — `power`, `comms`, `sensing`, 1,015 lines, 18 tests — is the
fourth crate vendored here and the first that nobody picked by reading imports.

The core repo now has `scripts/extractability.py`: per module, the outward
edges, split into *blocking* (points at something still in that tree) and *free*
(points at a crate that has already left, which a new crate can simply depend
on). It is the mirror of the existing `curation_survey.py`, and the two ask
opposite questions — who references this, versus what does this reference. Only
the second one predicts whether a piece can move. The three suites were among
six modules with zero blocking edges.

Two things about that script are worth carrying over here, because this
repository is downstream of its judgement:

- **Its first version was wrong, in the direction that would have cost a week.**
  Counting only `use crate::…` declarations, it reported `config` — 3,430 lines,
  58 dependents — as having no outward edges. It has six; its struct fields are
  typed with inline paths like `pub server: crate::mcp::McpServerConfig` that no
  `use` line records. That is the same failure the sibling script was corrected
  for in July, which is why the two now share one parser.
- **The verdict was then confirmed by a compiler**, before anything moved:
  `src/comms/mod.rs` compiled in a scratch crate whose entire universe was
  `obc-memory`, serde and anyhow. A survey saying "no blocking edges" and a
  compiler agreeing are different claims, and only the second is load-bearing.
  The extraction that followed needed no call-site changes at all.

Why these three and not `scheduler`, `a2a` or `observability`, which were
equally movable: the queue says what *can* move, not what *should*. The README
says the reflex layer keeps working when the brain is unreachable, on ten
separate lines, and backed it only with vendored firmware. The three suites are
the host side of that — each turns a raw reading into a world-memory fact plus a
coarse mode (`power.mode`, `net.mode`, `sensor.{quantity}` and a quality flag),
and the mode is what a reflex rule watches, since a rule cannot reason about
millivolts.

Stated plainly rather than left to be found: this backs half the sentence. The
reflex *engine* is in the core crate's `agent/` behind thirteen blocking edges
and cannot move yet. A claim half-backed and labelled as such is worth more than
one wholly unbacked and unlabelled, but it is not the same as done.

---

## 2026-08-01 — Track 0 comes here third, because the safety claim was the one a reader could not check

`obc-safety` is the third crate vendored from the core agent, after `obc-memory`
and `obc-planner`. The order was not chosen by importance — on importance this
one goes first. It was chosen by separability, which is the only thing that makes
a piece movable, and Track 0 did not become separable until upstream fixed a
dependency that pointed the wrong way.

Three of its files — `audit.rs`, `taint.rs`, `trust.rs` — imported `RiskClass`
and `BlastRadius` from `crate::tools`, so the safety layer depended on the
largest and least self-contained module in the tree. Those four types are the
*contract* the tool layer is checked against, not tool machinery. Upstream moved
them down into `obc-safety::risk` and had `tools::traits` re-export them, which
left the crate with no outward edges and made this vendoring a copy rather than a
negotiation. Extraction is usually blocked by exactly one edge pointing the wrong
way, and the fix is usually to move the contract down rather than the consumer up.

What this changes for a reader: `README.md` and `docs/SAFETY.md` claim that
actuator bounds are enforced below the host, that every physical action and every
refusal lands in a hash-chained Ed25519-signed record, and that a privileged call
whose arguments echo untrusted content is refused. Until today all three claims
were documented here and implemented somewhere else. `cargo test -p obc-safety`
now runs 65 tests of that code in this repository, in CI, on every push. The
document arriving before its code is the wrong order, and this is the third and
last of the three where that had happened.

Not fixed by this, and worth stating in the same breath: node **pairing** is
vendored here as `pairing.rs` and is inert upstream — `pair_node` and `is_trusted`
have no callers, so the spine is still unauthenticated (see `docs/SPINE-AUTH.md`
and `docs/MIGRATION.md` §2.4). Vendoring the code does not wire it. What it does
is put the primitive and its 386 tested lines where the design document that
depends on them already lives.

---

## 2026-08-01 — `sync` skips what `check` already skips

`sync` refused to run at all against a clean upstream checkout. Seven artifacts —
five wasm build outputs and two firmware `Cargo.lock`s — are gitignored upstream,
so they are simply absent from a fresh clone, and `do_sync` aborted on the first
missing source. `check --upstream` had known about exactly these seven since
2026-07-30, by name and with a reason each; `sync` did not. The same knowledge,
encoded in one command and not its sibling.

It surfaced the way these things do: vendoring `obc-safety` — twelve files with
nothing to do with WASM — was blocked by a WASM bundle that was never going to be
there.

`sync` now skips them and **carries their manifest entries forward**, which is
the part that had to be right. The manifest is rebuilt from what a run copied, so
skipping without carrying would have silently dropped seven artifacts from the
gate — turning "cannot sync" into "no longer checked", which is strictly worse
than the abort it replaces. The recorded hash wins over re-hashing the file on
disk, so a hand-edited vendored copy still fails `check` instead of being
laundered into the manifest by the next sync. Skips print on every run, like
`check`'s do.

---

## 2026-07-30 — The peer check keeps a credential, because the alternative is trusting a mirror

The `peer` job checks the 11 artifacts the deployment generator mirrors. It went
red on PR #2 and stayed red, and the interesting part is how long it took to stop
looking for drift.

Everything measurable said the mirrors were identical: 56 artifacts passing
locally; passing against `git archive main` of the generator, which is
byte-for-byte what `actions/checkout` produces; no CR anywhere; the same hash for
`registry.json` across the OBC-Prime worktree, the generator worktree, and the
generator's committed blob; the 13 crate artifacts correctly carrying no peer
path. Every one of those checks was about the comparison. The failure was
upstream of the comparison — the checkout — and no amount of hashing reaches it.

**The generator repository is private.** That is now measured rather than
asserted: the job failed on the peer checkout, a fine-grained PAT with
`Contents: read` went in as `PEER_REPO_TOKEN`, and all four jobs went green. An
earlier version of this workflow asserted the opposite — "the generator is public
and needs no token" — with nothing having checked, and `PLAN.md` saying otherwise
in the same tree.

The decision was whether to keep the job at all. The case for deleting it is real:
when it was written the generator had no CI, and it does now — `ci.yml` runs the
same four planner-parity tests against the same goldens, including the widened
`wasm-planner.test.ts` that compares the whole config instead of asserting it
contains `[peripherals]`. So this leg is no longer the only guard, and it is a
guard that needs a credential with an expiry to function.

Kept anyway. The generator's own CI proves its planner agrees with the goldens
*it has*; this job proves the goldens it has are the ones this repository
published. Those are different claims, and the second one is the entire point of a
mirror. A vendored copy nobody compares is a copy that has already forked and has
not been told.

The cost is honest and written into the workflow: when the PAT expires this job
fails on checkout with "Repository not found", which reads exactly like drift and
is not. A drift failure names a file and two hashes. That sentence is in
`parity.yml` so the next person spends a minute rather than an afternoon.

### The transferable part

When a check that compares two things fails, the reflex is to interrogate the two
things. The comparison was never reached. Read the log before reproducing the
comparison — one line of it would have replaced an hour of hashing, and the hour
of hashing produced only evidence that everything it could see was fine.

---

## 2026-07-30 — Hashes prove identity; only execution proves correctness

The stale-build entry below fixed the *detection* of a bundle built from old
sources. Confirming that fix exposed the gap one level up: **nothing in this
repository ran the bundle.** Every gate here compares hashes, which answers "is
this the file we recorded" and cannot answer "is this the right file".

The assertion that would have caught the original bug lived in the generator's
vitest suite — a different repository, which has no CI at all, and which needs an
npm install to run. So the public project could not check its own headline claim
without a private sibling and a toolchain.

`parity/verify_wasm.cjs` closes that. It loads the vendored bundle, runs
`plan_deployment`, `deployment_toml` and `plan_site` against the vendored
fixtures, and compares the whole generated config byte for byte. It needs node
and nothing else — the bundle is a CommonJS `--target nodejs` build and the
fixtures are in this repo — so it runs as a CI job rather than as a thing someone
remembers to do. Verified in both directions: green on the current bundle, and
failing with a line-by-line diff against the pre-rebuild one recovered from
`git show HEAD:`.

The manifest also now records the **toolchain** that built the bundle (rustc,
wasm-pack, and wasm-bindgen from the lockfile). It is not a gate and does not
fail anything: a compiler bump legitimately rewrites the `.wasm` with no source
change, and the drift gate is right to stay green for it. It is there so that a
200 KB binary moving for no visible reason is a one-line diff rather than an
hour of archaeology. It populates on the next `--rebuild-wasm`; back-filling it
with a guessed rustc version would be a wrong number written down, which this
file already records two instances of.

One process note, worth more than the code. The stale bundle was first
"confirmed still broken" after the rebuild — against a cached copy of the *old*
file, in a scratch directory, while the correct new file sat on disk a few paths
away. The wrong conclusion was reached with real evidence, cleanly presented. The
fix was to stop testing copies: `verify_wasm.cjs` runs against the vendored path
in the repository, and the artifact under test is never staged, mirrored or moved
first. Verifying a copy verifies the copy.

---

## 2026-07-29 — A hash gate cannot see a stale build

The parity mechanism hashes every vendored artifact and fails on any change. It
had been verified by corrupting a file and watching it fail. It was still blind
to the largest divergence in the repository, and blind by construction: **a
compiled artifact cannot drift from its own hash.**

`wasm/obc-planner/` was built on 11 July. On 28 July `src/deployment/planner.rs`
was rewritten three times — "one canonical config, fixtured whole", "align role
assignment, and delete the mask", and the `claude-sonnet-5` pin — and
`expected-config.toml` was re-blessed with it. Every hash in `MANIFEST.json`
still matched. `check --upstream --peer` reported all 43 artifacts identical.
The bundle emitted a 79-line config where the golden had 119, carrying the old
system prompt and a hardcoded `[provider] name = "openai" / model = "gpt-4o"`.

The test that should have caught it was the narrow-gate failure this project has
already documented once. `planner-parity.test.ts` carries a long comment about
how a golden covering only `[deployment]` hid a real divergence for months, and
that comment sits above an assertion comparing the *whole* config byte for byte.
Twenty lines away, `wasm-planner.test.ts` checked
`expect(scheme.config_toml).toContain("[peripherals]")`. The lesson was written
down, applied to one leg, and not carried to the other. Writing down a lesson is
not the same as applying it everywhere it holds, and the second leg is exactly
where nobody looks.

Two changes, because the two failure modes are different:

- **The manifest now hashes the WASM's build inputs**, not only its output —
  the twelve upstream sources `planner-wasm` compiles via `#[path]`, declared as
  `WASM_SOURCES`. `check --upstream` fails if any has changed since the recorded
  build. This is the only way a hash gate can see the age of a build.
- **`wasm-planner.test.ts` compares the whole generated config** to the golden,
  matching the assertion on the TypeScript leg.

Both were verified by observing them fail: the missing-build-inputs branch
against the real manifest, and the stale-source branch by injecting a
pre-rewrite hash for `planner.rs` and confirming the error names that file.

Cost, and it is a real one: **the gate is red until the bundle is rebuilt.**
`wasm-pack build planner-wasm --target nodejs`, then `sync --upstream`. It is
red because the repository is in the state it describes, and a gate that goes
green on a known-stale artifact to spare the commit would be the original bug
with extra steps.

> **Resolved 2026-07-30.** Rebuilt and re-synced. All four legs green; the
> vendored bundle now renders the 119-line golden config, and `verify_wasm.cjs`
> confirms it by execution. Only `obc_planner_wasm_bg.wasm` changed
> (223,822 → 235,572 bytes) — the JS glue, `.d.ts` and `package.json` are
> byte-identical, so `wasm-bindgen` had not moved and there was no API drift. The
> goldens did **not** need re-blessing: the planner sources were always right, it
> was only the build that was old.
>
> Two things were found while confirming it, and both are now closed:
>
> 1. **`sync` could clear the gate without earning it.** Recording the current
>    source hashes next to a bundle it had merely copied would launder the exact
>    staleness the mechanism exists to catch. The `wasm_build` block is now
>    written *only* by `--rebuild-wasm`, in the run that invoked wasm-pack, and
>    carries `built_by_this_script: true`. A plain `sync` carries the previous
>    hashes forward untouched.
> 2. **`sync` never updated the generator's mirrors.** Only `check` knew about
>    `--peer`, so a rebuild would land here and leave the generator's copy behind
>    — and the error message said `fix with: sync`, which for that case was
>    false. `sync --peer` now exists.

Two smaller things fell out of the same pass. The documented regeneration
command said `--target web`; the bundle is `--target nodejs` and the test
`require()`s it, so following the printed hint produced a bundle that broke the
suite. And `parity/README.md` called this "three implementations" running one
"in a browser" — it is two implementations in three executables, and the browser
one is not built.

---

## 2026-07-28 — Retention is declared; everything else is a consequence of the world

Three mechanisms withdraw a belief because something changed: a newer value
arrived, its author stopped reporting, or something it rested on went away.
Retention is the fourth, and the only one that fires because a human wrote a
rule. That asymmetry drives its whole design.

An agent's own note is unreachable by the other three — nothing rewrites
`incident.<subject>`, the agent does not stop existing, and an assertion rests on
nothing recorded. Six such notes were still believed ten days after the
investigation that produced them concluded. So the mechanism has to exist.

But its blast radius is a string someone typed, so it only ever does what it is
told: nothing expires by default, an empty prefix is rejected rather than treated
as "everything", malformed policies are reported at `ERROR` rather than skipped,
`source.*` can never be expired, and `due()` is a dry run.

Age comes from `ingested_at`, not `valid_from` — the latter is a caller-supplied
tool parameter, so postdating a claim would otherwise buy it immortality.

On a shared namespace the origin filter is the entire safeguard: `mesh.` holds
the radio's evidence alongside the agent's notes, and `origins = ["asserted"]` is
what keeps a retention rule from ageing out the mesh itself.

---

## 2026-07-28 — Debounce is a rate limit, not a novelty test

A reflex asked "has enough time passed since I last fired?". For a condition that
stays true, the answer is eventually always yes, so a rule watching a standing
state re-fires forever at the debounce interval. In practice the vision rules
escalated to a 30B reasoner every hour, indefinitely, on images from 6 July,
because "a verified person was detected" never stopped being true.

Snapshots now carry the **row id** of each fact, not just its value, and a rule
may require those ids to differ from the ids at its last fire. Two ticks reading
the same row are the same observation; two ticks reading different rows with equal
values are not.

Opt-in, and it must stay that way. A safing rule *should* keep firing while a
dangerous state holds — "the battery is still critical" is worth repeating, and
suppressing it because the reading has not changed is exactly backwards. Only the
vision rules opt in.

A snapshot with no ids never suppresses: value-only snapshots (a node, a
simulation) cannot speak to evidence identity, and missing identity is not
evidence of sameness.

Cost: the wire format grows a field, defaulted for compatibility, and rule state
grows a second map.

---

## 2026-07-28 — Restating a belief is not new evidence

Applied at both write boundaries, for the same reason and with very different
volumes.

Every write supersedes: it closes the open row and appends a new one with a fresh
timestamp. So a writer that reads a fact and writes it back makes a stale belief
look freshly confirmed — and if that writer is the agent, by an agent that learned
it from that same belief. It also defeats source liveness directly, since an echo
lands under `agent`, and a silent source the agent keeps restating never looks
silent.

The agent's `world_memory` tool now refuses a no-op restatement, and says what is
already there rather than returning an error to work around.

The same rule at the perception boundary is where the volume was: the ClawCam
poll re-read its source every 60 s and recorded everything it saw, turning 50
distinct events into 9,600 rows and a deer count of 5,418 from 28 real detections.
Ingest is idempotent on event id; dedup is per entity, not global, since one event
yielding two subjects is two beliefs; a detection with no event id is written
through, because duplicates are recoverable and missing detections are not.

Counters were an accumulator, so the error compounded rather than washing out and
had to be repaired by a recount from distinct events. Corrected, not deleted — the
inflated values remain in `history()`.

---

## 2026-07-28 — Unknown support and no support are different states

`world_facts.derived_from` records the facts a derived belief was computed from
— Doyle's JTMS in-list. It has three states, and the first two are deliberately
not merged:

- `NULL` — unknown support. Every row written before the column existed, and
  every caller that has not been taught to declare its inputs.
- `[]` — explicitly self-standing. A premise.
- `[ids…]` — rests on these.

The reason the distinction is load-bearing: `observe()` already defaults to
`Origin::Derived` as its fail-closed default, so most rows are typed `Derived`
without anyone having thought about where they came from. If an invalidation
sweep read `NULL` as "nothing supports this", its first run would retract the
entire store.

The column is **not backfilled**. `origin` was, partially, from source labels —
support cannot be, because a wrong in-list is worse than an absent one: the
absent one is inert, the wrong one gets walked. `dependents()` therefore cannot
see unknown-support rows at all, so sweeps under-retract rather than
over-retract. A corrupted in-list parses back to `NULL`, never to `[]`, since
`[]` is the stronger claim.

`dependents()` is deliberately not transitive. A belief with several supports
may survive one of them dying (`a+b`) or may not (`a·b`); making the query
transitive would decide that for every caller.

Cost: the graph is only as good as its coverage, which starts near zero and
grows one write site at a time. `support_coverage()` reports the gap so it
cannot be quietly ignored.

---

## 2026-07-28 — The name is Open Body Control

Keeps the `OBC` acronym, which is already the binary name, the config directory
and a decade of muscle memory in aerospace and robotics where it means
*On-Board Computer*. That existing meaning is inherited rather than fought.

"Open ..." positions this as a layer to build against rather than a product to
buy — the model is Open Sound Control. "Body" is the honest word: this is not a
chatbot with plugins, it is an agent with nodes, sensors and actuators.

The vocabulary that follows — brain, body, senses, reflexes, escalation — is
already the vocabulary of the code (`obc-brain`, the reflex controller, the
System 1 / System 2 split), so the naming and the architecture agree.

Rejected: *Onboard Control* (safer, less distinctive), *Open Brain & Claw*
(preserves heritage, doesn't explain itself), *Open Bot Core* ("bot" invites
exactly the chatbot association the project is trying to avoid).

---

## 2026-07-28 — A clean public repo, with the core agent as upstream

Rather than renaming the existing private repo, or building a monorepo of all
four projects.

The private repo carries a long changelog and a number of subsystems
that are declared, documented, and not wired up. A rename would make all of
that the public first impression. A four-way monorepo would additionally drag
in a codebase whose own headline CLI is broken.

The clean repo lets each piece move over when it is defensible, which is also
the order in which its documentation can be written honestly.

Cost: vendored artifacts must be kept in sync across repo boundaries. That cost
is paid by `scripts/sync_upstream.py` and the parity CI gate — see below.

---

## 2026-07-28 — Parity is enforced by hash, not by convention

The board registry, the golden fixtures and the planner WASM bundle exist in
three repositories. They were previously kept in step by hand-copying, with no
sync step and no verification. The only thing that caught a stale copy was a
test failing afterwards, in a different repository, for a reason that looked
unrelated.

Now: one declarative list of vendored artifacts, a manifest of SHA-256 hashes,
and a check that fails on any divergence — from the manifest, from upstream, or
from the generator app's mirrors.

The gate was verified by deliberately corrupting a vendored file and confirming
a non-zero exit with an actionable message, then restoring it. A gate that has
never been observed failing is not known to work.

> **Corrected 2026-07-29.** This said "a CI job that fails on any divergence".
> The *script* checks all three; **CI runs only the first**. `parity.yml` invokes
> a bare `check`, and the `--upstream` job is commented out. There has never been
> a `--peer` job at all. So on any given push, a hand-edit to a vendored file is
> caught and drift against the core agent is not — which is the more likely
> failure of the two, because the core agent is where the work happens. The
> capability was described as if the wiring existed. See §"A hash gate cannot see
> a stale build" for the second, worse gap in the same mechanism.

Deliberate limitation: a bare `check` can only prove nobody hand-edited a
vendored file. It cannot prove the manifest itself is current — that needs
`--upstream`. The tool says so in its output rather than implying a stronger
guarantee than it verified.

---

## 2026-07-28 — Reference Bodies ship with seeded data

A Reference Body is a complete deployment — config, firmware, and a database
with real recorded history — that runs before any hardware exists.

The reasoning is about the first two minutes. A newcomer who can clone, start
the agent, and watch a reflex fire on a real detection understands the System 1
/ System 2 split immediately. The same person reading a description of it does
not. Seeded data converts documentation into evidence.

It also makes the bodies genuinely reusable: Trailwatch becomes a security
perimeter or a livestock monitor by changing `alert_subjects`, with no code
change. The reflex rules and escalation playbooks are the transferable part,
and they are only legible when you can watch them run.

---

## 2026-07-28 — Delete the subsystems that were never wired, and stop hiding them

Release gate 3. `src/lib.rs` opened with
`#![allow(dead_code, unused_imports, unused_variables)]`. That one line is why
the curation problem existed at all: the islands were not a historical accident,
they were invisible **by configuration**. Nothing ever warned.

Removed: `dashboard`, `rag`, `satcom`, `hooks`, and `memory/personality.rs`,
plus the `[personality]` config section that outlived the store it configured —
2,036 lines that parsed, documented themselves, and did nothing. A config key
that loads cleanly and has no effect is worse than a missing feature, because
the config file is the surface a user actually reads. (Safe on upgrade: the root
`Config` does not `deny_unknown_fields`, so a leftover `[personality]` block is
ignored rather than becoming a parse error.)

**Kept, against the survey's advice: `a2a`.** The first pass cut it too. Then
`tests/evals.rs` — the release-gate eval file — failed to compile with thirteen
unresolved references. The survey only scanned `src/`. Integration tests are a
whole category of consumer it never looked at, which is a good argument for not
trusting a reference count you did not write the scanner for. `scripts/curation_survey.py`
now scans `tests/`, `examples/` and `benches/` too.

The blanket allow is gone and must not return. Suppression is now narrow, at the
item or file, with a stated reason: the chat-platform modules carry a scoped
`#![allow(dead_code)]` because their structs mirror a vendor's webhook payload
and deleting unread fields would make them a worse description of the wire.

What the lint found once it could speak: a mission could trip a guard, halt
navigation and end without a single log line saying why. The reason was going
into world memory but never to the operator's terminal. That is now logged.

Warnings went 0 (suppressed) → 32 → **4**, and all four are honest: a field or
method that is declared and genuinely not used yet. A short list of real
warnings is worth more than a clean build that means nothing.

---

## 2026-07-28 — Two repos, one statement of which is which

Release gate 4. Both repos were MIT and both had a LICENSE. What neither had
was a sentence saying which repo a change belongs in — so a stranger looking at
Oh-Ben-Claw could not tell it was the upstream core of this one, or that
`registry.json`, the golden fixtures and the planner WASM are emitted there and
vendored here by hash.

Both now open their CONTRIBUTING with the same routing table, and both READMEs
link to it. The vendored artifacts get an explicit licence sentence: they
originate upstream, same author, same terms.

The larger finding was in the four commands the upstream CONTRIBUTING had
always told contributors to run before opening a PR. Two of them had never
passed on a clean checkout: `clippy -- -D warnings` (the gate-3 warnings plus
an unexpected-cfg in the WASM crate) and `cargo fmt --all --check` (736 diff
hunks across 81 files, because it had never been run). CI ran both, so CI had
been failing too.

A check that fails on a clean checkout teaches everyone who meets it to ignore
that check, which then costs nothing to keep failing. That is the same failure
mode as the crate-wide `allow` removed in gate 3, in a different medium — and
it is why the fix was to make the commands pass rather than to soften them.
`-D warnings` stays, and `--all-targets` was *added*, because the survey that
skipped `tests/` is precisely how a live module nearly got deleted.

Cost, stated: the first `cargo fmt --all` is a 4,796-line mechanical commit
sitting on top of every `git blame`. Mitigated with `.git-blame-ignore-revs`
and one line of setup in CONTRIBUTING, not eliminated. Rustfmt defaults were
kept rather than tuning `max_width` until the diff got small, which would have
been tailoring the standard to the mess.

---

## 2026-07-28 — One data root, resolved once, movable by one variable

Release gate 5. The gateway turned out to be fine — host and port are config,
so "one per machine" was never welded in. The data was the problem, and it was
worse than a single-user assumption: there were two conventions running at the
same time.

Half the state used the platform data directory. The other half — approval
grants, harness records, the skill-evolution log, the install audit, the rollout
record, the gateway's staging directory — hardcoded `$HOME/.oh-ben-claw` by
reading `HOME`/`USERPROFILE` directly. The documentation named `~/.oh-ben-claw`
throughout, describing neither arrangement on Windows.

Consequence: a user's data was split across two directories, the docs named a
third, and nothing could move any of it. `OBC_CONFIG` relocated the config file;
there was no equivalent for data. Two agents on one machine shared one database,
one audit chain and one set of standing permission-to-act grants.

Now: `OBC_DATA_DIR` → `[paths].data_dir` → platform convention, resolved in one
module, twelve call sites through it. The platform convention rather than a home
dotdir, because `~/.oh-ben-claw` is a Linux habit that is wrong on the other two
platforms this project runs on.

The config search gains `config.toml` in the data root, above the platform
directory, which is what makes a relocated instance self-contained. The
environment beats the config key deliberately: a config file gets checked in and
copied between machines, and starting a second instance should not require
editing one the first instance reads.

**This is not multi-tenancy and is not claimed as such.** It removes the
single-tenant assumption from a dozen call sites so that a hosted deployment
needing per-tenant isolation changes a resolver instead of excavating. That was
the whole ask: don't foreclose it.

Verified by running two instances side by side, not by reading the code — one
relocated with its own config, database and agent name, the other untouched on
the platform default. `doctor` now prints the resolved root and which of the
three sources chose it.

Also found: the upstream README documented a `setup` wizard and a `service`
manager, neither of which has ever existed, and the install instructions told a
new user to run `oh-ben-claw setup` first. Corrected against `--help` output.
Gate 2 removed the need for a wizard anyway — a provider key in the environment
and no config file is a working first run.

---

## 2026-07-28 — The operate token belongs in the keychain, and arming is an act

The deployment generator's fleet console held the gateway's **operate token** in
`AsyncStorage` — a plaintext file in the app sandbox. That token is not a login:
presenting it on a mutating request lets the holder drive physical hardware
through a running gateway.

What made it clearly a bug rather than a judgement call was the asymmetry inside
the same app. `lib/_core/auth.ts` already used `SecureStore` for the session
token. The token that actuates a robot did not.

Three decisions in the fix:

- **The migration deletes the plaintext copy.** Moving the token into the
  keychain and leaving the old file behind fixes nothing and fails silently:
  everything keeps working, and the file everyone was worried about is still
  there. The test for this was watched failing against a version with the delete
  removed — a gate never observed failing is not known to work.
- **Web keeps it in memory only.** `SecureStore` has no web implementation and
  `localStorage` is no better than what is being replaced. So on web it survives
  only as long as the tab, and the UI says so rather than implying a protection
  that is not there.
- **Arming is no longer automatic.** The saved token is offered back into the
  input so nobody retypes a secret, but the console does not come up ARMED
  because it was ARMED yesterday. Elevation to physical control should be
  something you did, not a state you woke up in.

The console also now says when the gateway URL is plain `http`, because storing
a secret safely and then putting it on the wire in cleartext is a strange place
to stop. Not blocked — a trusted LAN is a legitimate deployment — just said.

---

## 2026-07-28 — Firmware is vendored, not moved

The plan said *move* the two Rust firmware crates here. Checking before cutting —
the habit the `a2a` near-miss bought — showed that moving would have deleted the
only tests that firmware actually runs.

`heltec-lora-linktest` builds for `xtensa-esp32s3-espidf`, so `cargo test` inside it
compiles its tests for the microcontroller and cannot execute them. Upstream,
`tests/firmware_spine_framing.rs` `#[path]`-includes `src/spine.rs` and compiles it
for the host, which is what puts the frame codec, the relay de-dup ring and the line
framer under ordinary `cargo test`. That harness exists because of a real incident:
the bridge transmitted two mid-string fragments after the host wrote two commands
back to back.

So the firmware joins the registry, the fixtures and the planner WASM as a vendored,
hash-checked artifact. Cost: contributors edit upstream and re-sync, same as the
others. Benefit: the flashing guide and the sources it describes cannot drift.

All four firmwares came over, not the two the plan named. Two are Arduino sketches,
which is the only entry point for the reader who has a board and no Rust toolchain —
and the first user this project is written for is someone with an ESP32 in a drawer.

### The thing that fell out of it

Vendoring 32 more text files made a latent bug impossible to ignore: **this
repository has never passed its own drift gate on a fresh Windows clone.** The
Windows Git installer sets `core.autocrlf=true` and there was no `.gitattributes`,
so cloning rewrote every text artifact to CRLF and every SHA-256 changed. The gate
then reported the three planner implementations as disagreeing when nothing had
diverged at all — on the one claim the README leads with, from the first commit.

Confirmed by cloning to a temporary directory and watching `check` fail on all 42
artifacts, `registry.json` included, then pass after `* text=auto eol=lf` — the same
`.gitattributes` the core agent already had, which is exactly why upstream never hit
this and this repo did.

---

## 2026-07-28 — Benchtop ships without hardware verification, and says which half

Trailwatch runs with nothing plugged in because it carries 14 days of real
recorded detections. Benchtop cannot: its whole point is the live path, and a
fabricated sensor history would be teaching a reader to trust numbers nobody
measured — the failure the bodies README already warns about.

The alternative to shipping it dishonestly was not shipping it, and that was
worse: the body existed as an inventory in the generator with no runtime half,
so the two places a Reference Body is supposed to live disagreed.

So it ships with a verification table at the top. Verified: the config parses and
the agent starts from it (`doctor` reports 0 errors, 2 reflex rules); the
`[deployment]` block is planner-emitted rather than hand-written; the hardware
resolves with zero capability gaps. Not verified: a BME280 actually firing the
reflex, and the Track 0 limit refusing a command on a physical node. **A
reference body you cannot fully run is worth shipping if it is honest about which
half you are getting.**

### Two findings from generating it rather than writing it

**The generator's emitted config had two dead keys and no brain.** `[agent] model
= "grok-4"` — `model` is not an `[agent]` key — and `max_iterations`, which is
spelled `max_tool_iterations`. Unknown keys are not rejected, so both parsed and
did nothing, in the first config a stranger ever receives. No `[provider]` block
at all. The Rust planner emits the correct schema, so this was TypeScript-only
drift that the parity gate never saw, because the fixtures cover the
`[deployment]` block and the site plan — **not** the config preview. The
byte-identical claim is true of what is fixtured and was not true of the section
a user pastes. `parity/README.md` now says so; widening the fixture is open work.

**An absent `[provider]` is not a stated one.** Gate 2 said an explicit config is
never second-guessed. Right about the file, wrong about a section it does not
contain: `serde`'s default supplied `openai/gpt-4o`, so a body that deliberately
left the brain unspecified greeted an Anthropic-key holder with "No API key found
for provider 'openai'". Resolution now fills an unnamed provider from the
environment. The test keys on `provider.name`, not on the `[provider]` table —
found by running the body, whose `[provider.retry]` block creates that table
without choosing a vendor and so silently opted itself back out.

---

## 2026-07-28 — A narrowed gate needs an expiry condition

The parity fixtures covered the `[deployment]` block and the site plan. The claim
they backed was "three implementations produce byte-identical output" — true of
what was fixtured, false of everything else, and everything else is the part a
user pastes into their config file.

Widening the golden to the whole generated config exposed two layers of
divergence, and the way each was handled is the decision worth recording.

**Layer one: the emitters had drifted into different sections.** Rust emitted
`[edge]` and a hardcoded `[provider]`; the TypeScript port emitted
`[fleet.lora_serial]`, `[memory]` and a different `[agent]`. Neither was a superset
of the other. Merged to one canonical output with **the agent's own config schema
as arbiter** — not a style call, because the root `Config` does not reject unknown
keys, so a key outside the schema parses cleanly and does nothing. Three had
accumulated that way, all in the first config a new user reads.

**Layer two: the planners disagreed about what the deployment does.** Given the
same hardware they assigned different tool sets. That could not be fixed in the
same change, and the tempting move — widen the fixture to exclude it — is exactly
what caused the original problem.

So the mask shipped with an **expiry assertion**: a test asserting the divergence
was *still present*, which fails the moment the mask stops being necessary. It
fired on the next change. The mask is gone and the comparison is now byte-for-byte
with nothing excluded.

**A gate narrowed to accommodate a known problem becomes permanent unless
something fails when the problem goes away.** That is the transferable part.

The alignment itself used the **tool registry** as arbiter, and found invented
names: the orchestrator was being handed `file_read`, `file_write`, `http_get` and
`memory_note` (the real tools are `file`, `http`, `memory`), while the TypeScript
orchestrator lacked the four delegation tools that are the reason an orchestrator
exists. It also surfaced a real bug the port had already fixed and the core had
not: `audio_sample` is the *microphone* capability, so testing it for "has a
speaker" described a listen-only board as playing synthesised speech through a
speaker it does not have.

---

## 2026-07-29 — CI was red, and only on the platform nobody was building on

Three CI jobs were failing. All three were invisible locally, because the author
develops on Windows and CI runs `ubuntu-latest`. Reproduced by exporting the tree
into a Linux container and running the CI steps verbatim rather than reading the
YAML.

**The wasm crate could never have compiled on Linux.** `#[path]` inside an
*inline* `mod peripherals { … }` block resolves against a directory named after
the module — which did not exist. Windows normalises the `..` components lexically
before touching the filesystem, so it resolved anyway. Linux requires every
component of a path to exist. The first step of build-and-test therefore failed on
every push.

That is the worst shape a build failure can have: **green for the only person who
can fix it.** Fixed by making the shim directories real.

**Four security advisories, for a feature that does not exist.** `rustls-webpki
0.102.8` carries four RUSTSEC advisories in certificate and CRL handling, arriving
solely through `rumqttc`'s `use-rustls` feature, with no upgrade path — rumqttc
0.25.1 pins the same version.

It was also unreachable: `src/spine/mod.rs` never calls `set_transport`, so
MQTT-over-TLS has never worked. The project was shipping a vulnerable
certificate-validation stack for a capability it does not have. Dropping the
feature removes the advisories rather than suppressing them.

Which forced the honest half: **`[spine] tls = true` now refuses to start.** Every
other dead config key in this codebase merely did nothing. This one told an
operator their broker link was encrypted when it was cleartext — and three tests
asserted the reassuring warnings it produced, which is how the missing feature
stayed hidden. A warning would not be enough; someone who set that key made a
security decision and is entitled to learn it did not take effect.

### The transferable part

A green local build is not evidence about CI when the two run different operating
systems, and neither is reading the workflow file. The cheap version of this check
is to run the CI steps on the CI platform once, which took one export and a
container.

Stated as not-verified: the aarch64 cross-compile job could not be reproduced —
`static.rust-lang.org` is unreachable from the sandbox, so the target's std would
not install. It runs on Linux and would have hit the same `#[path]` failure at step
one, so it is *probably* fixed by the same change. Probably is the honest word.
