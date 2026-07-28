# Parity

Three implementations of the deployment planner must produce identical output:

| Implementation | Where it runs | Why it exists |
|---|---|---|
| Rust planner | inside the agent, on the device | the one that actually deploys |
| WASM build of it | in a browser | so a planning UI needs no backend |
| TypeScript port | in the generator app | so the UI stays responsive offline |

Two of those are compiled from the same source. The third is a hand-written
port, and hand-written ports drift. This directory is the mechanism that stops
that drift being discovered by a user.

## What's here

```
MANIFEST.json                  sha256 + size of every vendored artifact
fixtures/deployment/nanopi/    an inventory, and the exact TOML it must produce
fixtures/siteplan/square/      a site case, and the exact site plan it must produce
```

### What the fixtures actually cover

Read this before repeating the byte-identical claim, because it is narrower than
it sounds. The goldens cover the **`[deployment]` block** and the **site plan**.
They do **not** cover the rest of the config preview — `[agent]`, `[provider]`,
`[spine]`, `[orchestrator]`.

That gap has already produced a real divergence: the TypeScript port emitted
`[agent] model = "grok-4"` and `max_iterations`, neither of which is a key the
agent reads, while the Rust planner emitted the correct schema and a `[provider]`
section. Byte-identical where fixtured, silently divergent where not — and the
divergent half is the part a user pastes into their config file. Fixed
downstream; widening the fixture so it cannot recur is open work.

The fixtures are **goldens**: inputs paired with byte-exact expected output.
Not "structurally equivalent", not "semantically the same" — the same bytes.
TOML has enough freedom in key order, quoting and float formatting that
"equivalent" output from three implementations is easy and worthless. Identical
output is the property that lets you plan in one place and run in another.

## Running the gate

```bash
# vendored files still match the manifest
python scripts/sync_upstream.py check

# ...and still match the core agent
python scripts/sync_upstream.py check --upstream ../core

# ...and the generator app's copies too — all three legs
python scripts/sync_upstream.py check --upstream ../core --peer ../generator
```

Bare `check` only proves nobody hand-edited a vendored file. It cannot prove the
manifest is current — for that it needs `--upstream`. The script says so rather
than implying a stronger guarantee than it verified.

## When it fails

A failure names the file, both hashes, and the command that regenerates it:

```
x registry/registry.json: DRIFTED from upstream
      upstream a3f9c21e8b04d7f2  here 91c0ee45ab7d3308
      fix with: python scripts/sync_upstream.py sync
```

Resolve by regenerating upstream, then syncing — never by editing the vendored
copy. The vendored copy is a cache; the core agent is the source of truth.

| Artifact | Regenerated upstream by |
|---|---|
| `registry/registry.json` | `cargo run --bin emit-registry` |
| `wasm/obc-planner/*` | `wasm-pack build planner-wasm --target web` |
| `parity/fixtures/*` | committed goldens — a change here is a deliberate behaviour change |

If a fixture legitimately changes, that is a planner behaviour change and every
implementation has to move together. That is the whole point: the gate turns a
silent divergence into a loud, blocking, obviously-intentional commit.

## History

These artifacts were previously hand-copied between repositories with no sync
step and no drift check. The only thing catching a stale copy was a test
failing afterwards, in a different repo, for a reason that looked unrelated.
Everything in this directory exists to close that gap.
