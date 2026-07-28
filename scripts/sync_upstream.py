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
    python scripts/sync_upstream.py sync    --upstream <path-to-core-repo>
    python scripts/sync_upstream.py check   [--upstream <path>] [--peer <path>]

`sync`  copies upstream -> here and rewrites parity/MANIFEST.json.
`check` verifies, in order:
          1. every vendored file matches the manifest hash   (always)
          2. every vendored file matches upstream            (if --upstream)
          3. every peer mirror matches too                   (if --peer)
        Exits non-zero on any mismatch. This is the CI gate.

Paths may also come from OBC_UPSTREAM / OBC_PEER environment variables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
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

# How each artifact is produced upstream. Printed on drift so the fix is
# obvious instead of requiring archaeology.
REGENERATE = {
    "registry/registry.json": "cargo run --bin emit-registry",
    "wasm/obc-planner/": "wasm-pack build planner-wasm --target web",
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


def do_sync(upstream: Path) -> int:
    copied, missing = [], []
    for up, local, _peer in ARTIFACTS:
        src, dst = upstream / up, ROOT / local
        if not src.exists():
            missing.append(up)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append((local, sha256(dst), dst.stat().st_size))

    if missing:
        print(f"{RED}missing upstream artifacts:{RESET}")
        for m in missing:
            print(f"  {m}")
        return 1

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "upstream": str(upstream),
        "note": "Vendored from the core agent. Do not edit by hand — "
                "run scripts/sync_upstream.py sync.",
        "artifacts": {local: {"sha256": digest, "bytes": size}
                      for local, digest, size in copied},
    }, indent=2) + "\n", encoding="utf-8")

    total = sum(size for _, _, size in copied)
    print(f"{GREEN}synced{RESET} {len(copied)} artifacts ({total:,} bytes) from {upstream}")
    for local, digest, size in copied:
        print(f"  {DIM}{digest[:12]}{RESET}  {size:>7,}  {local}")
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

    scope = ["manifest"]
    if upstream:
        scope.append("upstream")
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
    args = ap.parse_args()

    if args.mode == "sync":
        return do_sync(resolve(args.upstream, "OBC_UPSTREAM", "upstream", required=True))
    return do_check(
        resolve(args.upstream, "OBC_UPSTREAM", "upstream", required=False),
        resolve(args.peer, "OBC_PEER", "peer", required=False),
    )


if __name__ == "__main__":
    sys.exit(main())
