#!/usr/bin/env python3
"""check_cited_paths.py — a path cited in an instructional document is either
here, or says whose it is.

Why this exists
---------------
On 2026-08-21 `bodies/benchtop/README.md` cited `docs/SAFETY-CASE.md` and
`docs/BENCH-PINOUT-CARDS.md` in backticks. Both are Oh-Ben-Claw files. In a
document telling someone how to run a bench, they read as files in this
repository, and a reader who went looking would find nothing.

`check_doc_links.py` ran on that file and reported ok. It strips code spans
first, on the reasoning that "a link quoted inside backticks is a citation,
not a link" — right for the case it was built against (`SAFETY.md` §6
explaining a deliberately broken link), and precisely the hole those two
citations went through.

What it checks
--------------
Every backticked token in an *instructional* document that looks like a
repo-relative source path. Each must do one of:

  * resolve at the repository root,
  * resolve relative to the document citing it,
  * resolve as the tail of a tracked path — `src/feedback.rs` in a table row
    about `obc-movement` is a crate-relative citation, not a wrong one,
  * or sit in a paragraph that says which repository it belongs to.

That last one is the point. Every path in this repository's prose that points
somewhere else already carries its attribution: "upstream's `docs/ENDGAME.md`",
"the core repo's `scripts/extractability.py`", "the generator's
`tests/reference-bodies.test.ts`". The convention was already universal. This
gate holds it rather than inventing it.

**Its first run found nothing.** All candidate spans across the six
instructional documents pass, seven of them by attribution. That is the honest
result, and a gate whose first run is green earns its place only if it would
have gone red the day before. This one would have — `--selftest` proves that
against synthetic documents rather than asserting it, and runs in CI beside
the real check.

What it deliberately does not check
-----------------------------------
* **Histories.** `MIGRATION.md`, `DECISIONS.md`, `MEMORY-2026-07.md` and
  `RESEARCH-2026-07.md` name paths that are upstream, moved, or gone — that is
  what those documents are *for*. A probe over the whole tree returned 228
  non-resolving spans and almost every one was correct as written. A
  200-finding gate is a gate someone turns off in a week.
* **Tokens without a slash.** `audit.rs` is a basename under discussion, not a
  path being cited. Requiring a slash drops those, the JSON-RPC method
  `tools/call`, the MQTT topic `obc/nodes/{id}/limits`, and `13/13`-style
  fractions, without anyone maintaining a denylist.
* **Fenced blocks.** A path inside a fence is a transcript or a command, and
  its working directory is whatever the block established.

Known limit: attribution is matched over the citation's own paragraph (its own
row, inside a table). A paragraph that names another repository for one reason
will excuse a dangling path cited for another. That is a deliberate trade — the
alternative is parsing English — and it fails open, which is worth saying out
loud in a repository that spent this week finding places that fail open.

Run:  python scripts/check_cited_paths.py
      python scripts/check_cited_paths.py --selftest
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

# A document that tells someone how to do something *here*. A dangling path in
# one of these misleads a person who is trying to act on it — which is a
# different failure from a history naming a file that has moved.
INSTRUCTIONAL = re.compile(
    r"^(README\.md"
    r"|bodies/README\.md"
    r"|bodies/[^/]+/README\.md"
    r"|firmware/README\.md"
    r"|parity/README\.md"
    r"|demo/README\.md)$"
)

# Suffixes that make a slash-bearing token a *source path* rather than a topic,
# a route, or a version string.
SUFFIX = (
    ".rs", ".py", ".md", ".toml", ".ts", ".tsx", ".js",
    ".yml", ".yaml", ".json", ".svg", ".sh", ".lock",
)

# The vocabulary this repository already uses when it points somewhere else.
# Read off the existing prose, not invented: see README.md §"upstream's
# docs/ENDGAME.md" and bodies/README.md §"In the deployment generator".
ATTRIBUTION = re.compile(
    r"upstream|core repo|Oh-Ben-Claw|OBC-deployment-generator|the generator|generator's",
    re.I,
)

FENCE = re.compile(r"^```.*?^```", re.S | re.M)
SPAN = re.compile(r"`([^`\n]+)`")


def commit_files() -> tuple[dict[str, bytes], set[str]]:
    """Every tracked file at HEAD, from an export rather than the working tree.

    Same reasoning as check_doc_links: an untracked local file must not be able
    to satisfy a citation that a fresh clone cannot follow.
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


def windows(text: str):
    """Yield the units an attribution is allowed to cover.

    A prose paragraph is one unit: the repository's own style puts the
    attribution on the line before the path more often than on the same one.
    A table row is its own unit, so one attributed row cannot excuse the row
    below it.
    """
    # Normalise line endings first. On CRLF the split below would never fire,
    # every document would collapse to a single window, and one "the generator"
    # anywhere in a file would attribute every path in it -- a gate that fails
    # open silently and still prints ok.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for para in FENCE.sub("", text).split("\n\n"):
        lines = para.splitlines()
        if lines and sum(1 for ln in lines if ln.lstrip().startswith("|")) > len(lines) / 2:
            yield from lines
        elif para.strip():
            yield para


def candidates(window: str):
    """Backticked tokens in this window that look like repo-relative paths."""
    for match in SPAN.finditer(window):
        tok = match.group(1).strip().rstrip(".,;:")
        if " " in tok or "/" not in tok or not tok.endswith(SUFFIX):
            continue
        if tok.startswith(("http://", "https://", "~", "$", "/dev/")):
            continue
        yield tok


def resolves(tok: str, doc: str, names: set[str], dirs: set[str]) -> str | None:
    """How this token resolves, or None. The string is for the report."""
    # NOT lstrip("./") — that strips character-wise, so `.cargo/config.toml`
    # becomes `cargo/config.toml` and then matches nothing. It cost this gate a
    # false positive on its first run, which is a cheap place to learn it.
    bare = tok[2:] if tok.startswith("./") else tok
    if bare in names:
        return "at the root"
    if bare in dirs or any(n.startswith(bare + "/") for n in names):
        return "a directory here"
    rel = os.path.normpath(os.path.join(os.path.dirname(doc), tok)).replace("\\", "/")
    if rel in names or rel in dirs or any(n.startswith(rel + "/") for n in names):
        return "relative to the document"
    tail = "/" + bare
    hits = [n for n in names if n.endswith(tail)]
    if len(hits) == 1:
        return f"crate-relative -> {hits[0]}"
    if len(hits) > 1:
        return f"crate-relative, {len(hits)} matches"
    return None


# Each case is (name, window text, should_pass). The first two are the exact
# citation this gate was built for, with and without its attribution: if those
# two ever agree, the gate has stopped discriminating and is decoration.
SELFTEST = [
    ("the citation that caused this",
     "the load-bearing property `docs/SAFETY-CASE.md` §4 calls out", False),
    ("the same citation, attributed",
     "the property upstream's `docs/SAFETY-CASE.md` §4 calls out", True),
    ("the other one",
     "pin map from `docs/BENCH-PINOUT-CARDS.md` Card 2", False),
    ("a path that is genuinely here",
     "the gate lives in `scripts/check_counts.py` and runs in CI", True),
    # `src/feedback.rs` played this part until 2026-09-13, when it was deleted
    # upstream; a selftest fixture that cites a real file is a fixture that
    # can stop being true.
    ("crate-relative, one match",
     "**`src/mushroom.rs` is the sparse-expansion memory** over episode embeddings", True),
    ("attributed to the generator",
     "The generator's `tests/reference-bodies.test.ts` enforces it", True),
    ("a basename, not a path",
     "`audit.rs` records the decision either way", True),
    ("an MQTT topic",
     "the host publishes to `obc/nodes/{id}/limits` on connect", True),
    ("a JSON-RPC method",
     "the peer calls `tools/call` with the arguments", True),
    ("a fraction",
     "`13/13` controls now cite a test", True),
    ("a directory that exists",
     "everything under `crates/obc-safety` is gated", True),
    # This one is here because the gate got it wrong on its first run:
    # `lstrip("./")` strips character-wise and turned it into
    # `cargo/config.toml`, which matches nothing.
    ("a dotted directory, crate-relative",
     "`cargo run` flashes because `.cargo/config.toml` sets the runner", True),
]


def selftest(names: set[str], dirs: set[str]) -> int:
    failed = []
    for label, text, want_pass in SELFTEST:
        toks = list(candidates(text))
        got_pass = all(
            resolves(t, "bodies/benchtop/README.md", names, dirs) or ATTRIBUTION.search(text)
            for t in toks
        )
        if got_pass != want_pass:
            failed.append(f"{label}: expected {'pass' if want_pass else 'FAIL'}, got the other")
    print(f"selftest: {len(SELFTEST) - len(failed)}/{len(SELFTEST)} cases behave as stated")
    for line in failed:
        print("  x " + line)
    if failed:
        return 1
    print("ok: the gate discriminates the citation it was built for, "
          "attributed from unattributed")
    return 0


def main(argv: list[str]) -> int:
    docs, names = commit_files()
    dirs = {os.path.dirname(n) for n in names if os.path.dirname(n)}

    if "--selftest" in argv:
        return selftest(names, dirs)

    vendored = {local for _up, local, _peer in ARTIFACTS}
    targets = sorted(n for n in docs if INSTRUCTIONAL.match(n) and n not in vendored)

    checked = 0
    by_attribution = 0
    bad: list[str] = []

    for doc in targets:
        text = docs[doc].decode("utf-8", errors="replace")
        for window in windows(text):
            attributed = ATTRIBUTION.search(window)
            for tok in candidates(window):
                checked += 1
                how = resolves(tok, doc, names, dirs)
                if how:
                    continue
                if attributed:
                    by_attribution += 1
                    continue
                bad.append(f"{doc}: `{tok}` is not in this repository and "
                           f"nothing near it says whose it is")

    print(f"checked {checked} cited paths across {len(targets)} instructional "
          f"document(s); {by_attribution} resolved by attribution")
    if bad:
        print("\ncited paths that point at nothing a reader can open:")
        for entry in bad:
            print("  x " + entry)
        print("\nEither the path is wrong, or it belongs to another repository "
              "and should say so,\n"
              "the way README.md says \"upstream's `docs/ENDGAME.md`\".")
        return 1
    print("ok: every cited path is here, or says whose it is")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
