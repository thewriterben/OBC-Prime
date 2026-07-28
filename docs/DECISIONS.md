# Decisions

Short records of choices that are expensive to reverse, and why they were made.
New entries go at the top.

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
and a CI job that fails on any divergence — from the manifest, from upstream,
or from the generator app's mirrors.

The gate was verified by deliberately corrupting a vendored file and confirming
a non-zero exit with an actionable message, then restoring it. A gate that has
never been observed failing is not known to work.

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
