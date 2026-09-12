#!/usr/bin/env python3
"""check_peer_access.py — can this runner read the generator at all?

Why this exists
---------------
The `peer` job compares this repository's 12 generator mirrors against the
generator's own copies. The generator is **private**, so the comparison needs
`PEER_REPO_TOKEN`, a fine-grained PAT with `Contents: read` on
thewriterben/OBC-deployment-generator.

The PAT in place until 2026-09-12 had a 30-day life. Measured: issued
2026-07-30, green 2026-08-22, dead by 2026-09-06. When it lapsed,
`actions/checkout` failed with "Bad credentials" and the job went red — and on
the run list that red was indistinguishable from a mirror that genuinely
drifted. It happened again on 2026-09-11: eleven of twelve jobs green, `peer`
red at the *checkout step*, nothing compared.

The replacement issued 2026-09-12 does not expire, so that particular clock has
stopped. This still matters, because a token that cannot expire can still be
revoked, be dropped by an organisation policy sweep, lose access when the
repository is renamed, or be replaced by someone with an expiring one. Every one
of those arrives as the same "Bad credentials".

`.github/workflows/parity.yml` has said so in a comment since 2026-09-06:

    Either way it reads like drift and is not — a drift failure names a file
    and two hashes. Re-issue the PAT rather than debugging the manifest.

That was right, and was a comment rather than a check. This is the check. It is
the same correction this repository already made once, for the same reason:
`check_vendored_mods.py` exists because `sync_upstream.py` described a failure
mode in prose instead of testing for it.

What it checks
--------------
One API call to the repository endpoint, before any checkout, and a diagnosis
from the status code. Four outcomes that a "Bad credentials" line cannot tell
apart:

  * no token, repository public      -> fine, `github.token` will do
  * no token, repository private     -> the secret was never set
  * token rejected (401)             -> set, and expired or revoked
  * token authenticates, 404         -> valid, but not granted this repository

What it deliberately does not do
--------------------------------
**It does not let the job pass.** An unreadable peer means the mirrors are
unverified, and unverified is not verified — the same rule this ecosystem
applies to a Blender check that cannot run. What changes is only that the red
names its own cause instead of looking like drift.

It also does not fetch or compare anything. `sync_upstream.py` does that, and
this runs before it precisely so that its failure cannot be mistaken for one.

The early-warning half, and why it is not here
----------------------------------------------
This briefly grew a `--warn-days N` that read GitHub's
`github-authentication-token-expiration` header and warned before a lapse rather
than after one. It was written, tested, and removed the same day.

The reason is the token issued 2026-09-12: it **does not expire**, so that branch
could not fire. Keeping it would have meant shipping a warning that cannot
happen, dressed as a safety net — for a hypothetical future PAT nobody has
decided to issue. CONTRIBUTING's rule about not adding code nothing calls
applies to a code path nothing reaches just as much as to a module nothing
imports.

Worth recording that the header was never actually confirmed to arrive: it was
tried against a `gho_` OAuth token (no expiry, no header) and then against the
new PAT (no expiry, no header), so both observations are consistent with GitHub
not sending it at all. Anyone re-adding this on an expiring token should verify
the header exists before building on it.

What replaces it is cruder and works: `peer-token.yml` runs this probe daily, so
any way the token dies surfaces within a day instead of on whatever merge comes
next.

Run:  PEER_REPO_TOKEN=... python scripts/check_peer_access.py
      python scripts/check_peer_access.py --selftest
      python scripts/check_peer_access.py --repo owner/name   (probe by hand)
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

REPO = "thewriterben/OBC-deployment-generator"

# Every line here names what to do, because the person reading it is looking at
# a red `parity` run and the obvious first move is to go and debug the manifest.
NOT_DRIFT = (
    "This is NOT drift. A drift failure names a file and two hashes; nothing "
    "was compared at all."
)
REISSUE = (
    "Fix: issue a fine-grained PAT at "
    "https://github.com/settings/personal-access-tokens with Contents: read on "
    f"{REPO} and nothing else, then update the PEER_REPO_TOKEN secret on this "
    "repository (Settings -> Secrets and variables -> Actions)."
)


def diagnose(*, token_set: bool, status: int) -> tuple[bool, str, list[str]]:
    """Pure: (readable, headline, what to do). No network, so it can be pinned."""
    if status == 200:
        if token_set:
            return True, "PEER_REPO_TOKEN reads the generator", []
        # The workflow's comment asserts the generator is private, and that
        # assertion was itself a measurement (2026-07-30). If this branch ever
        # fires, the world changed and the comment is now wrong.
        return True, (
            "the generator is readable with no token — it is public now, and "
            "parity.yml's comment saying otherwise needs correcting"
        ), []

    if not token_set:
        return False, "PEER_REPO_TOKEN is not set, and the generator is private", [
            NOT_DRIFT,
            "The workflow falls back to `github.token`, which is scoped to THIS "
            "repository and cannot read another private one. The fallback exists "
            "for symmetry and has never worked here.",
            REISSUE,
        ]

    if status == 401:
        return False, "PEER_REPO_TOKEN is set and was rejected", [
            NOT_DRIFT,
            "401 means the credential itself is bad: expired, revoked, or "
            "mistyped. Expiry is the usual one — this PAT has a 30-day life "
            "(issued 2026-07-30, green 2026-08-22, dead by 2026-09-06).",
            REISSUE,
        ]

    if status == 403:
        return False, "PEER_REPO_TOKEN is set and was refused", [
            NOT_DRIFT,
            "403 is not expiry. It is an organisation SSO authorisation the "
            "token has not been granted, a blocked IP policy, or a rate limit. "
            "Check the token's SSO state before re-issuing it.",
        ]

    if status == 404:
        return False, "PEER_REPO_TOKEN authenticates but cannot see the generator", [
            NOT_DRIFT,
            "A fine-grained PAT returns 404, not 403, for a repository it was "
            f"not granted. Either {REPO} is missing from the token's repository "
            "list, or it has Metadata but not Contents: read, or the repository "
            "was renamed.",
            REISSUE,
        ]

    return False, f"the generator endpoint answered {status}", [
        NOT_DRIFT,
        "An unexpected status. Check https://www.githubstatus.com before "
        "touching the token.",
    ]


def probe(repo: str, token: str) -> int:
    """HTTP status from the repository endpoint. Never prints the token."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "obc-prime-parity-preflight",
        },
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except urllib.error.URLError as e:
        print(f"could not reach api.github.com: {e.reason}", file=sys.stderr)
        return 0


# Each case must produce a *different* headline from every other. A preflight
# whose four diagnoses read alike would be the same failure it was written to
# fix, one layer further in.
SELFTEST = [
    ("no token, public repo", False, 200, True),
    ("no token, private repo", False, 404, False),
    ("token accepted", True, 200, True),
    ("token expired or revoked", True, 401, False),
    ("token not SSO-authorised", True, 403, False),
    ("token not granted this repository", True, 404, False),
    ("github is having a day", True, 500, False),
]


def selftest() -> int:
    failed: list[str] = []
    headlines: dict[str, str] = {}
    for label, token_set, status, want_ok in SELFTEST:
        ok, headline, guidance = diagnose(token_set=token_set, status=status)
        if ok != want_ok:
            failed.append(f"{label}: expected {'readable' if want_ok else 'FAIL'}, got the other")
        if headline in headlines:
            failed.append(f"{label}: says the same thing as '{headlines[headline]}'")
        headlines[headline] = label
        if not ok and not guidance:
            failed.append(f"{label}: fails without saying what to do")

    print(f"selftest: {len(SELFTEST) - len(failed)}/{len(SELFTEST)} cases behave as stated")
    for line in failed:
        print("  x " + line)
    if failed:
        return 1
    print("ok: the four ways this can fail are told apart, and each names its fix")
    return 0


def summary(headline: str, guidance: list[str], ok: bool) -> None:
    """Put the diagnosis on the run page, not only in a collapsed log."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"### Generator access: {'ok' if ok else 'UNAVAILABLE'}\n\n")
        fh.write(f"**{headline}**\n\n")
        for line in guidance:
            fh.write(f"{line}\n\n")


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()

    repo = REPO
    if "--repo" in argv:
        repo = argv[argv.index("--repo") + 1]

    token = os.environ.get("PEER_REPO_TOKEN", "").strip()
    status = probe(repo, token)
    ok, headline, guidance = diagnose(token_set=bool(token), status=status)

    print(f"probed {repo} {'with' if token else 'without'} PEER_REPO_TOKEN -> HTTP {status}")
    print(("ok: " if ok else "x  ") + headline)
    for line in guidance:
        print()
        print(line)
    summary(headline, guidance, ok)

    if not ok:
        print()
        print("The 12 generator mirrors were NOT compared. Unverified is not verified.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
