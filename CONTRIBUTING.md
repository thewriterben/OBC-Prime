# Contributing to Open Body Control

## Where work happens

OBC-Prime is the **public project**. The Rust agent it runs is developed
upstream in [**Oh-Ben-Claw**](https://github.com/thewriterben/Oh-Ben-Claw),
and moves here as each piece becomes defensible — which is also the order its
documentation can be written honestly.

So, before you open a PR here, check which repo the change belongs to:

| Change | Repo |
|---|---|
| Agent behaviour, memory, tools, channels, spine, safety | **Oh-Ben-Claw** (upstream) |
| `registry/registry.json`, `parity/fixtures/`, `wasm/obc-planner/` | **Oh-Ben-Claw** — these are *emitted* there and vendored here |
| Reference bodies (`bodies/`), quickstarts, deployment guides | **here** |
| `docs/`, `PLAN.md`, anything a first-time user reads | **here** |

A PR that edits a vendored artifact directly will fail CI, by design — see
below.

## Vendored artifacts are checked by hash, not by trust

`registry/`, `parity/fixtures/` and `wasm/obc-planner/` are copies. They exist
in three repositories, and they used to be kept in step by hand-copying, with
no sync step and no verification: the only thing that ever caught a stale copy
was a test failing afterwards, in a different repository, for a reason that
looked unrelated.

Now there is one declarative list, a manifest of SHA-256 hashes, and a CI job
that fails on divergence:

```bash
python scripts/sync_upstream.py check                 # vs the manifest
python scripts/sync_upstream.py check --upstream ../Oh-Ben-Claw   # vs the core repo
python scripts/sync_upstream.py sync  --upstream ../Oh-Ben-Claw   # re-vendor + re-hash
```

A bare `check` can only prove nobody hand-edited a vendored file. It **cannot**
prove the manifest itself is current — that needs `--upstream`. The tool says
so in its own output rather than implying a stronger guarantee than it
verified.

To change a vendored artifact: change it upstream, then `sync --upstream` here
and commit the manifest update alongside it.

## Reference bodies

A Reference Body under `bodies/` is a complete deployment — config, firmware,
and a database with real recorded history — that runs before any hardware
exists. If you add one, it must actually start from a clean clone, and its
seeded data must be real recorded history rather than fabricated rows. The
point of seeding is to turn documentation into evidence; invented data turns it
back into documentation.

## Documentation

Two rules, both of which this project has broken and fixed:

- **Do not document what does not run.** A feature described in a README and
  absent from the code is worse than a missing feature. If you remove a
  capability, remove its documentation in the same commit.
- **Numbers get checked.** A figure in a doc should have been measured, and if
  it was inherited from an earlier draft it should be re-derived rather than
  copied. `docs/DECISIONS.md` records two occasions where a wrong number
  survived its own correction because only the argument was fixed and the
  summary was not.

Decisions with consequences go in `docs/DECISIONS.md`: what was chosen, what it
was chosen *over*, what it costs, and how it was verified. A gate that has
never been observed failing is not known to work, so say how you made it fail.

## Commit messages

Say what was wrong, what changed, and what you are not claiming. Known
weaknesses stated in the message are worth more than a clean message that hides
them.

## License

MIT — see [LICENSE](LICENSE).

The vendored artifacts under `registry/`, `parity/` and `wasm/` originate in
Oh-Ben-Claw, which is MIT-licensed by the same author; they carry the same
terms. By contributing you agree that your contributions are licensed under the
MIT License.
