#!/usr/bin/env python3
"""check_doc_links.py — every relative link in this repo's own prose resolves.

Why this exists
---------------
On 2026-08-02 `docs/SAFETY.md` §6 said `See [SECURITY.md](../SECURITY.md)`.
There is no `SECURITY.md` in this repository — the line was written against the
upstream tree and pointed at nothing here from the day the file arrived. Nobody
noticed, because reading a document does not resolve its links and GitHub
renders a dead relative link as an ordinary one.

The same pass found `docs/playbooks/vision-analytics.md` missing while the
reference-body quickstart printed its path on screen. That one was a missing
file rather than a wrong link, and this gate would have caught it the moment
anything linked to it.

What it checks
--------------
Every `[text](target)` in every tracked `.md` file that this repository wrote,
against the file list of the commit itself. Absolute URLs are not fetched — a
link checker that needs the network is a link checker that goes red on a
Tuesday for reasons nobody caused.

What it deliberately skips
--------------------------
* **Vendored prose.** `firmware/lora-node/README.md`, `docs/playbooks/*.md` and
  friends are byte-identical copies of upstream files; their relative paths
  mean the *upstream* tree, and this repository must not edit them to make a
  checker happy. The list comes from `sync_upstream.ARTIFACTS`, not from a
  hardcoded prefix, so a newly vendored document is skipped without anyone
  remembering to add it here.
* **Code spans.** A link quoted inside backticks is a citation, not a link.
  Without stripping those first, this file's own docstring and the note in
  `SAFETY.md` §6 explaining the broken link would both read as broken links,
  forever.

Run:  python scripts/check_doc_links.py
"""

from __future__ import annotations

import io
import os
import pathlib
import re
import subprocess
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sync_upstream import ARTIFACTS  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent

LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
FENCE = re.compile(r"^```.*?^```", re.S | re.M)
INLINE = re.compile(r"`[^`\n]*`")


def commit_files() -> tuple[dict[str, bytes], set[str]]:
    """Every tracked file at HEAD, read from an export rather than the tree.

    Verifying against the working directory would let an untracked local file
    satisfy a link that a fresh clone cannot follow — which is the exact
    failure this is meant to catch.
    """
    out = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "--format=zip", "HEAD"],
        capture_output=True,
    )
    if out.returncode != 0:
        sys.exit("git archive failed: " + out.stderr.decode(errors="replace"))
    zf = zipfile.ZipFile(io.BytesIO(out.stdout))
    names = set(zf.namelist())
    docs = {n: zf.read(n) for n in names if n.endswith(".md")}
    return docs, names


def main() -> int:
    docs, names = commit_files()
    vendored = {local for _up, local, _peer in ARTIFACTS}

    targets = sorted(n for n in docs if n not in vendored)
    broken: list[str] = []
    checked = 0

    for name in targets:
        text = docs[name].decode("utf-8", errors="replace")
        text = INLINE.sub("``", FENCE.sub("", text))
        base = pathlib.PurePosixPath(name).parent
        for match in LINK.finditer(text):
            href = match.group(1)
            if href.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = os.path.normpath(str(base / href)).replace("\\", "/")
            checked += 1
            if resolved in names:
                continue
            if any(n.startswith(resolved + "/") for n in names):
                continue  # a directory link
            broken.append(f"{name}: [{href}] -> {resolved}")

    skipped = len(docs) - len(targets)
    print(
        f"checked {checked} relative links across {len(targets)} markdown files "
        f"({skipped} vendored file(s) skipped)"
    )
    if broken:
        print("\nbroken links (target not in this commit):")
        for entry in broken:
            print("  x " + entry)
        return 1
    print("ok: every relative link resolves inside the commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
