#!/usr/bin/env python3
"""check_vendored_mods.py — a vendored file's modules are vendored too.

Why this exists
---------------
On 2026-08-21 upstream added `firmware/obc-esp32-s3/src/board.rs` and a
`mod board;` in `main.rs`. `sync_upstream.py sync` copied the changed `main.rs`
and did not copy `board.rs`, because `ARTIFACTS` is an explicit list and nobody
had added it. `check` then reported **"223 artifacts identical"** and exited 0.

It was telling the truth. Every file it names *was* identical. The file it does
not name was invisible to it, and what had been vendored was a firmware tree
that declares a module it does not contain — one that cannot build.

Nothing else would have caught it. No CI anywhere compiles this crate; that is
the whole reason the host-side shims exist. `sync_upstream.py` says in its own
comment that "adding a vendored file anywhere without adding it here is the
exact failure mode this script exists to prevent" — which was right, and was a
comment rather than a check.

What it checks
--------------
Every vendored `.rs` file, for `mod NAME;` declarations. If the declaring file
is vendored, the module's source must be vendored too — `NAME.rs` or
`NAME/mod.rs` beside it. `#[path = "..."]` includes are resolved against the
declaring file's directory and checked the same way.

That is deliberately narrower than "the manifest covers every file upstream
has". Plenty of upstream files are *deliberately* not vendored, so a directory
sweep would be a list of decisions rather than a list of faults. A `mod` that
resolves to nothing is never a decision.

What it deliberately does not check
-----------------------------------
* **`mod` inside `#[cfg(...)]`.** Still checked — a module compiled only under
  one feature is still a file that must exist for that feature to build.
* **`mod NAME { ... }`** — an inline module has no separate file. Matched by
  requiring the `;`.
* **Whether the file *compiles*.** It cannot; that is the standing condition
  this whole family of scripts works around.

Run:  python scripts/check_vendored_mods.py
      python scripts/check_vendored_mods.py --selftest
"""

from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sync_upstream import ARTIFACTS  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent

# `mod name;` — the trailing semicolon is what makes it a *file* module rather
# than an inline `mod name { .. }`. Leading attributes/visibility are skipped by
# anchoring on the keyword at a word boundary.
MOD = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+([A-Za-z_]\w*)\s*;", re.M)
# `#[path = "../elsewhere/file.rs"]` immediately preceding a `mod`.
PATH_ATTR = re.compile(r'#\s*\[\s*path\s*=\s*"([^"]+)"\s*\]\s*(?:[^;{]*?)\bmod\s+([A-Za-z_]\w*)\s*;')


def vendored_paths() -> set[str]:
    return {local for _up, local, _peer in ARTIFACTS}


def missing_for(local: str, text: str, vendored: set[str]) -> list[str]:
    """Modules declared by `local` whose source is not vendored."""
    here = pathlib.PurePosixPath(local).parent
    out: list[str] = []

    explicit = {}
    for rel, name in PATH_ATTR.findall(text):
        target = (here / rel)
        explicit[name] = str(pathlib.PurePosixPath(*target.parts)).replace("\\", "/")

    for name in MOD.findall(text):
        if name in explicit:
            candidates = [normalise(explicit[name])]
        else:
            candidates = [f"{here}/{name}.rs", f"{here}/{name}/mod.rs"]
        if not any(c in vendored for c in candidates):
            out.append(f"{local}: `mod {name};` -> none of {candidates} is vendored")
    return out


def normalise(p: str) -> str:
    parts: list[str] = []
    for part in p.split("/"):
        if part == "..":
            if parts:
                parts.pop()
        elif part not in ("", "."):
            parts.append(part)
    return "/".join(parts)


SELFTEST = [
    ("the omission that caused this",
     "firmware/obc-esp32-s3/src/main.rs", "mod board;\nfn main() {}",
     {"firmware/obc-esp32-s3/src/main.rs"}, False),
    ("the same declaration, vendored",
     "firmware/obc-esp32-s3/src/main.rs", "mod board;\nfn main() {}",
     {"firmware/obc-esp32-s3/src/main.rs", "firmware/obc-esp32-s3/src/board.rs"}, True),
    ("an inline module needs no file",
     "a/src/lib.rs", "mod helpers { pub fn f() {} }", {"a/src/lib.rs"}, True),
    ("a directory module",
     "a/src/lib.rs", "pub mod net;", {"a/src/lib.rs", "a/src/net/mod.rs"}, True),
    ("a cfg-gated module still needs its file",
     "a/src/lib.rs", '#[cfg(feature = "x")]\nmod extra;', {"a/src/lib.rs"}, False),
    ("a #[path] include resolved against the declaring file",
     "demo/src/bench.rs", '#[path = "../../firmware/obc-esp32-s3/src/safety.rs"]\nmod fw;',
     {"demo/src/bench.rs", "firmware/obc-esp32-s3/src/safety.rs"}, True),
    ("a #[path] include pointing at nothing vendored",
     "demo/src/bench.rs", '#[path = "../../firmware/obc-esp32-s3/src/gone.rs"]\nmod fw;',
     {"demo/src/bench.rs"}, False),
]


def selftest() -> int:
    failed = []
    for label, local, text, vendored, want_pass in SELFTEST:
        got_pass = not missing_for(local, text, vendored)
        if got_pass != want_pass:
            failed.append(f"{label}: expected {'pass' if want_pass else 'FAIL'}, got the other")
    print(f"selftest: {len(SELFTEST) - len(failed)}/{len(SELFTEST)} cases behave as stated")
    for line in failed:
        print("  x " + line)
    if failed:
        return 1
    print("ok: the gate tells a declared module that is vendored from one that is not")
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()

    vendored = vendored_paths()
    rust = sorted(p for p in vendored if p.endswith(".rs"))
    missing: list[str] = []
    declared = 0

    for local in rust:
        path = ROOT / local
        if not path.exists():
            missing.append(f"{local}: vendored but not present in this tree")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        declared += len(MOD.findall(text))
        missing.extend(missing_for(local, text, vendored))

    print(
        f"checked {declared} module declaration(s) across {len(rust)} vendored "
        f"Rust file(s)"
    )
    if missing:
        print("\nvendored files declaring modules that were not vendored with them:")
        for entry in missing:
            print("  x " + entry)
        print(
            "\nAdd the file to ARTIFACTS in scripts/sync_upstream.py and re-run\n"
            "`sync`. A manifest gate can only compare the files it is told about."
        )
        return 1
    print("ok: every module a vendored file declares is vendored beside it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
