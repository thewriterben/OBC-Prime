# Belief revision: four ways to stop believing something

What shipped in OBC between 27 and 28 July 2026, why each piece exists, and what
it measured on a live store. Companion to `MEMORY-2026-07.md`, which surveyed the
field and named the gap; this is the engineering account of closing it.

---

## The shape of the problem

A store of beliefs needs a way to stop holding one. Production LLM memory systems
implement exactly one: a newer value replaces an older value for the same key.
That is enough when every belief is a fact about a conversation, which is the
setting those systems were built for.

It is not enough for an agent with sensors. OBC's bench store accumulated, over
ten days, a set of beliefs that no supersession could ever reach — and each of
them was unreachable for a *different* reason. That is the finding, and it is why
there are four mechanisms rather than one general one.

| Belief | Why supersession never fires |
|---|---|
| `mesh.escalated_count = 2` | The supervisor that wrote it was switched off. Nothing recomputes it. |
| `mesh.escalation_status.health` | Derived from a phantom node that the discovery fix removed from view. The code path that would clear it was deleted along with the bug. |
| `incident.mesh-node-lost` | An agent's note. Nothing ever writes that entity again. |
| `notify.trail_activity` | Derived from a camera reading that has since been replaced by a newer reading. |

Four beliefs, four reasons, four mechanisms:

| Mechanism | Fires when | Eager or lazy | Marked as |
|---|---|---|---|
| **Supersession** | a newer value arrives for the same entity | eager | (unmarked) |
| **Source liveness** | the author stops reporting | eager, at boot | `source-stopped:<source>` |
| **Dependency withdrawal** | something it rests on is no longer believed | eager, transitive | `unsupported:<source>` |
| **Retention** | a declared policy says beliefs of this kind go stale | eager, at boot | `expired:<prefix>` |

Plus one query, because the fifth case must not be a sweep — see §4.

Every one of them **closes** the valid-time interval rather than deleting the row.
`history()` and `at()` still answer what was believed and when; only `current()`
stops returning it. A withdrawal is undercutting, not rebutting (Pollock): it says
*we no longer have grounds for this*, and asserts nothing about whether it is true.
Writing `0` for a retracted count would have been a lie with the same shape as the
original bug.

---

## 1. The support graph

`world_facts.derived_from` is a JSON array of row ids — Doyle's JTMS **in-list**.
Three states, and the difference between the first two is the whole design:

- `NULL` — **unknown support.** Nothing was recorded. Inert to every sweep.
- `[]` — **explicitly self-standing.** A premise. Nothing upstream can undercut it.
- `[ids…]` — **rests on these.**

The distinction is load-bearing because `observe()` already defaults to
`Origin::Derived` as its fail-closed default, so most of the store is typed
"derived" without anyone having thought about provenance. **A sweep that read
`NULL` as "nothing supports this" would retract the entire store on its first
run.**

The column is **not backfilled**. `origin` partly was, from source labels; support
cannot be, because a wrong in-list is worse than an absent one — the absent one is
inert, the wrong one gets walked. A corrupted in-list parses back to `NULL`, never
to `[]`, since `[]` is the stronger claim.

Where an in-list is recorded today: the mesh supervisor's full chain, pose fusion's
inputs, and the escalation log of record (as `[]` — see §6).

---

## 2. Source liveness

Prometheus 2.0 settled the shape of this in 2017 after its own version of the bug:
alerts kept firing on targets that had vanished, because a lookback window cannot
tell *gone* from *quiet*. Its fix was a **staleness marker**, and the transferable
principle is:

> Absence of data is itself a datum, and must be written — distinguishable from
> "not yet arrived" and from "reported false".

So a source that stops gets a fact of its own at `source.<name>.liveness`,
recording state, reason, and when it last spoke. `Retired` (configured off,
deterministic) is kept distinct from `Silent` (inferred from silence, and
therefore capable of being wrong about a slow source). **Only the deterministic
half runs at boot** — at startup a source that has not spoken *yet* is
indistinguishable from one that died.

The liveness namespace can never itself be swept or expired. Bookkeeping about
withdrawal cannot be subject to withdrawal, or the next boot re-retires an
already-clean source.

---

## 3. Dependency withdrawal

A belief that loses its justification is no longer a justification itself, so the
walk is transitive — breadth-first to a fixpoint, with a seen-set. The set is not
paranoia: `derived_from` is not schema-constrained to be acyclic, and a cycle must
not become an infinite loop in a startup path.

The mesh chain is three deep, which is what makes one-hop propagation a
half-measure:

```
mesh.<node>              (lora-gateway, observed off the air)
  └─ mesh.<node>.health          (supervisor concluded)
       ├─ mesh.<node>.escalation
       │    └─ mesh.escalated_count
       └─ mesh.<node>.recovery
```

Retiring the radio with one-hop propagation would close the rollups, mark health
unsupported, and leave the escalations and the count standing — the original bug,
one level down.

An in-list is **conjunctive**: every entry must hold. Independent corroboration
(`a+b`, where a belief survives one support dying) needs a fact to carry several
*alternative* in-lists, and the schema holds one. That limit **over**-retracts,
unlike every other choice here, which is why the blast radius matters: facts with
unknown support are invisible to the walk by construction, so only beliefs that
explicitly declared what they rest on can be touched at all.

---

## 4. Supersession of a support is answered lazily, not swept

This is the design decision the tests forced, and it is the one worth arguing
about.

A justification fails for two reasons. Its author can stop reporting — rare,
discrete, handled eagerly above. Or a supporting fact can simply be **superseded**
by a newer value, which happens on every sensor tick.

Propagating eagerly through supersession is the pure JTMS reading and it is
unworkable: every reading a fused pose was computed from is replaced seconds
later, so the pose would be retracted and immediately recomputed, forever, filling
the store with churn that says nothing.

So supersession is evaluated **at read time**. `support_status()` asks whether a
belief's justification stands *now* and names the facts that moved;
`ungrounded()` lists open beliefs still being served by `current()` whose grounds
have shifted underneath them. `Unknown` support is explicitly not a failure —
absence of a recorded in-list is absence of evidence.

This is the **STALE Type II** shape: a belief invalidated by something *underneath*
it moving rather than by contradiction. The honest claim is that OBC can now
**answer** that question, not that it eagerly acts on it.

---

## 5. Retention

The fourth mechanism, and the only one that comes from a rule rather than from the
world. Supersession needs a newer value for the same entity; liveness needs the
author to stop existing; dependency withdrawal needs a recorded in-list. An
agent's own note at `incident.<subject>` has none of the three.

That makes it the most dangerous of the four — a wrong prefix retracts beliefs
that were perfectly good — so it only ever does what it is told:

- **Nothing expires by default.** An empty policy list is inert.
- **An empty prefix is rejected**, not treated as "everything". The failure mode of
  that typo is the entire store.
- Malformed policies are reported at `ERROR`, never silently skipped. A retention
  rule that quietly does nothing is how you find out a year later that nothing
  expired.
- `due()` is a dry run, because the first thing to do with a new rule is find out
  what it eats.

Age is measured from `ingested_at`, **not** `valid_from`. `valid_from` is a
caller-supplied tool parameter, so postdating a claim would otherwise buy it
immortality.

The **origin filter** is what makes a prefix safe on a shared namespace. `mesh.`
holds the radio's evidence and the supervisor's rollups alongside the agent's
notes; `origins = ["asserted"]` is the entire safeguard.

---

## 6. Where the mechanism does not fit

Two cases are recorded as decisions in the code rather than handled by machinery.

**A log of record is self-standing.** The escalation log is written with an *empty*
in-list — a claim, not an absence. It says an event happened, and that stays true
even when the belief that triggered it is withdrawn. Retracting it because its
cause was retracted would be falsifying history, which is the one thing a log of
record exists to prevent. Contrast `mesh.escalated_count`, a claim about the
*present*, which must fall when its grounds do. Same subsystem, opposite treatment.

**An accumulator has no usable in-list.** `vision.count.<subject>` is a running
total whose real support is every detection that ever incremented it — 5,418 of
them on the bench store. The honest encodings are an unusable list or a chain 5,418
links deep, walked one query per link in a boot path. Recording `[prev]` alone
would be *worse than nothing*: it looks like support while carrying almost none of
the dependency. The counter records unknown support, which is true.

---

## 7. The same idea outside memory

Row identity turned out to matter somewhere unrelated.

The reflex engine debounced by time: *has enough time passed since this rule last
fired?* For a condition that stays true, the answer is eventually always yes — so a
rule watching a standing state re-fires forever at the debounce interval. In
practice, the vision rules escalated to a 30B reasoner **every hour, indefinitely,
on images from 6 July**, because "a verified person was detected" never stopped
being true.

Debounce is a rate limit, not a novelty test. The fix is the same primitive: the
snapshot now carries the **row id** of each fact it read, and a rule may require
those ids to differ from the ids at its last fire. Two ticks reading the same row
are the same observation.

Opt-in, and it must stay that way: a safing rule *should* keep firing while a
dangerous state holds. "The battery is still critical" is worth repeating, and
suppressing it because the reading has not changed is exactly backwards.

The same principle at the perception boundary: a poll re-reads its source, so
recording what comes back is not new evidence. Ingest is now idempotent on event
id.

---

## 8. Measured

Against the live bench store, ~23,000 rows.

**Retraction on boot.** The mesh supervisor, configured off, had left ten beliefs
standing including the count a reflex had been firing on and four rows derived from
the 17 July phantom node. All ten withdrawn at startup, tagged, none deleted.
`mesh-node-lost` appears **2,376 times** in the log before that boot and **0**
after.

**The chain, end to end.** After the supervisor rebuilt its facts with in-lists,
retiring the *radio* closed 6 of its own facts and withdrew **5** more — two
health, two escalation, one count. Three levels, from a source going away, none of
them written by the source that died.

**Retention.** Three ten-day-old agent notes expired; three others in scope stayed,
being hours old. The dry run, run at wall-clock, agreed exactly.

**The support-graph index.** `dependents()` was a full table scan per walk step.
It cannot index the `json_each` membership test, but it never needs to look at rows
with no in-list. A partial index plus the matching predicate, over 200 walk steps:

| | total | per step |
|---|---|---|
| naive | 680.0 ms | 3.400 ms |
| guarded, no index | 504.9 ms | 2.525 ms |
| guarded + partial index | **0.6 ms** | **0.003 ms** |

A sweep walks once per frontier fact, at startup, before the gateway binds. The
cost was invisible only because coverage was near zero.

**Ingest idempotence.** 50 distinct detection events had been written **9,600
times** — the poll re-reading its source every 60 s. Counters corrected from
distinct events: deer 5,418 → 28, fox 2,318 → 11, coyote 1,161 → 6, person 778 → 5.
Zero detection rows written since.

---

## 9. What the roadmap got wrong

Worth recording, because the ordering in `MEMORY-2026-07.md` was confident and
partly mistaken.

**The in-list did not fix the bug it was designed for.** After liveness shipped,
support coverage in the live store was **0 of 20,431**. The graph existed and was
empty. `mesh.escalated_count` was reachable by source bookkeeping alone, because
the supervisor wrote the count under its own source label — no dependency edge was
consulted.

The in-list earns its keep across a **source boundary**: a conclusion whose author
is alive and whose *grounds* are gone. Teaching the supervisor to declare its
inputs produced that case for the first time.

**Coverage is the binding constraint, not mechanism.** Everything downstream —
propagation, admission policy, evaluation — is bounded by how many write sites
declare their inputs. That number is three.

**A dry run whose clock is not the real clock is not a dry run.** The first expiry
preview passed a far-future timestamp "so age is not the variable under test",
which turned *what expires now* into *what would eventually expire*. It reported
six facts; the real sweep took three.

---

## 10. Honest limits

- **`a·b` only.** Alternative justifications need several in-lists per fact.
- **Coverage is three producers**, out of roughly fifty write sites.
- **No STALE evaluation yet.** `support_status()` answers the Type II question;
  nothing has scored it against the published set, and no number should be claimed
  until something has.
- **Retention cannot reach an unnamed namespace.** A policy is a claim about a
  prefix, and beliefs outside every prefix age forever.
- **The reflex change is one hour old at time of writing.** The claim that hourly
  re-firing stops is structural, not yet observed over a full cycle.

---

## Sources

[Doyle, TMS 1979](https://www.sciencedirect.com/science/article/abs/pii/0004370279900080) ·
[SEP defeasible reasoning](https://plato.stanford.edu/entries/reasoning-defeasible/) ·
[Provenance semirings, PODS 2007](https://web.cs.ucdavis.edu/~green/papers/pods07.pdf) ·
[Prometheus staleness](https://promcon.io/2017-munich/slides/staleness-in-prometheus-2-0.pdf) ·
[watermarks, VLDB 2021](http://www.vldb.org/pvldb/vol14/p3135-begoli.pdf) ·
[STALE](https://arxiv.org/html/2605.06527v1) ·
[When Not to Write Memory](https://arxiv.org/html/2607.02579)
