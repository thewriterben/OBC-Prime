# Decisions

Short records of choices that are expensive to reverse, and why they were made.
New entries go at the top.

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

The private repo carries a 115,000-line changelog and a number of subsystems
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
