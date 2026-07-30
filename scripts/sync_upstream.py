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

# (path in upstream core repo, path here, path in the generator app or None)
#
# Keep this list as the single declaration of what is vendored. Adding a
# vendored file anywhere without adding it here is the exact failure mode this
# script exists to prevent.
ARTIFACTS: list[tuple[str, str, str | None]] = [
    ("registry/registry.json",
     "registry/registry.json",
     "lib/registry.json"),

    ("tests/fixtures/deployment/nanopi/inventory.json",
     "parity/fixtures/deployment/nanopi/inventory.json",
     "tests/fixtures/deployment/nanopi/inventory.json"),
    ("tests/fixtures/deployment/nanopi/expected-deployment.toml",
     "parity/fixtures/deployment/nanopi/expected-deployment.toml",
     "tests/fixtures/deployment/nanopi/expected-deployment.toml"),
    # The whole generated config, not just its [deployment] block. Added after the
    # narrower golden was found to have hidden a real divergence for months.
    ("tests/fixtures/deployment/nanopi/expected-config.toml",
     "parity/fixtures/deployment/nanopi/expected-config.toml",
     "tests/fixtures/deployment/nanopi/expected-config.toml"),
    ("tests/fixtures/siteplan/square/case.json",
     "parity/fixtures/siteplan/square/case.json",
     "tests/fixtures/siteplan/square/case.json"),
    ("tests/fixtures/siteplan/square/expected-site.toml",
     "parity/fixtures/siteplan/square/expected-site.toml",
     "tests/fixtures/siteplan/square/expected-site.toml"),

    ("planner-wasm/pkg/obc_planner_wasm_bg.wasm",
     "wasm/obc-planner/obc_planner_wasm_bg.wasm",
     "wasm/obc-planner/obc_planner_wasm_bg.wasm"),
    ("planner-wasm/pkg/obc_planner_wasm.js",
     "wasm/obc-planner/obc_planner_wasm.js",
     "wasm/obc-planner/obc_planner_wasm.js"),
    ("planner-wasm/pkg/obc_planner_wasm.d.ts",
     "wasm/obc-planner/obc_planner_wasm.d.ts",
     "wasm/obc-planner/obc_planner_wasm.d.ts"),
    ("planner-wasm/pkg/obc_planner_wasm_bg.wasm.d.ts",
     "wasm/obc-planner/obc_planner_wasm_bg.wasm.d.ts",
     "wasm/obc-planner/obc_planner_wasm_bg.wasm.d.ts"),
    ("planner-wasm/pkg/package.json",
     "wasm/obc-planner/package.json",
     "wasm/obc-planner/package.json"),

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
    ("crates/obc-memory/src/image.rs",
     "crates/obc-memory/src/image.rs",
     None),
    ("crates/obc-memory/src/journal.rs",
     "crates/obc-memory/src/journal.rs",
     None),
    ("crates/obc-memory/src/vector.rs",
     "crates/obc-memory/src/vector.rs",
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
    "planner-wasm/Cargo.toml",
    "planner-wasm/src/lib.rs",
    "planner-wasm/src/deployment/mod.rs",
    "planner-wasm/src/peripherals/mod.rs",
    "src/geo/mod.rs",
    "src/siteplan/mod.rs",
    "src/deployment/advisor.rs",
    "src/deployment/firmware_scaffold.rs",
    "src/deployment/inventory.rs",
    "src/deployment/planner.rs",
    "src/deployment/scheme.rs",
    "src/peripherals/registry.rs",
]

WASM_REBUILD_CMD = "wasm-pack build planner-wasm --target nodejs"

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


def resolve(flag: str | None, env: str, what: str, required: bool) -> Path | None:
    raw = flag or os.environ.get(env)
    if not raw:
        if required:
            sys.exit(f"{RED}error{RESET}: --{what} not given and {env} not set")
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


def do_sync(upstream: Path, peer: Path | None = None, rebuild: bool = False) -> int:
    if rebuild and not rebuild_wasm(upstream):
        return 1
    copied, missing, mirrored = [], [], []
    for up, local, peer_rel in ARTIFACTS:
        src, dst = upstream / up, ROOT / local
        if not src.exists():
            missing.append(up)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append((local, sha256(dst), dst.stat().st_size))

        # The generator carries its own copy of 11 of these. `sync` used to write
        # only this repo, so a rebuilt WASM landed here and the generator kept the
        # old one — `check --peer` then reported drift that `sync` could not fix,
        # and the documented remedy ("fix with: sync") was wrong for that case.
        if peer and peer_rel:
            mirror = peer / peer_rel
            mirror.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, mirror)
            mirrored.append(peer_rel)

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
    prior = {}
    if MANIFEST.exists():
        try:
            prior = json.loads(MANIFEST.read_text(encoding="utf-8")).get("wasm_build") or {}
        except (json.JSONDecodeError, OSError):
            prior = {}

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
    }, indent=2) + "\n", encoding="utf-8")

    total = sum(size for _, _, size in copied)
    print(f"{GREEN}synced{RESET} {len(copied)} artifacts ({total:,} bytes) from {upstream}")
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
    if peer:
        print(f"{GREEN}mirrored{RESET} {len(mirrored)} artifacts into {peer}")
    else:
        print(f"{YELLOW}note{RESET}: no --peer given — the generator's mirrors were "
              f"not updated. If a vendored file changed, `check --peer` will now "
              f"report drift until you re-run with --peer.")

    print(f"\nmanifest -> {MANIFEST.relative_to(ROOT)}")
    return 0


def do_check(upstream: Path | None, peer: Path | None) -> int:
    if not MANIFEST.exists():
        print(f"{RED}no manifest{RESET} at {MANIFEST} — run `sync` first")
        return 1

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    recorded = manifest.get("artifacts", {})
    problems: list[str] = []
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

        if upstream:
            src = upstream / up
            if not src.exists():
                problems.append(f"{local}: upstream source missing ({up})")
            elif sha256(src) != digest:
                problems.append(
                    f"{local}: DRIFTED from upstream\n"
                    f"      upstream {sha256(src)[:16]}  here {digest[:16]}\n"
                    f"      fix with: python scripts/sync_upstream.py sync")

        if peer and peer_rel:
            mirror = peer / peer_rel
            if not mirror.exists():
                problems.append(f"{local}: peer mirror missing ({peer_rel})")
            elif sha256(mirror) != digest:
                problems.append(
                    f"{local}: peer mirror DRIFTED ({peer_rel})\n"
                    f"      peer {sha256(mirror)[:16]}  here {digest[:16]}")

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

    scope = ["manifest"]
    if upstream:
        scope += ["upstream", "wasm build inputs"]
    if peer:
        scope.append("peer")

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
    ap.add_argument("--peer", help="path to the deployment generator repo")
    ap.add_argument("--rebuild-wasm", action="store_true",
                    help="(sync) run wasm-pack in the upstream repo first, then "
                         "record the build-input hashes. The only way the manifest "
                         "gets a wasm_build block.")
    args = ap.parse_args()

    if args.mode == "sync":
        return do_sync(
            resolve(args.upstream, "OBC_UPSTREAM", "upstream", required=True),
            resolve(args.peer, "OBC_PEER", "peer", required=False),
            rebuild=args.rebuild_wasm,
        )
    return do_check(
        resolve(args.upstream, "OBC_UPSTREAM", "upstream", required=False),
        resolve(args.peer, "OBC_PEER", "peer", required=False),
    )


if __name__ == "__main__":
    sys.exit(main())
