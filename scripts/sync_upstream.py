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
        also updates the generator app's mirrors (12 of the 215 artifacts).
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
    # The receiver's half of the same scheme (2026-08-01). `replay` is the
    # anti-replay window — RFC 4303 §3.4.3 rather than a high-water mark,
    # because this mesh's flood relay delivers duplicates by design and
    # re-orders across paths, so strict monotonicity would drop its own traffic
    # as an attack. `frame_auth` is key, tag and window as one decision, plus
    # the outbound counter that makes signing safe across a restart.
    #
    # Both are pure logic and run here: `cargo test -p obc-safety` is where the
    # public repo checks the authentication its own SPINE-AUTH.md specifies.
    ("crates/obc-safety/src/replay.rs",
     "crates/obc-safety/src/replay.rs",
     None),
    ("crates/obc-safety/src/frame_auth.rs",
     "crates/obc-safety/src/frame_auth.rs",
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
    # `SecretString` — a redact-in-Debug, redact-in-Display wrapper whose only
    # escape hatch is a greppable `.expose()`. It lived in the core repo's
    # `config::secret` until 2026-08-13 and moved here because it is secret
    # *hygiene* rather than configuration, and this crate already owns the vault.
    #
    # It moved for a concrete reason rather than a tidy one. `ProviderConfig`
    # holds an `Option<SecretString>`, and that struct needed to move into the
    # providers module to break a dependency cycle — one struct defined in
    # `config` while two of its own field types lived in `providers` and all ten
    # provider files imported it back. Moving the struct without moving this
    # type would have recreated the edge it was meant to remove.
    #
    # This entry exists because `check --upstream` demanded it. The file
    # appeared in a tree this repository vendors whole, and the gate said so:
    # "Nothing here is a copy of it and nothing here is checking it. Silence is
    # the one option that is not available." Second live catch for that check;
    # the first was obc-conscience's decision_log.
    ("crates/obc-safety/src/secret.rs",
     "crates/obc-safety/src/secret.rs",
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
    # `NodeState` — the heartbeat every other layer reads — moved here from the
    # core repo's `fleet` module on 2026-08-06. It is telemetry a coordinator
    # consumes, not coordination, and being defined inside the coordinator was
    # the single edge that kept `aerial` and `gnss` from extracting at all.
    ("crates/obc-telemetry/src/node.rs",
     "crates/obc-telemetry/src/node.rs",
     None),

    # ── Where a node actually is ─────────────────────────────────────────────
    # Vendored 2026-08-06, pieces eight and nine, and the first pair unlocked by
    # a change made on purpose rather than found already loose: the `NodeState`
    # move above took both from one blocking edge to zero, and upstream's
    # `scripts/extractability.py` said so before the crate existed.
    #
    # One crate rather than two because they are one pattern — a real-world
    # position report (MAVLink-style geodetic telemetry, or a raw NMEA 0183 GGA
    # sentence) projected through a site frame into the node state the fleet
    # coordinates on. Neither knows the coordinator exists, which is what lets a
    # drone and a bare u-blox module join the same auction as a ground robot.
    ("crates/obc-position/Cargo.toml",
     "crates/obc-position/Cargo.toml",
     None),
    ("crates/obc-position/src/lib.rs",
     "crates/obc-position/src/lib.rs",
     None),
    ("crates/obc-position/src/aerial.rs",
     "crates/obc-position/src/aerial.rs",
     None),
    ("crates/obc-position/src/gnss.rs",
     "crates/obc-position/src/gnss.rs",
     None),

    # ── Token accounting, and the tunnel ─────────────────────────────────────
    # Pieces ten and eleven, both vendored 2026-08-06 and both the same shape:
    # each named exactly one thing outside itself — its own config block, in the
    # core repo's root config module — so the config struct travelled with the
    # code that reads it. That is the arrangement obc-planner
    # (`DeploymentConfig`) and obc-conscience (`ConscienceConfig`) already use.
    #
    # A note on how these arrived. When they merged upstream, `check --upstream`
    # here stayed green — because the gate compares *declared* artifacts, and a
    # crate nobody has declared has nothing to compare. It catches a vendored
    # file edited here, a vendored file that drifted upstream, and an undeclared
    # file sitting in a vendored tree. It does not catch a new crate upstream
    # that should be vendored and is not. That gap is closed by a person
    # noticing, which is exactly the kind of dependency this repository keeps
    # finding and writing down.
    ("crates/obc-cost/Cargo.toml",
     "crates/obc-cost/Cargo.toml",
     None),
    ("crates/obc-cost/src/lib.rs",
     "crates/obc-cost/src/lib.rs",
     None),
    ("crates/obc-cost/src/config.rs",
     "crates/obc-cost/src/config.rs",
     None),
    ("crates/obc-cost/src/types.rs",
     "crates/obc-cost/src/types.rs",
     None),
    ("crates/obc-cost/src/tracker.rs",
     "crates/obc-cost/src/tracker.rs",
     None),

    ("crates/obc-tunnel/Cargo.toml",
     "crates/obc-tunnel/Cargo.toml",
     None),
    ("crates/obc-tunnel/src/lib.rs",
     "crates/obc-tunnel/src/lib.rs",
     None),
    ("crates/obc-tunnel/src/config.rs",
     "crates/obc-tunnel/src/config.rs",
     None),
    ("crates/obc-tunnel/src/cloudflare.rs",
     "crates/obc-tunnel/src/cloudflare.rs",
     None),
    ("crates/obc-tunnel/src/tailscale.rs",
     "crates/obc-tunnel/src/tailscale.rs",
     None),

    # ── Being reachable by other agents ──────────────────────────────────────
    # Vendored 2026-08-08, the twelfth crate: Google's Agent-to-Agent v1.0 —
    # the wire types, the JSON-RPC task lifecycle, and the HTTP transport that
    # makes an agent discoverable and callable.
    #
    # It is here later than it could have been, on purpose. It was upstream's
    # cleanest extraction candidate for months — zero edges to anything else in
    # the agent — and that was the same fact from the other side: nothing named
    # it either. `src/main.rs` referenced it zero times, `src/gateway/` zero
    # times, and flipping its `pub` off so `dead_code` could see it produced 34
    # items never constructed. 791 conformant, tested lines implementing a
    # server nobody could start.
    #
    # Vendoring that would have been worse here than upstream: in a public
    # repository an unreachable protocol implementation reads as a feature.
    # It was given an entry point first (`oh-ben-claw a2a-serve`, dispatch to
    # the real agent, and a read of the `[a2a]` config block that had never
    # been read by anything), and arrives now that it does something.
    #
    # Two files, and the crate is genuinely two files: the executor that calls
    # the agent lives upstream in `src/a2a_agent.rs`, implementing a trait this
    # crate declares. That is what keeps the crate free of agent dependencies,
    # and it is why the extraction moved 0 lines.
    ("crates/obc-a2a/Cargo.toml",
     "crates/obc-a2a/Cargo.toml",
     None),
    ("crates/obc-a2a/src/lib.rs",
     "crates/obc-a2a/src/lib.rs",
     None),

    # ── The act side of the loop ─────────────────────────────────────────────
    # Vendored 2026-08-08, the thirteenth crate: typed movement commands
    # bounded by the deterministic Track 0 gate *before* they reach hardware,
    # recorded into bitemporal world memory as `actuator.{name}` facts, and
    # dispatched through a pluggable sink.
    #
    # docs/SAFETY.md has described this bound since it was written. obc-safety
    # brought the gate here on 2026-08-01; this brings the caller that is
    # supposed to be using it, so the sentence "every command is bounded before
    # it actuates" is now two vendored crates that can be run against each
    # other rather than one crate and a claim.
    #
    # It was blocked for months by one edge — `Arc<SpineClient>` in a single
    # `ActuatorSink` implementation, one field and one constructor parameter.
    # Upstream turned it on 2026-08-08 by moving that sink to the spine, where
    # it implements this crate's trait from the other side. 39 lines. Behind it
    # `navigation` (3714 lines) went to zero blocking edges and is next.
    ("crates/obc-movement/Cargo.toml",
     "crates/obc-movement/Cargo.toml",
     None),
    ("crates/obc-movement/src/lib.rs",
     "crates/obc-movement/src/lib.rs",
     None),
    ("crates/obc-movement/src/feedback.rs",
     "crates/obc-movement/src/feedback.rs",
     None),

    # ── Knowing where you are and how to get somewhere ───────────────────────
    # Vendored 2026-08-08, the fourteenth crate and the largest: Monte Carlo
    # localization against a beam model and likelihood field, pose-graph SLAM
    # with loop closure and graph relaxation, occupancy grids, inflation cost
    # maps, A* with an admissible heuristic, frontier exploration, and pose
    # fusion across odometry, scan matching and an external fix.
    #
    # The README's "Navigation / SLAM" row has claimed all of that for months
    # against code this repository could not compile. It can now, which is the
    # same correction obc-movement made to docs/SAFETY.md the same day.
    #
    # Worth recording how it got here, because the size is misleading. It was
    # blocked by one edge (`movement`), which was blocked by one edge (`spine`),
    # which was one `Arc<SpineClient>` field in a single actuator sink. 39 lines
    # turned that edge upstream; obc-movement followed; this crate — six times
    # the size — followed with no design work and four of its nine files
    # byte-identical. An extraction queue is a queue of edges, not of jobs.
    ("crates/obc-navigation/Cargo.toml",
     "crates/obc-navigation/Cargo.toml",
     None),
    ("crates/obc-navigation/src/lib.rs",
     "crates/obc-navigation/src/lib.rs",
     None),
    ("crates/obc-navigation/src/particle.rs",
     "crates/obc-navigation/src/particle.rs",
     None),
    ("crates/obc-navigation/src/sensor_model.rs",
     "crates/obc-navigation/src/sensor_model.rs",
     None),
    ("crates/obc-navigation/src/slam.rs",
     "crates/obc-navigation/src/slam.rs",
     None),
    ("crates/obc-navigation/src/planning.rs",
     "crates/obc-navigation/src/planning.rs",
     None),
    ("crates/obc-navigation/src/costmap.rs",
     "crates/obc-navigation/src/costmap.rs",
     None),
    ("crates/obc-navigation/src/exploration.rs",
     "crates/obc-navigation/src/exploration.rs",
     None),
    ("crates/obc-navigation/src/mapping.rs",
     "crates/obc-navigation/src/mapping.rs",
     None),
    ("crates/obc-navigation/src/pose_fusion.rs",
     "crates/obc-navigation/src/pose_fusion.rs",
     None),

    # ── The contract every tool is checked against ───────────────────────────
    # Vendored 2026-08-12, the fifteenth crate and the smallest at 175 lines:
    # the `Tool` trait, `ToolResult`, the `Arc<dyn Tool>` blanket impl, and the
    # Track 0 vocabulary (risk class, blast radius, rollout stage, output trust)
    # that the approval layer and safety gate evaluate a tool against.
    #
    # This is the most useful thing here for someone who wants to *write*
    # something rather than read about it: it is the contract, with no
    # implementation attached. `obc-safety` is the other half — the gate that
    # reads `risk_class()` and decides.
    #
    # It is also the first crate extracted for a reason other than "it was
    # separable". Upstream's `tools` module is 9052 lines and sits in several of
    # the cycles that make the agent core unextractable; 30 of the core's 117
    # measured crossings were this one file, because `agent`, `gateway` and
    # `spine` all needed the contract and had to name the whole module to get
    # it. See docs/ENDGAME.md upstream.
    ("crates/obc-tool-api/Cargo.toml",
     "crates/obc-tool-api/Cargo.toml",
     None),
    ("crates/obc-tool-api/src/lib.rs",
     "crates/obc-tool-api/src/lib.rs",
     None),

    # ── System 1 ─────────────────────────────────────────────────────────────
    # Vendored 2026-08-12, the sixteenth crate: the reflex engine. A rule is
    # *when this condition holds, do this action*, evaluated against world
    # memory with debounce, rate limits and an escalation budget, and no LLM in
    # the loop. `Action::Escalate` is the one that wakes System 2.
    #
    # This is the half of the README's reflex claim that has been missing since
    # obc-telemetry arrived. That entry, five crates ago, said so in as many
    # words: "the reflex *engine* is in the core crate's `agent/` behind
    # thirteen blocking edges and cannot follow yet, so this backs
    # perceive-and-classify, not the whole sentence." The sentence is now whole
    # — `bodies/trailwatch`'s escalation text, the firmware's `src/reflex.rs`
    # already vendored here, and the host evaluator that mirrors it are finally
    # in one repository.
    #
    # Thirteen edges became one, and then none. The last was `SpineActionSink`:
    # one field, one constructor parameter, two topic constants, moved upstream
    # to `src/spine/action.rs` where it implements this crate's `ActionSink`
    # from the other side. Same manoeuvre that freed obc-movement (a sink) and
    # obc-a2a (an executor) — the trait stays where the abstraction is, the
    # implementation goes where the dependency is.
    #
    # One test did not come with it. `content_relayed_by_a_trusted_writer_is_
    # now_gated` needs the tool layer to say what it means, so it is an
    # integration test upstream now rather than a unit test here. The count in
    # the README moves by less than the crate's size suggests, for that reason.
    ("crates/obc-reflex/Cargo.toml",
     "crates/obc-reflex/Cargo.toml",
     None),
    ("crates/obc-reflex/src/lib.rs",
     "crates/obc-reflex/src/lib.rs",
     None),

    # ── Track 1, and the layer that writes its own rules ─────────────────────
    # Vendored 2026-08-13, the seventeenth and eighteenth crates, and neither
    # was chosen. Both fell out of obc-reflex landing the day before.
    #
    # `obc-foresight` is the predictive half of the control stack. Reflexes
    # react to the present; this reacts to a forecast. World memory is
    # bitemporal and append-only, so every entity carries a time-series — fit
    # the recent trend and you can say *when* a value will cross a threshold.
    # `battery predicted <= 10% within 60s -> return to base` fires while the
    # pack is still at 20% and draining, which is time a reactive rule cannot
    # buy. Forecasts are written back into world memory under
    # `foresight.{entity}`, so a rule that fired on a bad forecast leaves the
    # bad forecast behind as evidence.
    #
    # `obc-learning` is the layer that authors rules from experience rather than
    # from an operator: it mines the history for conditions that repeatedly
    # preceded a bad outcome and proposes anticipatory rules with a support
    # count and a confidence measured against the background rate. The thing
    # that makes it safe to ship publicly is what it deliberately does not do —
    # a proposal is inert until a human or policy approves it, and only then is
    # it converted, escalate-only, into a foresight rule. That invariant is
    # asserted upstream in `tests/learning_approval_gate.rs` against a real
    # `ForesightEngine`, which is why the test stayed there when the crate left,
    # and why this crate's own count is only 4.
    #
    # The chain is the point. learning was blocked by foresight, which was
    # blocked by reflex, which was blocked by one action sink holding an
    # `Arc<SpineClient>` — one field, one constructor parameter, two topic
    # constants. 2455 lines came out from behind it across three commits, and
    # the two crates here moved no logic at all: eight `crate::memory::world::`
    # paths became `obc_memory::`, names that had been a crate since 2026-07-30
    # and were still being read through the agent's re-export table.
    #
    # One dependency was found by the compiler and would have been missed by any
    # survey: obc-learning needs `anyhow`, which appears in no `use` line —
    # both call sites write `anyhow::Result<…>` inline in a return type. That is
    # the same shape that made upstream's `extractability.py` report `config` as
    # edge-free in its first version. `cargo check -p obc-learning` found it in
    # seconds, which is the whole argument for the crates-alone job below.
    ("crates/obc-foresight/Cargo.toml",
     "crates/obc-foresight/Cargo.toml",
     None),
    ("crates/obc-foresight/src/lib.rs",
     "crates/obc-foresight/src/lib.rs",
     None),
    ("crates/obc-learning/Cargo.toml",
     "crates/obc-learning/Cargo.toml",
     None),
    ("crates/obc-learning/src/lib.rs",
     "crates/obc-learning/src/lib.rs",
     None),

    # ── Three crates that came out of cutting cycles ─────────────────────────
    # Vendored 2026-08-13: the nineteenth, twentieth and twenty-first. They
    # arrived differently from everything above them, and the difference is the
    # story of the day upstream.
    #
    # Every crate before these left because it was *separable* — measured, found
    # loose, moved. These three were not loose. They came out of a deliberate
    # attack on the dependency cycles in the core, and each one was released by
    # turning a single edge around:
    #
    #   obc-fleet    a 60-line MQTT bridge sitting in the coordinator. Moved to
    #                the spine, where the transport is, and where `lora_mesh`
    #                was already bridging the *other* transport into the same
    #                coordinator from that side. The same integration had been
    #                built from both ends and only one end was the transport.
    #
    #   obc-audio    two `SpeechSink` implementations, one holding a
    #                `SpineClient` and one holding a `TextToSpeechTool`. The
    #                trait stayed; the implementations went to the spine and the
    #                tool layer. `LoggingSpeechSink` stayed too, because it
    #                depends on nothing, which is exactly what qualifies it as
    #                the safe default.
    #
    #   obc-mission  nothing, in the end. It reached zero blocking edges the
    #                moment obc-audio left — it had been holding an
    #                `AudioController` so a mission can speak.
    #
    # `obc-fleet` is the coordinator: a node registry, a task auction that
    # allocates by cost rather than by turn, and frontier exploration with a
    # minimum separation so two robots do not crowd one pocket. `NodeState`
    # comes from obc-telemetry, which is why that crate is a dependency here.
    #
    # `obc-audio` is hearing and speaking recorded into world memory as facts
    # with an `Origin`, so what the agent *said* is evidence on the same footing
    # as what it heard.
    #
    # `obc-mission` is an ordered sequence of guarded steps advanced against
    # world memory, so a multi-step job survives a restart and can say where it
    # got to.
    #
    # A note on what is *not* claimed. Upstream's cycle count went from 25 to
    # sixteen across this work, not to zero — a measurement script was reporting
    # zero because of a regex bug that made every edge into the config module
    # invisible. That is written up in upstream's docs/ENDGAME.md rather than
    # summarised here, because a number this repository cannot re-run is a
    # number it should not print.
    ("crates/obc-fleet/Cargo.toml",
     "crates/obc-fleet/Cargo.toml",
     None),
    ("crates/obc-fleet/src/lib.rs",
     "crates/obc-fleet/src/lib.rs",
     None),

    ("crates/obc-audio/Cargo.toml",
     "crates/obc-audio/Cargo.toml",
     None),
    ("crates/obc-audio/src/lib.rs",
     "crates/obc-audio/src/lib.rs",
     None),
    ("crates/obc-audio/src/suite.rs",
     "crates/obc-audio/src/suite.rs",
     None),

    ("crates/obc-mission/Cargo.toml",
     "crates/obc-mission/Cargo.toml",
     None),
    ("crates/obc-mission/src/lib.rs",
     "crates/obc-mission/src/lib.rs",
     None),

    # ── The human-in-the-loop gate ───────────────────────────────────────────
    # Vendored 2026-08-14, the twenty-second, and the first one extracted after
    # the core reached zero cycles rather than in order to get there.
    #
    # What it is: three autonomy levels -- full, supervised, manual -- and a
    # per-call gate that consults a tool's declared risk class before asking a
    # person. A grant can be given once or forever, and forever grants are
    # persisted, so "yes, always" survives a restart rather than quietly meaning
    # "yes, until you reboot". It also carries the trust half: a tool's output
    # has an `OutputTrust`, and relayed content from an untrusted writer does
    # not get the same standing as a driver-measured reading. `obc-safety`'s
    # taint guard, already here, is the other end of that.
    #
    # It is worth being exact about why this crate is in a public repository
    # that documents a robot's safety story. The claim "a human approves risky
    # actions" is the kind a reader cannot check by reading prose about it, and
    # thirty tests that run here are a different sort of evidence from a
    # paragraph saying they exist. That argument is the same one that put
    # obc-safety and obc-conscience here.
    #
    # How it reached zero blocking edges, in two steps, neither found by
    # reading:
    #
    #   1. `crate::config::paths::in_data_dir` -- where forever grants are
    #      written -- was naming upstream's root config module to reach
    #      obc-paths, a crate since July. A facade nobody had noticed was one.
    #   2. `AutonomyLevel` and `AutonomyConfig` spent an hour in `agent` before
    #      landing here, and the cycle count refused to reach zero the whole
    #      time. Autonomy *level* is the approval policy, and this is the module
    #      that turns it into an `ApprovalManager`. The rule was right and the
    #      noun was wrong; the graph said so before any reader did.
    #
    # Four dependencies in its manifest exist because the compiler asked, not
    # because an import survey found them: chrono, uuid and tracing appear in no
    # `use` line -- seven call sites write them at full paths -- and tempfile was
    # invisible to `cargo check -p` entirely, surfacing only under
    # `--all-targets` because the grants-persistence test writes to a temp dir.
    # Both halves of the crates-alone CI job below earn their runtime again.
    ("crates/obc-approval/Cargo.toml",
     "crates/obc-approval/Cargo.toml",
     None),
    ("crates/obc-approval/src/lib.rs",
     "crates/obc-approval/src/lib.rs",
     None),

    # ── The communication spine ──────────────────────────────────────────────
    # Vendored 2026-08-14, the twenty-third, 5100 lines, and the largest thing
    # that had ever been extracted from upstream's tree. It is also the host
    # half of a claim this repository has been making with only the node half
    # present.
    #
    # firmware/ has been here in full for weeks: the ESP32 and Heltec sources
    # implement the frame authentication docs/SPINE-AUTH.md specifies -- tag,
    # replay window, outbound counter -- and a reader could check that end.
    # The brain end was described and not shown. Both ends are here now, and
    # `cargo test -p obc-spine` runs 63 of them.
    #
    # What it is: the MQTT backbone between brain and nodes, a serial LoRa
    # gateway and a LoRa mesh with a relay, the mesh supervisor that decides a
    # node is lost, a P2P transport over TCP and UDP, and four sinks that put
    # movement commands, reflex actions, speech and fleet assignments onto the
    # wire.
    #
    # It never had a refactor, which is the part worth reading. Its
    # blocking-edge count went four to zero without a line of its own code
    # changing, because all four edges were the same mistake made four times --
    # an implementation living beside the abstraction it implements rather than
    # beside the dependency it holds. SpineActuatorSink left `movement`,
    # SpineActionSink left the agent's reflex module, the fleet bridge left the
    # coordinator, SpineSpeechSink left the audio suite. Each move released a
    # module that then became a crate, and three of those four crates are above
    # this entry. The spine did not get smaller; it stopped pointing.
    #
    # One thing this vendoring carries that is not code. Upstream's security
    # audit went red on the extraction, and not because anything new arrived:
    # the new manifest declared `rumqttc = "0.24"` where the root had
    # `default-features = false` under a comment naming four RUSTSEC advisories
    # in rustls-webpki 0.102.8. Cargo unifies features across a workspace, so
    # one manifest asking for defaults re-enabled a vulnerable certificate
    # stack for everything -- for MQTT-over-TLS, which is never wired. Build,
    # clippy, fmt and the full suite stayed green. The manifest below is the
    # corrected one, and `cargo audit` is why anyone knew.
    ("crates/obc-spine/Cargo.toml",
     "crates/obc-spine/Cargo.toml",
     None),
    ("crates/obc-spine/src/lib.rs",
     "crates/obc-spine/src/lib.rs",
     None),
    ("crates/obc-spine/src/action.rs",
     "crates/obc-spine/src/action.rs",
     None),
    ("crates/obc-spine/src/actuator.rs",
     "crates/obc-spine/src/actuator.rs",
     None),
    ("crates/obc-spine/src/fleet_bridge.rs",
     "crates/obc-spine/src/fleet_bridge.rs",
     None),
    ("crates/obc-spine/src/lora_gateway.rs",
     "crates/obc-spine/src/lora_gateway.rs",
     None),
    ("crates/obc-spine/src/lora_mesh.rs",
     "crates/obc-spine/src/lora_mesh.rs",
     None),
    ("crates/obc-spine/src/mesh_supervisor.rs",
     "crates/obc-spine/src/mesh_supervisor.rs",
     None),
    ("crates/obc-spine/src/p2p.rs",
     "crates/obc-spine/src/p2p.rs",
     None),
    ("crates/obc-spine/src/speech.rs",
     "crates/obc-spine/src/speech.rs",
     None),


    # ── Model Context Protocol, both directions ──────────────────────────────
    # Vendored 2026-08-14, and the two directions are not the same claim.
    #
    # The client dials out -- stdio to a local server, HTTP to a remote one --
    # and presents whatever it finds as tools the agent can call. That is how
    # the system acquires capability nobody wrote into it.
    #
    # The server points the other way: it exposes this agent's own tools over
    # MCP, so something else can drive a robot *through* the Track 0 gate rather
    # than around it. That is why the crate depends on obc-conscience. An MCP
    # server is an ingress, and reach and observation are gated on the way in as
    # well as on the way out -- a claim `docs/CONSCIENCE.md` makes and, until
    # this crate arrived, made about code that was not here.
    ("crates/obc-mcp/Cargo.toml",
     "crates/obc-mcp/Cargo.toml",
     None),
    ("crates/obc-mcp/src/client.rs",
     "crates/obc-mcp/src/client.rs",
     None),
    ("crates/obc-mcp/src/lib.rs",
     "crates/obc-mcp/src/lib.rs",
     None),
    ("crates/obc-mcp/src/server.rs",
     "crates/obc-mcp/src/server.rs",
     None),

    # ── The model backends ───────────────────────────────────────────────────
    # Vendored 2026-08-14. Anthropic, OpenAI, OpenRouter, Ollama and a generic
    # OpenAI-compatible backend behind one trait, with an ordered failover chain
    # so a dead endpoint moves to the next rather than failing the turn,
    # bounded retries, SSE streaming, and a registry that pins model names.
    #
    # This page has said "bring your own model" since its first paragraph, and
    # until now nothing here could be run to check it. The claim is not that a
    # provider exists -- it is the fallback chain, the retry bound and the
    # pinned registry, which are the parts that decide whether the promise holds
    # when a key is wrong or an endpoint is down. Twenty-two tests assert them
    # here.
    #
    # Upstream it was the first module in that tree to reach zero edges of any
    # kind, and it got there without being touched: it was blocked by one edge
    # into tools, and tools by one edge into the spine.
    ("crates/obc-providers/Cargo.toml",
     "crates/obc-providers/Cargo.toml",
     None),
    ("crates/obc-providers/src/anthropic.rs",
     "crates/obc-providers/src/anthropic.rs",
     None),
    ("crates/obc-providers/src/compatible.rs",
     "crates/obc-providers/src/compatible.rs",
     None),
    ("crates/obc-providers/src/failover.rs",
     "crates/obc-providers/src/failover.rs",
     None),
    ("crates/obc-providers/src/lib.rs",
     "crates/obc-providers/src/lib.rs",
     None),
    ("crates/obc-providers/src/model_registry.rs",
     "crates/obc-providers/src/model_registry.rs",
     None),
    ("crates/obc-providers/src/ollama.rs",
     "crates/obc-providers/src/ollama.rs",
     None),
    ("crates/obc-providers/src/openai.rs",
     "crates/obc-providers/src/openai.rs",
     None),
    ("crates/obc-providers/src/openrouter.rs",
     "crates/obc-providers/src/openrouter.rs",
     None),
    ("crates/obc-providers/src/retry.rs",
     "crates/obc-providers/src/retry.rs",
     None),
    ("crates/obc-providers/src/streaming.rs",
     "crates/obc-providers/src/streaming.rs",
     None),

    # ── The tool layer ───────────────────────────────────────────────────────
    # Vendored 2026-08-14, the twenty-fourth crate here and the largest: 8880
    # lines across twenty-nine files.
    #
    # `obc-tool-api` has been here since 2026-08-06 as the contract with no
    # implementation -- the `Tool` trait, `ToolResult`, and the Track 0
    # vocabulary a tool declares about itself. This is what implements it:
    # movement, navigation, vision, audio, mesh, shell, files, HTTP, a browser,
    # world memory, missions, incidents, OTA and the rest, each declaring its
    # own risk class to the gate that reads it.
    #
    # The pairing is the argument for vendoring it. A reader could already see
    # `obc-safety` refuse a command, and could see the vocabulary a tool uses to
    # describe itself, but not a single real tool declaring one. Both halves of
    # "the model may only call what the gate allows" are checkable now.
    #
    # Upstream it was the largest module in the tree and the last thing standing
    # between five other modules and extraction, and when it was measured rather
    # than estimated it turned out to be the loosest: all sixty-three of its
    # outward references pointed at crates that had already left, and none at a
    # module still in the tree.
    ("crates/obc-tools/Cargo.toml",
     "crates/obc-tools/Cargo.toml",
     None),
    ("crates/obc-tools/src/builtin/aerial.rs",
     "crates/obc-tools/src/builtin/aerial.rs",
     None),
    ("crates/obc-tools/src/builtin/audio.rs",
     "crates/obc-tools/src/builtin/audio.rs",
     None),
    ("crates/obc-tools/src/builtin/audio_speech.rs",
     "crates/obc-tools/src/builtin/audio_speech.rs",
     None),
    ("crates/obc-tools/src/builtin/audio_suite.rs",
     "crates/obc-tools/src/builtin/audio_suite.rs",
     None),
    ("crates/obc-tools/src/builtin/browser.rs",
     "crates/obc-tools/src/builtin/browser.rs",
     None),
    ("crates/obc-tools/src/builtin/comms.rs",
     "crates/obc-tools/src/builtin/comms.rs",
     None),
    ("crates/obc-tools/src/builtin/file.rs",
     "crates/obc-tools/src/builtin/file.rs",
     None),
    ("crates/obc-tools/src/builtin/fleet.rs",
     "crates/obc-tools/src/builtin/fleet.rs",
     None),
    ("crates/obc-tools/src/builtin/foresight.rs",
     "crates/obc-tools/src/builtin/foresight.rs",
     None),
    ("crates/obc-tools/src/builtin/gnss.rs",
     "crates/obc-tools/src/builtin/gnss.rs",
     None),
    ("crates/obc-tools/src/builtin/http.rs",
     "crates/obc-tools/src/builtin/http.rs",
     None),
    ("crates/obc-tools/src/builtin/incident.rs",
     "crates/obc-tools/src/builtin/incident.rs",
     None),
    ("crates/obc-tools/src/builtin/learn.rs",
     "crates/obc-tools/src/builtin/learn.rs",
     None),
    ("crates/obc-tools/src/builtin/memory.rs",
     "crates/obc-tools/src/builtin/memory.rs",
     None),
    ("crates/obc-tools/src/builtin/mesh.rs",
     "crates/obc-tools/src/builtin/mesh.rs",
     None),
    ("crates/obc-tools/src/builtin/mission.rs",
     "crates/obc-tools/src/builtin/mission.rs",
     None),
    ("crates/obc-tools/src/builtin/mod.rs",
     "crates/obc-tools/src/builtin/mod.rs",
     None),
    ("crates/obc-tools/src/builtin/movement.rs",
     "crates/obc-tools/src/builtin/movement.rs",
     None),
    ("crates/obc-tools/src/builtin/navigation.rs",
     "crates/obc-tools/src/builtin/navigation.rs",
     None),
    ("crates/obc-tools/src/builtin/ota.rs",
     "crates/obc-tools/src/builtin/ota.rs",
     None),
    ("crates/obc-tools/src/builtin/power.rs",
     "crates/obc-tools/src/builtin/power.rs",
     None),
    ("crates/obc-tools/src/builtin/sensing.rs",
     "crates/obc-tools/src/builtin/sensing.rs",
     None),
    ("crates/obc-tools/src/builtin/shell.rs",
     "crates/obc-tools/src/builtin/shell.rs",
     None),
    ("crates/obc-tools/src/builtin/site_anchor.rs",
     "crates/obc-tools/src/builtin/site_anchor.rs",
     None),
    ("crates/obc-tools/src/builtin/siteplan.rs",
     "crates/obc-tools/src/builtin/siteplan.rs",
     None),
    ("crates/obc-tools/src/builtin/vision.rs",
     "crates/obc-tools/src/builtin/vision.rs",
     None),
    ("crates/obc-tools/src/builtin/world.rs",
     "crates/obc-tools/src/builtin/world.rs",
     None),
    ("crates/obc-tools/src/credentials.rs",
     "crates/obc-tools/src/credentials.rs",
     None),
    ("crates/obc-tools/src/lib.rs",
     "crates/obc-tools/src/lib.rs",
     None),

    # ── The agent watching itself ────────────────────────────────────────────
    # Vendored 2026-08-02, the sixth crate. `obc-telemetry` above is the agent
    # watching its *body*; this is the instrumentation of the software — spans,
    # the bounded span ring buffer, and the counters the gateway's
    # `/api/v1/metrics` serves. The two are one word apart and easy to confuse,
    # which is why both Cargo.toml files say so.
    #
    # Upstream compiled it in a scratch crate against nothing but its six
    # external dependencies before extracting it, so "self-contained" was a
    # compiler's verdict rather than a survey's. That is also why it is only two
    # files: one module, no submodules.
    ("crates/obc-observability/Cargo.toml",
     "crates/obc-observability/Cargo.toml",
     None),
    ("crates/obc-observability/src/lib.rs",
     "crates/obc-observability/src/lib.rs",
     None),

    # ── The scheduler ────────────────────────────────────────────────────────
    # Vendored 2026-08-06. The last module upstream's extractability survey
    # listed with zero blocking edges; everything after it needs an edge turned
    # around first. Cron, interval and one-shot tasks in SQLite.
    #
    # It is also the crate that writes `<agent name>` and its `-wal`/`-shm`
    # sidecars — three of which were committed into `bodies/trailwatch/` here
    # and shipped for six days. Its own manifest upstream records that.
    ("crates/obc-scheduler/Cargo.toml",
     "crates/obc-scheduler/Cargo.toml",
     None),
    ("crates/obc-scheduler/src/lib.rs",
     "crates/obc-scheduler/src/lib.rs",
     None),

    # ── The perception & reach gate ──────────────────────────────────────────
    # Vendored 2026-08-06, and the reason this sync is not routine.
    #
    # `docs/CONSCIENCE.md` has been on this repository's public main since
    # 2026-08-04, describing a consent registry, an egress allowlist and audited
    # refusals as wired and live — and citing `crates/obc-conscience/examples/`,
    # a path that did not exist here or upstream. The code was real; it sat on a
    # branch whose PR had already merged, 21 commits ahead of every main, where
    # nothing was going to notice it.
    #
    # This repository's README already names the pattern: SAFETY.md,
    # BELIEF-REVISION.md and MEMORY-2026-07.md "all arrived before their code,
    # which is the wrong order and is now corrected for all three." CONSCIENCE.md
    # was the fourth, and this entry is that correction.
    #
    # The crate depends on serde, serde_json and tracing and nothing else, so
    # `cargo test --workspace` here runs the gate itself — not a description of
    # it. That is the whole reason crates/ exists in a repository that cannot
    # run the agent.
    ("crates/obc-conscience/Cargo.toml",
     "crates/obc-conscience/Cargo.toml",
     None),
    ("crates/obc-conscience/src/lib.rs",
     "crates/obc-conscience/src/lib.rs",
     None),
    ("crates/obc-conscience/src/classifier.rs",
     "crates/obc-conscience/src/classifier.rs",
     None),
    ("crates/obc-conscience/src/consent.rs",
     "crates/obc-conscience/src/consent.rs",
     None),
    ("crates/obc-conscience/src/multiparty.rs",
     "crates/obc-conscience/src/multiparty.rs",
     None),
    ("crates/obc-conscience/src/reach.rs",
     "crates/obc-conscience/src/reach.rs",
     None),
    ("crates/obc-conscience/src/replay.rs",
     "crates/obc-conscience/src/replay.rs",
     None),
    ("crates/obc-conscience/src/detector_eval.rs",
     "crates/obc-conscience/src/detector_eval.rs",
     None),
    # Moved into the crate upstream on 2026-08-08 from the private runtime's
    # src/decision_log.rs. It is the sink the crate's own header has always
    # demanded ("a conscience that isn't audited is just a promise") and never
    # shipped: the crate defined DecisionRecord, replayed it and computed the
    # config fingerprint, but could neither write a log nor read one back.
    # docs/CONSCIENCE.md documented the JSONL format here with no code here to
    # check it against.
    #
    # Worth recording how this entry came to be added: `check --upstream` found
    # the file. It was the first live use of undeclared_upstream_files(), added
    # two days earlier after `check --upstream` printed ok while obc-cost and
    # obc-tunnel were missing entirely. The old gate would have said ok again.
    ("crates/obc-conscience/src/decision_log.rs",
     "crates/obc-conscience/src/decision_log.rs",
     None),

    # The sample frames, ledgers and decision logs the crate's own docs point at
    # as runnable. Declared individually because VENDORED_TREES fails on any
    # undeclared file under crates/ — which is the rule working: a fixture that
    # drifts from upstream is a fixture that stops demonstrating what it claims.
    ("crates/obc-conscience/examples/sample-consent-frame.json",
     "crates/obc-conscience/examples/sample-consent-frame.json",
     None),
    ("crates/obc-conscience/examples/sample-consent-ledger.json",
     "crates/obc-conscience/examples/sample-consent-ledger.json",
     None),
    ("crates/obc-conscience/examples/sample-decision-log.json",
     "crates/obc-conscience/examples/sample-decision-log.json",
     None),
    ("crates/obc-conscience/examples/sample-decision-log.jsonl",
     "crates/obc-conscience/examples/sample-decision-log.jsonl",
     None),
    ("crates/obc-conscience/examples/sample-eval-frames.json",
     "crates/obc-conscience/examples/sample-eval-frames.json",
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

    # ── The triage playbooks ─────────────────────────────────────────────────
    # Vendored 2026-08-02, because the reference bodies already cite them. The
    # escalation text a reflex attaches when it wakes System 2 ends with
    # "Full playbook: docs/playbooks/vision-analytics.md" — and that string is
    # printed on screen by `bodies/trailwatch`, the quickstart on the front
    # page of this repository, within two seconds of a first-ever run. Until
    # now the file it named was not here. The public repo told a new reader to
    # go read a document it did not have.
    #
    # The reason strings live in the agent's reflex rules, which are not in
    # this repository, so this side is the side that can be fixed.
    #
    # Vendored verbatim, like the firmware: they are upstream's prose about
    # upstream's rules, and editing them here would put this copy in the same
    # position `crates/obc-memory/src/image.rs` was in. Where they point into
    # `src/`, they mean the core repo. `docs/playbooks/README.md` says so, and
    # is this repository's own file — see VENDORED_TREES below.
    ("docs/playbooks/vision-analytics.md",
     "docs/playbooks/vision-analytics.md",
     None),
    ("docs/playbooks/mesh-node-lost.md",
     "docs/playbooks/mesh-node-lost.md",
     None),
    ("docs/playbooks/safing-escalations.md",
     "docs/playbooks/safing-escalations.md",
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
    # Only the playbooks subtree, not docs/ — everything else under docs/ is
    # written here. Same shape as firmware: one local README, the rest vendored.
    "docs/playbooks": {"docs/playbooks/README.md"},
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


# Upstream trees that are vendored whole, mapped to upstream paths inside them
# that are deliberately not vendored. Empty set means "every tracked file here
# must be declared".
#
# This is undeclared_vendored_files() pointed the other way, and it exists
# because the first direction was not enough. On 2026-08-06 obc-cost and
# obc-tunnel were extracted upstream. `check --upstream` printed ok, because
# every artifact it knew about was still correct -- and it knew about no file in
# either crate. Two entire crates had appeared in the thing this repository
# claims to mirror, and the mirror-checker said the mirror was fine.
#
# ARTIFACTS answers "is everything we declared still correct".
# undeclared_vendored_files answers "is everything present still declared".
# Neither can answer "is everything upstream present at all". This can.
UPSTREAM_TREES: dict[str, set[str]] = {
    "crates": {
        # ── Deliberately not vendored, 2026-08-14 ────────────────────────────
        # An entry ending in `/` is a directory prefix. That is the only
        # granularity at which this decision is real: "obc-agent is not
        # vendored" is one decision about one crate, and spelling it as fifteen
        # file paths would mean re-deciding it every time upstream adds a file
        # -- noise, not signal, from a gate whose whole value is that its
        # failures mean something.
        #
        # These four sit above a line drawn on purpose. Everything this
        # repository vendors, it vendors because a document here makes a claim
        # a reader cannot check by reading it: obc-safety backs SAFETY.md,
        # obc-conscience backs CONSCIENCE.md, obc-spine is the host half of the
        # frame authentication the firmware already implements. The tool layer
        # and the model backends below join them on the same argument.
        #
        # These do not. The agent loop, the self-improvement layer, the
        # configuration that composes every module's block, and the peripheral
        # drivers are not evidence for a claim -- they are most of the product.
        # Vendoring them would turn this repository from "the substrate the
        # documents rest on" into "the agent, minus the binary", which is a
        # different project with a different promise.
        #
        # Recorded rather than omitted, because the check that produced this
        # list says so: add it to ARTIFACTS and sync, or record that it is
        # deliberately not vendored. Silence is the one option not available,
        # and a reader is owed the line and the reason for it.
        "crates/obc-agent/",
        "crates/obc-skill-forge/",
        "crates/obc-config/",
        "crates/obc-peripherals/",
    },
}


def undeclared_upstream_files(upstream: Path) -> list[str]:
    """Tracked upstream files inside a vendored-whole tree that ARTIFACTS omits.

    Uses `git ls-files` rather than a filesystem walk so that build output and
    anything else upstream ignores does not read as a missing artifact. If git
    is unavailable the check reports that fact instead of silently passing --
    a check that cannot run must not look like a check that ran.
    """
    declared = {up for up, _local, _peer in ARTIFACTS}
    found: list[str] = []
    for tree, skip in UPSTREAM_TREES.items():
        if not (upstream / tree).is_dir():
            continue
        try:
            out = subprocess.run(
                ["git", "-C", str(upstream), "ls-files", "--", tree],
                capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            found.append(f"{tree}/: cannot list upstream files ({exc})")
            continue
        if out.returncode != 0:
            found.append(f"{tree}/: `git ls-files` failed upstream "
                         f"({out.stderr.strip() or out.returncode})")
            continue
        for rel in sorted(line.strip() for line in out.stdout.splitlines()):
            if not rel or rel in declared:
                continue
            if rel in skip or any(s.endswith("/") and rel.startswith(s)
                                  for s in skip):
                continue
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
        # fails: on 2026-07-30 the summary line would have said 43 artifacts
        # and meant 36.
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

    if upstream:
        for rel in undeclared_upstream_files(upstream):
            problems.append(
                f"{rel}: exists upstream in a tree this repository vendors whole,\n"
                f"      but no ARTIFACTS entry names it. Nothing here is a copy of it\n"
                f"      and nothing here is checking it. Add it to ARTIFACTS and sync,\n"
                f"      or record in UPSTREAM_TREES that it is deliberately not\n"
                f"      vendored. Silence is the one option that is not available.")

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
