#!/usr/bin/env python3
"""
sync_upstream.py — keep OBC-Prime's vendored artifacts identical to upstream.

The problem this solves
-----------------------
Three independent implementations of the deployment planner must agree
byte-for-byte: the Rust planner in the core agent, the WASM build of it, and
the TypeScript port in the generator app. That agreement is enforced by golden
fixtures — but the fixtures, the board registry and the WASM bundle were
historically hand-copied between repos with no sync step and no drift check.
Nothing caught staleness except a test failing later, in another repo, for a
reason that looked unrelated.

This script makes the copy explicit, hashes every artifact into a manifest, and
gives CI a way to fail fast when any copy diverges.

Usage
-----
    python scripts/sync_upstream.py sync    --upstream <path-to-core-repo> [--peer <path>]
    python scripts/sync_upstream.py check   [--upstream <path>] [--peer <path>]

`sync`  copies upstream -> here, rewrites parity/MANIFEST.json, and with --peer
        also updates the generator app's mirrors (11 of the 43 artifacts).
        With --rebuild-wasm it runs wasm-pack in the upstream repo first and
        records what the bundle was compiled from. Without it, the previous
        build-input hashes are carried forward unchanged.

The one command that puts everything in step:

    python scripts/sync_upstream.py sync --upstream ../Oh-Ben-Claw \
        --peer ../OBC-deployment-generator --rebuild-wasm
`check` verifies, in order:
          1. every vendored file matches the manifest hash   (always)
          2. every vendored file matches upstream            (if --upstream)
          3. the WASM bundle's build inputs are unchanged    (if --upstream)
          4. every peer mirror matches too                   (if --peer)
        Exits non-zero on any mismatch. This is the CI gate.

        (3) exists because (1) and (2) structurally cannot catch a stale build:
        a compiled artifact never drifts from its own hash. Only the sources it
        was compiled from can show that it is out of date.

Paths may also come from OBC_UPSTREAM / OBC_PEER environment variables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "parity" / "MANIFEST.json"

# (path in upstream core repo, path here, {peer name: path in that peer} or None)
#
# The third column was a single generator path until 2026-07-30. Accelerapp
# carries copies of registry.json and templates.json too, and had done since
# Ecosystem Integration I1/I6, hashed by nobody -- they matched the canonical
# files exactly, by luck rather than by a gate. A named map costs one level of
# nesting and means the next consumer is a line rather than a refactor.
#
# Keep this list as the single declaration of what is vendored. Adding a
# vendored file anywhere without adding it here is the exact failure mode this
# script exists to prevent.
ARTIFACTS: list[tuple[str, str, dict[str, str] | None]] = [
    ("registry/registry.json",
     "registry/registry.json",
     {"generator": "lib/registry.json",
      "accelerapp": "src/accelerapp/hardware/registry.json"}),

    # The shared firmware template set (Ecosystem Integration I6): one starter
    # sketch per flashable registry board, exported from the same tables as
    # registry.json. Vendored here from 2026-07-30 — it was always a cross-repo
    # artifact, carried by the generator and Accelerapp and hashed by neither.
    #
    # It became load-bearing when obc-planner arrived: the crate's
    # `committed_templates_json_is_current` walks up from its own directory
    # looking for this file and fails loudly if it cannot find it, which is the
    # correct behaviour for a guard and would have turned the `substrate` job red
    # on the commit that vendored the crate.
    ("firmware-templates/templates.json",
     "firmware-templates/templates.json",
     {"generator": "lib/firmware-templates.json",
      "accelerapp": "src/accelerapp/firmware/templates.json"}),

    ("tests/fixtures/deployment/nanopi/inventory.json",
     "parity/fixtures/deployment/nanopi/inventory.json",
     {"generator": "tests/fixtures/deployment/nanopi/inventory.json"}),
    ("tests/fixtures/deployment/nanopi/expected-deployment.toml",
     "parity/fixtures/deployment/nanopi/expected-deployment.toml",
     {"generator": "tests/fixtures/deployment/nanopi/expected-deployment.toml"}),
    # The whole generated config, not just its [deployment] block. Added after the
    # narrower golden was found to have hidden a real divergence for months.
    ("tests/fixtures/deployment/nanopi/expected-config.toml",
     "parity/fixtures/deployment/nanopi/expected-config.toml",
     {"generator": "tests/fixtures/deployment/nanopi/expected-config.toml"}),
    ("tests/fixtures/siteplan/square/case.json",
     "parity/fixtures/siteplan/square/case.json",
     {"generator": "tests/fixtures/siteplan/square/case.json"}),
    ("tests/fixtures/siteplan/square/expected-site.toml",
     "parity/fixtures/siteplan/square/expected-site.toml",
     {"generator": "tests/fixtures/siteplan/square/expected-site.toml"}),

    ("planner-wasm/pkg/obc_planner_wasm_bg.wasm",
     "wasm/obc-planner/obc_planner_wasm_bg.wasm",
     {"generator": "wasm/obc-planner/obc_planner_wasm_bg.wasm"}),
    ("planner-wasm/pkg/obc_planner_wasm.js",
     "wasm/obc-planner/obc_planner_wasm.js",
     {"generator": "wasm/obc-planner/obc_planner_wasm.js"}),
    ("planner-wasm/pkg/obc_planner_wasm.d.ts",
     "wasm/obc-planner/obc_planner_wasm.d.ts",
     {"generator": "wasm/obc-planner/obc_planner_wasm.d.ts"}),
    ("planner-wasm/pkg/obc_planner_wasm_bg.wasm.d.ts",
     "wasm/obc-planner/obc_planner_wasm_bg.wasm.d.ts",
     {"generator": "wasm/obc-planner/obc_planner_wasm_bg.wasm.d.ts"}),
    ("planner-wasm/pkg/package.json",
     "wasm/obc-planner/package.json",
     {"generator": "wasm/obc-planner/package.json"}),

    # ── The memory substrate ─────────────────────────────────────────────────
    # The first piece of the agent to move here (2026-07-30). Vendored rather
    # than relocated, the same call DECISIONS.md made for firmware: the crates
    # stay in the core repo where the rest of the agent compiles against them,
    # and this repository carries a hash-checked copy it can build and test on
    # its own. `cargo test -p obc-memory` runs here, in CI, against real agent
    # code — which is more than a vendored copy usually earns, and the reason
    # this is worth doing rather than just publishing the docs.
    #
    # No peer column: the generator is a TypeScript app and has no use for them.
    #
    # `src/image.rs` was here until 2026-07-30 and is gone because upstream
    # deleted it — multimodal image memory was cut as documented-but-never-run.
    # This list did not notice for two commits, and neither did CI: `check`
    # without --upstream compares vendored files to their own recorded hashes,
    # which a deleted-upstream file passes trivially. Its own output says so
    # ("not that the manifest is current"). The `upstream` job below is now
    # enabled precisely so that sentence stops being the only warning.

    ("crates/obc-paths/Cargo.toml",
     "crates/obc-paths/Cargo.toml",
     None),
    ("crates/obc-paths/src/lib.rs",
     "crates/obc-paths/src/lib.rs",
     None),

    ("crates/obc-memory/Cargo.toml",
     "crates/obc-memory/Cargo.toml",
     None),
    ("crates/obc-memory/src/lib.rs",
     "crates/obc-memory/src/lib.rs",
     None),
    ("crates/obc-memory/src/world.rs",
     "crates/obc-memory/src/world.rs",
     None),
    ("crates/obc-memory/src/liveness.rs",
     "crates/obc-memory/src/liveness.rs",
     None),
    ("crates/obc-memory/src/expiry.rs",
     "crates/obc-memory/src/expiry.rs",
     None),
    ("crates/obc-memory/src/trajectory.rs",
     "crates/obc-memory/src/trajectory.rs",
     None),
    ("crates/obc-memory/src/embed.rs",
     "crates/obc-memory/src/embed.rs",
     None),
    ("crates/obc-memory/src/heartbeat.rs",
     "crates/obc-memory/src/heartbeat.rs",
     None),
    ("crates/obc-memory/src/journal.rs",
     "crates/obc-memory/src/journal.rs",
     None),
    ("crates/obc-memory/src/vector.rs",
     "crates/obc-memory/src/vector.rs",
     None),

    # ── The planner ──────────────────────────────────────────────────────────
    # The second piece to move here (2026-07-30), on the same terms as the memory
    # substrate: vendored, hash-checked, and compiled by the `substrate` job
    # rather than merely stored.
    #
    # It matters more than obc-memory did, because this repository already
    # carried a *build* of this code — the bundle under wasm/ — without carrying
    # the source. The README leads with three planner implementations agreeing;
    # two of the three were a compiled blob and a TypeScript port, and the Rust
    # the blob came from lived in another repository. Vendoring the crate makes
    # that a comparison rather than a promise, and WASM_SOURCES hashes exactly
    # these files.

    ("crates/obc-planner/Cargo.toml",
     "crates/obc-planner/Cargo.toml",
     None),
    ("crates/obc-planner/src/lib.rs",
     "crates/obc-planner/src/lib.rs",
     None),
    ("crates/obc-planner/src/config.rs",
     "crates/obc-planner/src/config.rs",
     None),
    ("crates/obc-planner/src/geo/mod.rs",
     "crates/obc-planner/src/geo/mod.rs",
     None),
    ("crates/obc-planner/src/geo/anchor.rs",
     "crates/obc-planner/src/geo/anchor.rs",
     None),
    ("crates/obc-planner/src/siteplan/mod.rs",
     "crates/obc-planner/src/siteplan/mod.rs",
     None),
    ("crates/obc-planner/src/peripherals/mod.rs",
     "crates/obc-planner/src/peripherals/mod.rs",
     None),
    ("crates/obc-planner/src/peripherals/registry.rs",
     "crates/obc-planner/src/peripherals/registry.rs",
     None),
    ("crates/obc-planner/src/deployment/mod.rs",
     "crates/obc-planner/src/deployment/mod.rs",
     None),
    ("crates/obc-planner/src/deployment/advisor.rs",
     "crates/obc-planner/src/deployment/advisor.rs",
     None),
    ("crates/obc-planner/src/deployment/firmware_scaffold.rs",
     "crates/obc-planner/src/deployment/firmware_scaffold.rs",
     None),
    ("crates/obc-planner/src/deployment/inventory.rs",
     "crates/obc-planner/src/deployment/inventory.rs",
     None),
    ("crates/obc-planner/src/deployment/planner.rs",
     "crates/obc-planner/src/deployment/planner.rs",
     None),
    ("crates/obc-planner/src/deployment/scheme.rs",
     "crates/obc-planner/src/deployment/scheme.rs",
     None),

    # ── Track 0 ──────────────────────────────────────────────────────────────
    # The third piece to move here (2026-08-01), on the same terms as the two
    # before it: vendored, hash-checked, compiled and tested by the `substrate`
    # job rather than merely stored.
    #
    # This is the piece with the strongest claim to being in the public repo,
    # because it is the one the README's safety claim rests on. `docs/SAFETY.md`
    # describes a pin allowlist and value ranges enforced at the actuator, a
    # hash-chained Ed25519-signed record of every physical decision, a risk
    # classification that drives approval defaults, and a taint guard that
    # refuses a privileged call whose arguments echo untrusted content. Until
    # now a reader could check none of that: the document was here and the code
    # was in another repository. Now `cargo test -p obc-safety` runs it here.
    #
    # `src/risk.rs` is the reason the extraction was possible at all. RiskClass,
    # BlastRadius, OutputTrust and RolloutStage used to live in `tools::traits`,
    # so three Track 0 files imported *upward* into the largest module in the
    # tree. They are the contract rather than tool machinery; upstream moved
    # them down here and `tools::traits` re-exports them, which is why this
    # crate has no outward edges left to vendor.
    #
    # No peer column: the generator and Accelerapp have no use for these.

    ("crates/obc-safety/Cargo.toml",
     "crates/obc-safety/Cargo.toml",
     None),
    ("crates/obc-safety/src/lib.rs",
     "crates/obc-safety/src/lib.rs",
     None),
    ("crates/obc-safety/src/risk.rs",
     "crates/obc-safety/src/risk.rs",
     None),
    # The host half of spine authentication (2026-08-01). Canonical; the node's
    # copy is firmware/heltec-lora-linktest/src/auth.rs, and upstream compiles
    # both against RFC 4231 and RFC 5869 vectors. Landing it here means the
    # document in docs/SPINE-AUTH.md and the arithmetic it specifies are in the
    # same repository for the first time.
    ("crates/obc-safety/src/spine_tag.rs",
     "crates/obc-safety/src/spine_tag.rs",
     None),
    ("crates/obc-safety/src/limits.rs",
     "crates/obc-safety/src/limits.rs",
     None),
    ("crates/obc-safety/src/audit.rs",
     "crates/obc-safety/src/audit.rs",
     None),
    ("crates/obc-safety/src/audit_sign.rs",
     "crates/obc-safety/src/audit_sign.rs",
     None),
    ("crates/obc-safety/src/taint.rs",
     "crates/obc-safety/src/taint.rs",
     None),
    ("crates/obc-safety/src/trust.rs",
     "crates/obc-safety/src/trust.rs",
     None),
    ("crates/obc-safety/src/pairing.rs",
     "crates/obc-safety/src/pairing.rs",
     None),
    ("crates/obc-safety/src/policy.rs",
     "crates/obc-safety/src/policy.rs",
     None),
    ("crates/obc-safety/src/redteam.rs",
     "crates/obc-safety/src/redteam.rs",
     None),
    ("crates/obc-safety/src/vault.rs",
     "crates/obc-safety/src/vault.rs",
     None),

    # ── Body telemetry ───────────────────────────────────────────────────────
    # The fourth crate (2026-08-01), and the first upstream picked with an
    # instrument rather than by reading imports: `scripts/extractability.py`
    # counts each module's outward edges, and power, comms and sensing were
    # three of the six with none pointing anywhere still in the core tree.
    #
    # One crate because they are one pattern. Each classifies a raw reading
    # against configured expectations, records it in world memory under a stable
    # entity name, and derives a coarse mode a reflex rule can watch without
    # understanding the domain: `power.mode`, `net.mode`, `sensor.{quantity}`
    # plus a quality flag.
    #
    # This is the half of the README's reflex claim that had no code here. The
    # firmware has been vendored since the beginning, so "the reflex layer keeps
    # working when the brain is unreachable" was checkable on the node side and
    # nowhere else. The host side is these three. The honest limit, stated here
    # rather than left to be discovered: the reflex *engine* is in the core
    # crate's `agent/` behind thirteen blocking edges and cannot follow yet, so
    # this backs perceive-and-classify, not the whole sentence.
    #
    # Not `observability`, which is the agent watching itself and is still
    # upstream. This is the agent watching its body.

    ("crates/obc-telemetry/Cargo.toml",
     "crates/obc-telemetry/Cargo.toml",
     None),
    ("crates/obc-telemetry/src/lib.rs",
     "crates/obc-telemetry/src/lib.rs",
     None),
    ("crates/obc-telemetry/src/power.rs",
     "crates/obc-telemetry/src/power.rs",
     None),
    ("crates/obc-telemetry/src/comms.rs",
     "crates/obc-telemetry/src/comms.rs",
     None),
    ("crates/obc-telemetry/src/sensing.rs",
     "crates/obc-telemetry/src/sensing.rs",
     None),

    # ── Node firmware ────────────────────────────────────────────────────────
    # Authored upstream, vendored here so the flashing guide and the sources it
    # describes cannot drift apart. `spine.rs` in particular is compiled by a
    # host-side test upstream (tests/firmware_spine_framing.rs) — the firmware and
    # the harness share one copy on purpose, and so does this one.

    ("firmware/obc-esp32-s3/.cargo/config.toml",
     "firmware/obc-esp32-s3/.cargo/config.toml",
     None),
    ("firmware/obc-esp32-s3/BRINGUP.md",
     "firmware/obc-esp32-s3/BRINGUP.md",
     None),
    ("firmware/obc-esp32-s3/CAMERA.md",
     "firmware/obc-esp32-s3/CAMERA.md",
     None),
    ("firmware/obc-esp32-s3/Cargo.lock",
     "firmware/obc-esp32-s3/Cargo.lock",
     None),
    ("firmware/obc-esp32-s3/Cargo.toml",
     "firmware/obc-esp32-s3/Cargo.toml",
     None),
    ("firmware/obc-esp32-s3/build.rs",
     "firmware/obc-esp32-s3/build.rs",
     None),
    ("firmware/obc-esp32-s3/components_esp32s3.lock",
     "firmware/obc-esp32-s3/components_esp32s3.lock",
     None),
    ("firmware/obc-esp32-s3/idf_component.yml",
     "firmware/obc-esp32-s3/idf_component.yml",
     None),
    ("firmware/obc-esp32-s3/rust-toolchain.toml",
     "firmware/obc-esp32-s3/rust-toolchain.toml",
     None),
    ("firmware/obc-esp32-s3/sdkconfig.defaults",
     "firmware/obc-esp32-s3/sdkconfig.defaults",
     None),
    ("firmware/obc-esp32-s3/src/audio.rs",
     "firmware/obc-esp32-s3/src/audio.rs",
     None),
    ("firmware/obc-esp32-s3/src/camera.rs",
     "firmware/obc-esp32-s3/src/camera.rs",
     None),
    ("firmware/obc-esp32-s3/src/camera_bindings.h",
     "firmware/obc-esp32-s3/src/camera_bindings.h",
     None),
    ("firmware/obc-esp32-s3/src/dht.rs",
     "firmware/obc-esp32-s3/src/dht.rs",
     None),
    ("firmware/obc-esp32-s3/src/main.rs",
     "firmware/obc-esp32-s3/src/main.rs",
     None),
    ("firmware/obc-esp32-s3/src/reflex.rs",
     "firmware/obc-esp32-s3/src/reflex.rs",
     None),
    ("firmware/obc-esp32-s3/src/safety.rs",
     "firmware/obc-esp32-s3/src/safety.rs",
     None),
    ("firmware/obc-esp32-s3/src/safing.rs",
     "firmware/obc-esp32-s3/src/safing.rs",
     None),
    ("firmware/obc-esp32-s3/src/sensors.rs",
     "firmware/obc-esp32-s3/src/sensors.rs",
     None),
    ("firmware/heltec-lora-linktest/.cargo/config.toml",
     "firmware/heltec-lora-linktest/.cargo/config.toml",
     None),
    ("firmware/heltec-lora-linktest/Cargo.lock",
     "firmware/heltec-lora-linktest/Cargo.lock",
     None),
    ("firmware/heltec-lora-linktest/Cargo.toml",
     "firmware/heltec-lora-linktest/Cargo.toml",
     None),
    ("firmware/heltec-lora-linktest/build.rs",
     "firmware/heltec-lora-linktest/build.rs",
     None),
    ("firmware/heltec-lora-linktest/rust-toolchain.toml",
     "firmware/heltec-lora-linktest/rust-toolchain.toml",
     None),
    ("firmware/heltec-lora-linktest/sdkconfig.defaults",
     "firmware/heltec-lora-linktest/sdkconfig.defaults",
     None),
    # Spine frame authentication, node side (SPINE-AUTH.md step 2). Nothing
    # calls it: no frame carries a tag and no receiver checks one. It is here so
    # that the wire change in step 4 starts from two ends already proven to
    # agree, and so this repository can run that proof — `cargo test
    # -p obc-safety` plus the core repo's cross-implementation vectors.
    ("firmware/heltec-lora-linktest/src/auth.rs",
     "firmware/heltec-lora-linktest/src/auth.rs",
     None),
    ("firmware/heltec-lora-linktest/src/main.rs",
     "firmware/heltec-lora-linktest/src/main.rs",
     None),
    ("firmware/heltec-lora-linktest/src/spine.rs",
     "firmware/heltec-lora-linktest/src/spine.rs",
     None),
    ("firmware/heltec-lora-linktest/src/sx1262.rs",
     "firmware/heltec-lora-linktest/src/sx1262.rs",
     None),
    ("firmware/lora-node/README.md",
     "firmware/lora-node/README.md",
     None),
    ("firmware/lora-node/obc_lora_bridge/obc_lora_bridge.ino",
     "firmware/lora-node/obc_lora_bridge/obc_lora_bridge.ino",
     None),
    ("firmware/t-deck-terminal/README.md",
     "firmware/t-deck-terminal/README.md",
     None),
    ("firmware/t-deck-terminal/t_deck_terminal/t_deck_terminal.ino",
     "firmware/t-deck-terminal/t_deck_terminal/t_deck_terminal.ino",
     None),
]

# The upstream sources the WASM bundle is *compiled from*, via the `#[path]`
# shims in `planner-wasm/src/`. These are NOT vendored — they are hashed so that
# a planner change without a rebuild is caught.
#
# Why this exists: the manifest hashes the built `.wasm`, and a built artifact
# cannot drift from itself. On 2026-07-11 the bundle was built; on 2026-07-28
# `src/deployment/planner.rs` was rewritten three times and the goldens with it.
# Every hash in the manifest still matched, every parity check still passed, and
# the vendored bundle emitted a 79-line config where the golden had 119 — with a
# hardcoded `[provider] openai / gpt-4o` in it. Hashing the build inputs is the
# only way a hash gate can see that.
WASM_SOURCES: list[str] = [
    # Updated 2026-07-30, when the core repo extracted crates/obc-planner. These
    # were src/geo, src/siteplan, src/deployment/* and src/peripherals/registry.rs,
    # compiled into planner-wasm verbatim through `#[path]`; that crate now has an
    # ordinary dependency, and the two shim mod.rs files listed here no longer
    # exist. Ten of the twelve entries pointed at paths that were gone.
    #
    # `geo/anchor.rs` is deliberately absent: it sits behind obc-planner's
    # `world-anchor` feature, which wasm builds do not enable, so it is not an
    # input to this bundle. Being part of the crate and being part of the build
    # are different questions, and only the second one belongs here.
    "planner-wasm/Cargo.toml",
    "planner-wasm/src/lib.rs",
    "crates/obc-planner/Cargo.toml",
    "crates/obc-planner/src/lib.rs",
    "crates/obc-planner/src/config.rs",
    "crates/obc-planner/src/geo/mod.rs",
    "crates/obc-planner/src/siteplan/mod.rs",
    "crates/obc-planner/src/peripherals/mod.rs",
    "crates/obc-planner/src/peripherals/registry.rs",
    "crates/obc-planner/src/deployment/mod.rs",
    "crates/obc-planner/src/deployment/advisor.rs",
    "crates/obc-planner/src/deployment/firmware_scaffold.rs",
    "crates/obc-planner/src/deployment/inventory.rs",
    "crates/obc-planner/src/deployment/planner.rs",
    "crates/obc-planner/src/deployment/scheme.rs",
]

WASM_REBUILD_CMD = "wasm-pack build planner-wasm --target nodejs"

# Vendored files that a *fresh checkout* of upstream does not contain, and why.
#
# `check --upstream` compares each vendored file to the same path in an upstream
# working copy. That silently assumes the upstream copy is a git checkout plus
# nothing — and on a developer machine it is a checkout plus every build output
# and ignored file that has ever been produced there. Locally every one of these
# resolved and matched. In CI, against a real checkout, all seven failed.
#
#   planner-wasm/pkg/       ignored by planner-wasm/pkg/.gitignore (`*`)
#   firmware/*/Cargo.lock   ignored by the root .gitignore (`Cargo.lock`)
#
# Rebuilding the bundle in CI does not rescue the comparison, which was the
# first attempt: wasm-pack output is not byte-reproducible across toolchains, so
# a fresh build differs from the vendored one for reasons that have nothing to
# do with drift. The bundle is still covered, twice over and better:
#
#   * the `behaviour` job executes it against the vendored goldens, which is a
#     statement about output rather than bytes, and is what would actually catch
#     a wrong planner;
#   * `wasm_build` records the hashes of the *sources* it was compiled from, and
#     those are ordinary tracked files, so staleness is caught by comparing them
#     — which is the check that found the six-week-old bundle in the first place.
#
# Skips are printed on every run. A check that quietly declines to check is worse
# than one that fails.
UNCOMPARABLE_UPSTREAM: dict[str, str] = {
    "wasm/obc-planner/obc_planner_wasm_bg.wasm":
        "build output, gitignored upstream; not byte-reproducible across toolchains",
    "wasm/obc-planner/obc_planner_wasm.js":
        "build output, gitignored upstream",
    "wasm/obc-planner/obc_planner_wasm.d.ts":
        "build output, gitignored upstream",
    "wasm/obc-planner/obc_planner_wasm_bg.wasm.d.ts":
        "build output, gitignored upstream",
    "wasm/obc-planner/package.json":
        "build output, gitignored upstream; embeds the wasm-pack version",
    "firmware/obc-esp32-s3/Cargo.lock":
        "gitignored upstream (root .gitignore: Cargo.lock)",
    "firmware/heltec-lora-linktest/Cargo.lock":
        "gitignored upstream (root .gitignore: Cargo.lock)",
}


# Directories whose contents are vendored in their entirety, mapped to the few
# files inside them that belong to this repository instead.
#
# ARTIFACTS answers "is everything we declared still correct". It cannot answer
# "is everything present still declared", and on 2026-07-30 that gap had teeth:
# upstream deleted crates/obc-memory/src/image.rs, this repository kept its copy
# and kept compiling it, and every gate stayed green because `check` only ever
# walks ARTIFACTS. The crate here had quietly become a different crate from the
# one upstream builds.
#
# Removing an entry from ARTIFACTS does not remove the file either — `sync`
# copies, it never deletes — so the same hole opens from the other direction the
# moment something is retired. This closes both.
VENDORED_TREES: dict[str, set[str]] = {
    "crates": set(),
    "wasm": set(),
    "registry": set(),
    # This repo's own prose about the vendored firmware, not a vendored file.
    "firmware": {"firmware/README.md"},
}


def undeclared_vendored_files() -> list[str]:
    """Files sitting in a vendored tree that ARTIFACTS does not declare."""
    declared = {local for _up, local, _peer in ARTIFACTS}
    found: list[str] = []
    for tree, own in VENDORED_TREES.items():
        base = ROOT / tree
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel not in declared and rel not in own:
                found.append(rel)
    return found


# How each artifact is produced upstream. Printed on drift so the fix is
# obvious instead of requiring archaeology.
REGENERATE = {
    "registry/registry.json": "cargo run --bin emit-registry",
    "wasm/obc-planner/": "wasm-pack build planner-wasm --target nodejs",
    "parity/fixtures/": "cargo test  (fixtures are committed goldens)",
    "firmware/": "(hand-authored upstream — edit there, then sync)",
}

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
if os.name == "nt" and not os.environ.get("WT_SESSION"):
    GREEN = RED = YELLOW = DIM = RESET = ""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def resolve(flag: str | None, env: str | None, what: str, required: bool) -> Path | None:
    # `env` is None for named peers, which have no environment fallback. Without
    # the guard this is saved only by short-circuiting on a non-empty flag, which
    # is luck rather than design.
    raw = flag or (os.environ.get(env) if env else None)
    if not raw:
        if required:
            sys.exit(f"{RED}error{RESET}: --{what} not given"
                     + (f" and {env} not set" if env else ""))
        return None
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        sys.exit(f"{RED}error{RESET}: {what} path is not a directory: {p}")
    return p


def hint_for(local: str) -> str:
    for prefix, cmd in REGENERATE.items():
        if local.startswith(prefix):
            return cmd
    return "(unknown — see parity/README.md)"


def rebuild_wasm(upstream: Path) -> bool:
    """Run wasm-pack in the upstream repo. Returns True on success.

    This exists so that recording the build-input hashes cannot be a guess. A
    plain `sync` copies whatever bundle is on disk; if that bundle is stale,
    recording the *current* source hashes alongside it would launder the exact
    staleness this mechanism was added to catch — the gate would go green on a
    bundle that is still wrong. So `sync` never writes fresh hashes unless it
    built the bundle itself, in this function, moments earlier.
    """
    print(f"{DIM}$ {WASM_REBUILD_CMD}{RESET}  (in {upstream})")
    try:
        proc = subprocess.run(WASM_REBUILD_CMD.split(), cwd=upstream)
    except FileNotFoundError:
        print(f"{RED}error{RESET}: wasm-pack not found on PATH.\n"
              f"       install it with: cargo install wasm-pack\n"
              f"       (it also needs the wasm target: "
              f"rustup target add wasm32-unknown-unknown)")
        return False
    if proc.returncode != 0:
        print(f"{RED}error{RESET}: wasm-pack exited {proc.returncode} — "
              f"not recording build inputs")
        return False
    print(f"{GREEN}built{RESET} {upstream / 'planner-wasm' / 'pkg'}")
    return True


def toolchain_versions(upstream: Path) -> dict:
    """What built the bundle, so a binary diff with no source diff is explainable.

    The build inputs say which *sources* went in. They say nothing about the
    compiler, and a rustc or wasm-bindgen bump rewrites the `.wasm` — and
    sometimes the JS glue — with no source change at all. The drift gate is right
    to stay green for that, but a 200 KB binary moving for no visible reason is
    the kind of thing that costs an hour to re-derive. Recording it turns that
    into a one-line diff.
    """
    def probe(cmd: list[str]) -> str | None:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return r.stdout.strip().splitlines()[0]

    versions = {
        "rustc": probe(["rustc", "--version"]),
        "wasm-pack": probe(["wasm-pack", "--version"]),
    }
    # wasm-bindgen is the one that rewrites the JS glue, and it is pinned by the
    # lockfile rather than by anything on PATH.
    lock = upstream / "Cargo.lock"
    if lock.exists():
        text = lock.read_text(encoding="utf-8", errors="replace")
        i = text.find('name = "wasm-bindgen"')
        if i != -1:
            for line in text[i:i + 400].splitlines():
                if line.startswith("version = "):
                    versions["wasm-bindgen"] = line.split('"')[1]
                    break
    return {k: v for k, v in versions.items() if v}


def do_sync(upstream: Path, peers: dict[str, Path] | None = None, rebuild: bool = False) -> int:
    if rebuild and not rebuild_wasm(upstream):
        return 1

    # The prior manifest, read before anything is copied. The manifest is rebuilt
    # from what this run copied, so the artifacts a plain upstream checkout cannot
    # supply need their entries carried forward — a dropped entry is an artifact
    # nobody hashes any more, which is the silent-hole failure this script exists
    # to prevent.
    prior_manifest: dict = {}
    if MANIFEST.exists():
        try:
            prior_manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prior_manifest = {}
    prior_artifacts: dict = prior_manifest.get("artifacts") or {}

    copied, missing, mirrored, carried = [], [], [], []
    for up, local, peer_rel in ARTIFACTS:
        src, dst = upstream / up, ROOT / local
        if not src.exists():
            # `sync` used to abort for anything missing, which meant it could not
            # run at all against a clean upstream clone: the five wasm build
            # outputs and two firmware Cargo.locks are gitignored upstream and
            # simply are not there. `check --upstream` has skipped exactly these
            # since 2026-07-30 — the same knowledge, applied in one command and
            # not the other. Found on 2026-08-01 while vendoring obc-safety,
            # where an unrelated missing bundle blocked a sync that had nothing
            # to do with the bundle.
            if local in UNCOMPARABLE_UPSTREAM:
                entry = prior_artifacts.get(local)
                if entry is None and dst.exists():
                    entry = {"sha256": sha256(dst), "bytes": dst.stat().st_size}
                if entry is None:
                    missing.append(f"{up}  (uncomparable upstream, and no vendored copy here)")
                    continue
                # The recorded hash wins over re-hashing the file on disk: if the
                # vendored copy was hand-edited, carrying the old hash forward is
                # what lets `check` still say so.
                carried.append((local, UNCOMPARABLE_UPSTREAM[local]))
                copied.append((local, entry["sha256"], entry["bytes"]))
                continue
            missing.append(up)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append((local, sha256(dst), dst.stat().st_size))

        # The generator carries its own copy of 11 of these. `sync` used to write
        # only this repo, so a rebuilt WASM landed here and the generator kept the
        # old one — `check --peer` then reported drift that `sync` could not fix,
        # and the documented remedy ("fix with: sync") was wrong for that case.
        for name, root in (peers or {}).items():
            rel = (peer_rel or {}).get(name)
            if not rel:
                continue
            mirror = root / rel
            mirror.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, mirror)
            mirrored.append(f"{name}:{rel}")

    if missing:
        print(f"{RED}missing upstream artifacts:{RESET}")
        for m in missing:
            print(f"  {m}")
        return 1

    # Record what the WASM was built from, so `check --upstream` can tell that a
    # later planner edit invalidated the bundle.
    #
    # Only written when this run did the build (--rebuild-wasm). Otherwise the
    # previous block is carried forward untouched: a sync that merely copies a
    # bundle it did not build has no standing to say what that bundle was
    # compiled from, and guessing is how the gate would clear itself.
    prior = prior_manifest.get("wasm_build") or {}

    if rebuild:
        wasm_build = {
            "note": "sha256 of the upstream sources the vendored WASM bundle is "
                    "compiled from. Written by `sync --rebuild-wasm`, which built "
                    "the bundle in the same run. `check --upstream` fails if any "
                    "of them has changed since.",
            "rebuild": WASM_REBUILD_CMD,
            "built_by_this_script": True,
            "toolchain": toolchain_versions(upstream),
            "sources": {rel: (sha256(upstream / rel) if (upstream / rel).exists() else None)
                        for rel in WASM_SOURCES},
        }
    else:
        wasm_build = prior or None

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "upstream": str(upstream),
        "note": "Vendored from the core agent. Do not edit by hand — "
                "run scripts/sync_upstream.py sync.",
        "artifacts": {local: {"sha256": digest, "bytes": size}
                      for local, digest, size in copied},
        **({"wasm_build": wasm_build} if wasm_build else {}),
    }, indent=2) + "\n", encoding="utf-8", newline="\n")
    # newline="\n" because .gitattributes stores everything here as LF. Without
    # it a sync run on Windows writes CRLF, and the working tree stops being
    # byte-identical to the blob CI checks out — in the one file whose whole job
    # is recording exact bytes.

    total = sum(size for _, _, size in copied)
    print(f"{GREEN}synced{RESET} {len(copied)} artifacts ({total:,} bytes) from {upstream}")
    if carried:
        # Printed every run, like the `check --upstream` skips. A sync that
        # quietly declines to sync part of what it lists is worse than one that
        # fails: the summary line would say 43 artifacts and mean 36.
        print(f"{YELLOW}kept{RESET} {len(carried)} artifact(s) the upstream checkout "
              f"does not carry — hashes unchanged, not re-copied:")
        for local, why in carried:
            print(f"  {local}  ({why})")
    if rebuild:
        print(f"{GREEN}recorded{RESET} {len(wasm_build['sources'])} WASM build-input "
              f"hashes for a bundle built by this run")
        tc = wasm_build.get("toolchain") or {}
        if tc:
            print("         toolchain: " + ", ".join(f"{k} {v}" for k, v in tc.items()))
        else:
            print(f"{YELLOW}         could not determine the build toolchain{RESET}")
    elif wasm_build:
        print(f"{YELLOW}note{RESET}: carried forward the existing WASM build-input "
              f"hashes. This run did not rebuild the bundle, so it cannot vouch "
              f"for it. Use --rebuild-wasm to refresh them.")
    else:
        print(f"{YELLOW}note{RESET}: no WASM build-input hashes recorded — "
              f"`check --upstream` will fail until you run with --rebuild-wasm.")
    for local, digest, size in copied:
        print(f"  {DIM}{digest[:12]}{RESET}  {size:>7,}  {local}")
    if peers:
        for name, root in sorted(peers.items()):
            n = len([m for m in mirrored if m.startswith(f"{name}:")])
            print(f"{GREEN}mirrored{RESET} {n} artifacts into {name} ({root})")
    else:
        print(f"{YELLOW}note{RESET}: no --peer given — the generator's mirrors were "
              f"not updated. If a vendored file changed, `check --peer` will now "
              f"report drift until you re-run with --peer.")

    print(f"\nmanifest -> {MANIFEST.relative_to(ROOT)}")
    return 0


def do_check(upstream: Path | None, peers: dict[str, Path] | None) -> int:
    if not MANIFEST.exists():
        print(f"{RED}no manifest{RESET} at {MANIFEST} — run `sync` first")
        return 1

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    recorded = manifest.get("artifacts", {})
    problems: list[str] = []
    skipped: list[str] = []
    checked = 0

    for up, local, peer_rel in ARTIFACTS:
        here = ROOT / local

        if local not in recorded:
            problems.append(f"{local}: vendored but absent from MANIFEST.json "
                            f"(add it to ARTIFACTS, then sync)")
            continue
        if not here.exists():
            problems.append(f"{local}: missing on disk")
            continue

        digest = sha256(here)
        checked += 1

        if digest != recorded[local]["sha256"]:
            problems.append(
                f"{local}: edited since sync\n"
                f"      manifest {recorded[local]['sha256'][:16]}  "
                f"actual {digest[:16]}\n"
                f"      regenerate with: {hint_for(local)}")

        if upstream and local in UNCOMPARABLE_UPSTREAM:
            skipped.append(f"{local}: {UNCOMPARABLE_UPSTREAM[local]}")
        elif upstream:
            src = upstream / up
            if not src.exists():
                problems.append(
                    f"{local}: upstream source missing ({up}).\n"
                    f"      If it is a build output or gitignored upstream, it cannot be\n"
                    f"      compared against a checkout — say so in UNCOMPARABLE_UPSTREAM\n"
                    f"      rather than removing it from ARTIFACTS.")
            elif sha256(src) != digest:
                problems.append(
                    f"{local}: DRIFTED from upstream\n"
                    f"      upstream {sha256(src)[:16]}  here {digest[:16]}\n"
                    f"      fix with: python scripts/sync_upstream.py sync")

        for name, root in (peers or {}).items():
            rel = (peer_rel or {}).get(name)
            if not rel:
                continue
            mirror = root / rel
            if not mirror.exists():
                problems.append(f"{local}: {name} mirror missing ({rel})")
            elif sha256(mirror) != digest:
                problems.append(
                    f"{local}: {name} mirror DRIFTED ({rel})\n"
                    f"      {name} {sha256(mirror)[:16]}  here {digest[:16]}")

    # ── WASM build inputs ───────────────────────────────────────────────────
    # A built artifact cannot drift from itself, so the artifact hashes above
    # cannot detect a stale bundle. These can.
    if upstream:
        wasm_build = manifest.get("wasm_build")
        if not wasm_build:
            problems.append(
                "wasm/obc-planner/: MANIFEST.json records no build inputs, so the\n"
                "      bundle cannot be shown to match the planner it claims to be a\n"
                "      build of. This is the state the manifest was in when the\n"
                "      vendored bundle was 17 days behind src/deployment/planner.rs.\n"
                "      fix with: python scripts/sync_upstream.py sync \\\n"
                "                    --upstream <core> --peer <generator> --rebuild-wasm")
        else:
            recorded_src = wasm_build.get("sources", {})
            for rel in WASM_SOURCES:
                src = upstream / rel
                if not src.exists():
                    problems.append(f"wasm build input missing upstream: {rel}")
                    continue
                was = recorded_src.get(rel)
                now = sha256(src)
                if was is None:
                    problems.append(
                        f"wasm build input not recorded: {rel}\n"
                        f"      re-run sync after rebuilding the bundle")
                elif was != now:
                    problems.append(
                        f"wasm/obc-planner/: STALE BUILD — {rel} changed since the "
                        f"bundle was built\n"
                        f"      recorded {was[:16]}  upstream now {now[:16]}\n"
                        f"      The vendored .wasm is a build of older sources. It will\n"
                        f"      still hash-match the manifest and still pass every\n"
                        f"      artifact check, and it is still wrong.\n"
                        f"      fix with: python scripts/sync_upstream.py sync \\\n"
                        f"                    --upstream <core> --peer <generator> --rebuild-wasm")

    for rel in undeclared_vendored_files():
        problems.append(
            f"{rel}: present in a vendored tree but absent from ARTIFACTS.\n"
            f"      Either it was retired upstream and this copy should go, or it\n"
            f"      was added here by hand. Both are drift; neither is visible to\n"
            f"      a hash check, because nothing is hashing it.")

    if skipped:
        print(f"{DIM}not compared against upstream ({len(skipped)}):{RESET}")
        for k in skipped:
            print(f"  {DIM}-{RESET} {k}")
        print()

    scope = ["manifest"]
    if upstream:
        scope += ["upstream", "wasm build inputs"]
    for name in sorted(peers or {}):
        scope.append(name)

    if problems:
        print(f"{RED}drift detected{RESET} ({checked} artifacts checked "
              f"against {', '.join(scope)}):\n")
        for p in problems:
            print(f"  {RED}x{RESET} {p}")
        print(f"\n{len(problems)} problem(s). The three planner implementations "
              f"can no longer be assumed to agree.")
        return 1

    print(f"{GREEN}ok{RESET}: {checked} artifacts identical across {', '.join(scope)}")
    if not upstream:
        print(f"{YELLOW}note{RESET}: no --upstream given — only verified that "
              f"vendored files match the manifest, not that the manifest is current")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["sync", "check"])
    ap.add_argument("--upstream", help="path to the core agent repo")
    # Repeatable and named: --peer generator=../OBC-deployment-generator
    #                       --peer accelerapp=../Accelerapp
    #
    # A bare path still works and means the generator, so every existing
    # invocation and the CI job keep running unchanged.
    ap.add_argument("--peer", action="append", default=[], metavar="NAME=PATH",
                    help="a mirror to check, as name=path (repeatable). A bare "
                         "path is taken as generator=<path>.")
    ap.add_argument("--rebuild-wasm", action="store_true",
                    help="(sync) run wasm-pack in the upstream repo first, then "
                         "record the build-input hashes. The only way the manifest "
                         "gets a wasm_build block.")
    args = ap.parse_args()

    raw = list(args.peer)
    if not raw:
        env = resolve(None, "OBC_PEER", "peer", required=False)
        if env:
            raw = [str(env)]
    peers: dict[str, Path] = {}
    for item in raw:
        name, sep, path = item.partition("=")
        if not sep:
            name, path = "generator", item
        resolved = resolve(path, None, name, required=True)
        if resolved is None:
            return 1
        peers[name] = resolved

    if args.mode == "sync":
        return do_sync(
            resolve(args.upstream, "OBC_UPSTREAM", "upstream", required=True),
            peers or None,
            rebuild=args.rebuild_wasm,
        )
    return do_check(
        resolve(args.upstream, "OBC_UPSTREAM", "upstream", required=False),
        peers or None,
    )


if __name__ == "__main__":
    sys.exit(main())
