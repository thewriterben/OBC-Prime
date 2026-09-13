# Parity

Three implementations of the deployment planner must produce identical output:

| Implementation | Where it runs | Why it exists |
|---|---|---|
| Rust planner | inside the agent, on the device | the one that actually deploys |
| WASM build of it | under Node (`--target nodejs`) | so a planning service needs no Rust |
| TypeScript port | in the generator app | so the UI stays responsive offline, and in React Native, where there is no WASM |

Two of those are compiled from the same source, so this is **two
implementations in three executables** — not three independent ones. The
hand-written port is the one that can disagree on logic; the WASM build is the
one that can disagree on *age*. Both failure modes are gated, differently, and
§Drift below says how.

> Corrected 2026-07-29. This table previously said the WASM build runs "in a
> browser". It cannot: the vendored bundle is built `--target nodejs` and ends
> in a CommonJS `require('fs').readFileSync(...)`, which is also why the
> generator's test suite can `require()` it. A browser build is a `--target web`
> rebuild away, and nothing here depends on one.

## What's here

```
MANIFEST.json                  sha256 + size of every vendored artifact
fixtures/deployment/nanopi/    an inventory, and the exact TOML it must produce
fixtures/siteplan/square/      a site case, and the exact site plan it must produce
```

### What the fixtures cover, and the one hole that is left

The goldens cover the **site plan** and the **whole generated config** — not just
its `[deployment]` block, which is all they covered until 2026-07-28.

That narrower version had hidden a real divergence for months. The TypeScript port
emitted `[agent] model = "grok-4"` and `max_iterations` — neither a key the agent
reads — plus `[memory]` and `[fleet.lora_serial]`; the Rust planner emitted a
different `[agent]`, a hardcoded `[provider]` and `[edge]`. Byte-identical where
fixtured, structurally different where not, and the divergent half was the part a
user pastes into their config file.

Both emitters were merged to one canonical output, with **the agent's own config
schema as the arbiter for every disagreement** — which is not a style preference:
the root `Config` does not reject unknown keys, so a key that is not in the schema
parses cleanly and does nothing. Three had accumulated that way (`[memory]
backend`/`path`, `accessories` on a board entry, `datasheet_dir`, whose only
consumer had been deleted).

**The hole that was here is closed**, and how it closed is the part worth keeping.

The two planners had been assigning different tool sets to the same hardware — a
disagreement about what the deployment *does*, invisible until this fixture
existed. Rather than widening the fixture to exclude it, both suites masked the
`role` and `tools` lines and the TypeScript side carried an **expiry assertion**:
a test asserting the divergence was *still there*, which would fail the moment the
mask stopped being necessary. It fired on the next change, and the mask is gone.

That is the pattern to reuse. A gate narrowed to accommodate a known problem
becomes permanent unless something fails when the problem goes away.

The alignment used the **tool registry** as arbiter, the same way the config schema
settled the emitter merge, and found names that do not exist: the orchestrator was
being handed `file_read`, `file_write`, `http_get` and `memory_note` — the real
tools are `file`, `http` and `memory` — while the TypeScript orchestrator was
missing the four delegation tools that are the entire reason an orchestrator
exists. It also surfaced a real bug: `audio_sample` is the *microphone*
capability, so testing it for "has a speaker" described a listen-only board as
playing synthesised speech.

The fixtures are **goldens**: inputs paired with byte-exact expected output.
Not "structurally equivalent", not "semantically the same" — the same bytes.
TOML has enough freedom in key order, quoting and float formatting that
"equivalent" output from three implementations is easy and worthless. Identical
output is the property that lets you plan in one place and run in another.

## Running the gate

```bash
# the bundle BEHAVES as the goldens say (node only — no npm install, no Rust)
node parity/verify_wasm.cjs

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

And none of the `check` legs prove the bundle is *correct*, only that it is the
file we recorded. Those are different claims. `verify_wasm.cjs` is the one that
executes it: it runs `plan_deployment`, `deployment_toml` and `plan_site` against
the vendored fixtures and compares the whole generated config byte for byte. It
was verified by running it against the pre-2026-07-30 bundle, which it fails with
a line-by-line diff. It runs in CI (the `behaviour` job) because it needs nothing
but node.

Note the sibling-directory names. `CONTRIBUTING.md` writes these as
`../Oh-Ben-Claw` and `../OBC-deployment-generator`, which are the real repository
names; `../core` and `../generator` here are placeholders for whatever you
cloned them as. Use your actual paths.

## Putting everything back in step

One command. It rebuilds the WASM in the core repo, copies all 233 artifacts
here, updates the generator's 12 mirrors, and records what the bundle was
compiled from:

```bash
python scripts/sync_upstream.py sync \
    --upstream ../Oh-Ben-Claw \
    --peer ../OBC-deployment-generator \
    --rebuild-wasm
```

Prerequisites, once per machine:

```bash
rustup target add wasm32-unknown-unknown
cargo install wasm-pack
```

Then confirm all four legs:

```bash
python scripts/sync_upstream.py check --upstream ../Oh-Ben-Claw --peer ../OBC-deployment-generator
cd ../OBC-deployment-generator && npm test    # 143 tests, incl. the whole-config wasm assertion
cd ../Oh-Ben-Claw && cargo test --workspace
```

### Why `--rebuild-wasm` is not optional for the WASM leg

`sync` will happily copy a bundle it did not build. When it does, it **carries
the previous build-input hashes forward untouched** rather than recording the
current sources — because a run that only copied a bundle has no standing to say
what that bundle was compiled from, and writing today's hashes next to an old
`.wasm` would clear the gate on exactly the staleness it exists to catch.

So the `wasm_build` block in `MANIFEST.json` is only ever written by
`--rebuild-wasm`, in the same run that invoked `wasm-pack`. That block carries
`"built_by_this_script": true` to say so.

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
| `wasm/obc-planner/*` | `wasm-pack build planner-wasm --target nodejs` |
| `parity/fixtures/*` | committed goldens — a change here is a deliberate behaviour change |

If a fixture legitimately changes, that is a planner behaviour change and every
implementation has to move together. That is the whole point: the gate turns a
silent divergence into a loud, blocking, obviously-intentional commit.

## History

These artifacts were previously hand-copied between repositories with no sync
step and no drift check. The only thing catching a stale copy was a test
failing afterwards, in a different repo, for a reason that looked unrelated.
Everything in this directory exists to close that gap.
