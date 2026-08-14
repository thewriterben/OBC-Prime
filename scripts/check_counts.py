#!/usr/bin/env python3
"""check_counts.py — every number this repository states about itself is current.

Why this exists
---------------
Three times in two days a count in this repository's own prose was wrong, and
each time it was wrong the same way: stated as part of an *argument* rather than
as data, so nobody updating "the numbers" thought to look at it.

  On 2026-08-13 a sync raised the substrate to twenty-one crates and updated the
  README from 632 tests to 653 — and missed `Cargo.toml` ("executes 473 tests of
  real agent code", the six-crate era) and `demo/src/main.rs` ("'589 tests
  pass'").

  On 2026-08-13 the commit that added a gate for *that* still left
  `parity/README.md` saying the sync "copies all 43 artifacts here, updates the
  generator's 11 mirrors" — 157 and 12 — plus both figures in
  `sync_upstream.py`'s own docstring.

(Those two paragraphs carry dates because this script flags itself otherwise.
That is not a workaround: a line quoting a number in order to correct it is a
historical record, which is precisely what the date is for.)

The first version of this script checked test counts in four named files. It
could not have caught the second batch: wrong metric, wrong files. This one
derives the numbers and the file set instead of being told them.

One more thing it caught, about itself
--------------------------------------
It ran green every time before it was committed and went red immediately after.
`our_files()` reads `git ls-files`, so while this script was untracked it was
excluding *itself* from the scan. A gate that behaves differently either side of
`git add` is a trap, and this one was carrying five of its own violations at the
moment it was declared working.

The fix is the dates above. The lesson is that "I ran it and it passed" and "it
passes in CI" are different claims, and the gap between them is exactly one
`git add`.

What it checks
--------------
Three counts, each measured rather than remembered — tests (from harness
output), artifacts (`len(sync_upstream.ARTIFACTS)`), and generator mirrors
(ARTIFACTS entries carrying a `generator` peer) — against every tracked text
file this repository *wrote*.

What it deliberately does not check, and why
--------------------------------------------
A gate with false positives is a gate someone turns off, so the exclusions are
as important as the checks:

* **Vendored files.** Their prose belongs upstream. The list comes from
  ARTIFACTS, not a path prefix, so a newly vendored document is skipped without
  anyone remembering to add it.

* **The logs.** `PLAN.md`, `docs/DECISIONS.md` and `docs/MIGRATION.md` are
  append-only records. Their numbers are historical *by construction* — PLAN.md
  literally annotates itself ("> 2026-08-02: 96 artifacts, not 10") — and
  rewriting them to match today would destroy the thing they exist to hold.

* **Dated lines, and lines under a dated heading.** Same rule, applied to the
  files that are mostly live prose but carry some history.

* **Other repositories' counts.** `parity/README.md` states the generator's
  npm test count next to this workspace's cargo one. Both are correct; only one
  is about this repo.

Every exclusion above was added because the first run produced a false positive,
not in anticipation. Twelve of sixteen initial hits were noise.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sync_upstream  # noqa: E402

DATE = re.compile(r"20\d\d-\d\d-\d\d")
HEADING = re.compile(r"^\s*#{1,6}\s")

# Append-only records. See the docstring: their numbers are meant to be old.
LOGS = {"PLAN.md", "docs/DECISIONS.md", "docs/MIGRATION.md"}

SKIP_DIRS = ("wasm/", "registry/", "parity/fixtures/", "firmware-templates/", "target/")
TEXT_SUFFIX = {".md", ".rs", ".toml", ".py", ".yml", ".yaml", ".cjs", ".js", ".sh"}

# Counts belonging to the generator, not to this workspace.
FOREIGN = re.compile(r"npm test|generator's \d+ tests|node_modules")

# `(?<![\d,])` so "1,417 tests" does not read as 417.
PATTERNS = [
    ("tests", re.compile(r"(?<![\d,])(\d{3,4})\s+tests\b|\bexecutes\s+(?<![\d,])(\d{3,4})\b")),
    ("artifacts", re.compile(r"(?<![\d,])(\d{2,4})\s+artifacts?\b")),
    ("mirrors", re.compile(r"generator(?:'s)?\s+(?:also carries\s+)?(\d{1,3})\s+mirrors?\b"
                           r"|\b(\d{1,3})\s+of the \d+ artifacts")),
]


def measured() -> dict[str, int]:
    out = subprocess.run(
        ["cargo", "test", "--workspace"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT,
    )
    tests = 0
    for line in out.stdout.splitlines():
        m = re.match(r"test result: ok\. (\d+) passed; (\d+) failed", line.strip())
        if m:
            if int(m.group(2)):
                sys.exit(f"tests are failing; counts are meaningless\n{line}")
            tests += int(m.group(1))
    if tests == 0:
        sys.exit("no test results parsed -- the harness output format changed")
    return {
        "tests": tests,
        "artifacts": len(sync_upstream.ARTIFACTS),
        "mirrors": sum(1 for _u, _l, p in sync_upstream.ARTIFACTS
                       if p and "generator" in p),
    }


def our_files() -> list[str]:
    vendored = {local for _u, local, _p in sync_upstream.ARTIFACTS}
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=ROOT)
    return [rel for rel in out.stdout.splitlines()
            if rel not in vendored
            and rel not in LOGS
            and not rel.startswith(SKIP_DIRS)
            and Path(rel).suffix in TEXT_SUFFIX]


def stale(rel: str) -> list[tuple[int, str, int, str]]:
    """Counts stated on non-historical lines.

    "Historical" is decided per *paragraph*, not per line. Prose wraps, and a
    dated sentence puts its date on one line and its number on the next — which
    cost two rounds of chasing before the rule was written this way. A
    blank-line-delimited block carrying a date anywhere in it is a record.

    The trade: a long block with one date in it can hide a live number. That is
    the same trade the heading rule already makes, and it is the reason both
    rules prefer small blocks. It is written here rather than discovered again.
    """
    try:
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    # Pre-pass: which paragraph is each line in, and is that paragraph dated?
    para_of, dated_para, para = [], {}, 0
    for line in lines:
        if not line.strip():
            para += 1
        para_of.append(para)
        if DATE.search(line):
            dated_para[para] = True

    hits, dated_section = [], False
    for idx, line in enumerate(lines):
        i = idx + 1
        if HEADING.match(line):
            dated_section = bool(DATE.search(line))
        if dated_section or dated_para.get(para_of[idx]) or FOREIGN.search(line):
            continue
        for name, pat in PATTERNS:
            for m in pat.finditer(line):
                stated = int(next(g for g in m.groups() if g))
                hits.append((i, name, stated, line.strip()))
    return hits


def main() -> int:
    truth = measured()
    print("measured: " + ", ".join(f"{k}={v}" for k, v in truth.items()))

    bad = [(rel, i, n, s, t) for rel in our_files()
           for i, n, s, t in stale(rel) if s != truth[n]]

    for rel, i, name, stated, text in bad:
        print(f"  {rel}:{i}: {name} says {stated}, actual {truth[name]}\n      {text}")

    if bad:
        print(f"\n{len(bad)} stale count(s). Update them, or add a date to the "
              f"line if it is a historical record.")
        return 1
    print("ok: every stated count in this repo's own prose is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
