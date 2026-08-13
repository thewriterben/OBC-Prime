#!/usr/bin/env python3
"""check_test_count.py — every stated test count in this repo's own prose is current.

Why this exists
---------------
On 2026-08-13 a sync raised the vendored substrate from eighteen crates to
twenty-one and updated the README from 632 tests to 653. It missed two other
files stating the same figure:

  * `Cargo.toml`, the workspace header, said **473** — true when six crates
    were vendored, and left behind by every sync since.
  * `demo/src/main.rs`, the one host binary, said **589**.

Both were written as arguments rather than as data ("`cargo test --workspace`
here executes N tests of real agent code", "it exists because 'N tests pass'
and 'you can see it refuse' are different kinds of evidence"), which is exactly
why they were not updated with the count they were arguing from.

The commit that missed them was the commit whose entire purpose was correcting
a stale count. That is the argument for a gate rather than for more care.

What it checks
--------------
Runs the workspace test suite, counts what actually passed, and greps this
repository's own files for a stated count that disagrees. Vendored files are
skipped — their prose belongs to upstream — and dated historical quotations are
skipped by an explicit marker, because "on 2026-08-02 there were 391" is a fact
that must not be updated.

Exits non-zero on any disagreement, naming the file and both numbers.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files this repository wrote that state a workspace test count. Kept explicit:
# a glob would sweep in vendored prose and dated quotations, and both must be
# left alone.
STATERS = [
    "README.md",
    "Cargo.toml",
    "demo/src/main.rs",
    ".github/workflows/parity.yml",
]

# A line carrying a date is a historical record, not a live claim. `PLAN.md`
# annotates its own history this way ("> 2026-08-02: 96 artifacts ... 391
# tests") and those numbers are correct precisely because they are not current.
DATED = re.compile(r"20\d\d-\d\d-\d\d")

COUNT = re.compile(r"\b(\d{3,4})\s+tests\b|\bexecutes\s+(\d{3,4})\b|\"(\d{3,4})\s+tests")


def actual_count() -> int:
    """Unit + doc tests that passed, from the harness rather than from memory."""
    out = subprocess.run(
        ["cargo", "test", "--workspace"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, cwd=ROOT,
    )
    total = 0
    for line in out.stdout.splitlines():
        m = re.match(r"test result: ok\. (\d+) passed; (\d+) failed", line.strip())
        if m:
            if int(m.group(2)):
                sys.exit(f"tests are failing; count is meaningless\n{line}")
            total += int(m.group(1))
    if total == 0:
        sys.exit("no test results parsed -- the harness output format changed")
    return total


def main() -> int:
    n = actual_count()
    print(f"workspace: {n} tests passing")

    bad = []
    for rel in STATERS:
        path = ROOT / rel
        if not path.is_file():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if DATED.search(line):
                continue
            for m in COUNT.finditer(line):
                stated = int(next(g for g in m.groups() if g))
                if stated != n:
                    bad.append((rel, i, stated, line.strip()))

    for rel, i, stated, text in bad:
        print(f"  {rel}:{i}: says {stated}, actual {n}\n      {text}")

    if bad:
        print(f"\n{len(bad)} stale test count(s). Update them, or add a date to "
              f"the line if it is a historical record.")
        return 1
    print(f"ok: every stated test count in this repo's own prose is {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
