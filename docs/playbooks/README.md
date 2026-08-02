# Triage playbooks

Three documents, one per family of escalation the reflex layer can raise. They
are **not** background reading. Each one is the long form of a triage directive
that arrives attached to a wake, at the moment someone has to decide what to do
about it.

| Playbook | Raised by |
|---|---|
| [vision-analytics.md](vision-analytics.md) | A camera-analytics reflex: an unusually quiet day, an unusually busy one, or a model whose confidence stopped agreeing with human review |
| [mesh-node-lost.md](mesh-node-lost.md) | A mesh node that has stopped reporting |
| [safing-escalations.md](safing-escalations.md) | A Track 0 safing rule — the layer [`../SAFETY.md`](../SAFETY.md) describes |

You will meet the first one within two seconds of running the Trailwatch
quickstart in [`../../bodies/trailwatch/`](../../bodies/trailwatch/README.md).
The seeded model there is deliberately miscalibrated, so `vision-calibration-drift`
fires on a first-ever run and the escalation it attaches ends:

    Full playbook: docs/playbooks/vision-analytics.md

## These files are vendored

They are byte-identical copies of `docs/playbooks/` in the core agent repo,
carried here under the same hash gate as `firmware/` and `crates/`:

```bash
python scripts/sync_upstream.py check --upstream ../Oh-Ben-Claw
```

Do not edit them here. A local fix would pass `check` — which compares each file
to its own recorded hash — right up until someone ran `check --upstream`, and
would be silently overwritten by the next `sync`. Fix upstream and re-sync.

Two consequences of copying rather than rewriting, worth knowing before you read
them:

- Where a playbook points into `src/` — `safing-escalations.md` cites
  `src/agent/safing.rs` for the rule table — it means the **core repo**. That
  code is not in this repository yet; see [PLAN.md](../../PLAN.md).
- The tool names they tell you to call (`get_calibration_report`,
  `get_node_health`, and so on) are the agent's, and reach you here through the
  reference bodies' MCP perception servers. Trailwatch's
  [`serve.py`](../../bodies/trailwatch/serve.py) implements the ones the vision
  playbook calls, over seeded data — every one except `world_memory`, which is
  the agent's own store rather than a perception source.

This file is the exception: it is written here, and `sync_upstream.py` knows it
is ours rather than a vendored artifact that has gone undeclared.
