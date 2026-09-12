#!/usr/bin/env python3
"""check_peer_access.py — can this runner read the generator at all?

Why this exists
---------------
The `peer` job compares this repository's 12 generator mirrors against the
generator's own copies. The generator is **private**, so the comparison needs
`PEER_REPO_TOKEN`, a fine-grained PAT with `Contents: read` on
thewriterben/OBC-deployment-generator.

That PAT has a 30-day life. Measured: issued 2026-07-30, green 2026-08-22, dead
by 2026-09-06. When it lapses, `actions/checkout` fails with "Bad credentials"
and the job goes red — and on the run list that red is indistinguishable from a
mirror that genuinely drifted. It happened again on 2026-09-11: eleven of twelve
jobs green, `peer` red at the *checkout step*, nothing compared.

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

Early warning
-------------
The four diagnoses above are post-mortems: by the time any of them prints, the
mirrors are already unverified. GitHub returns a
`github-authentication-token-expiration` header on requests authenticated with a
PAT that has an expiry, so `--warn-days N` reports the days remaining and says
so loudly while the token still works. `peer-token.yml` runs that daily with
`--fail-on-warning`, which turns "find out on your next merge" into "find out
within a day".

**Unverified as of 2026-09-12:** the header was checked against the `gho_` OAuth
token this machine had, which has no expiry and so returned none — that tells us
nothing about what a fine-grained PAT returns, and no valid PAT was available to
test with. So the header is read if it is there and its absence is reported as
*absence*, never as "plenty of time". If it turns out GitHub does not send it for
this token type, the daily job still catches the lapse within a day; it just
cannot pre-announce it. Confirm on the next PAT and delete this paragraph.

Run:  PEER_REPO_TOKEN=... python scripts/check_peer_access.py
      python scripts/check_peer_access.py --warn-days 7 --fail-on-warning
      python scripts/check_peer_access.py --selftest
      python scripts/check_peer_access.py --repo owner/name   (probe by hand)
"""

from __future__ import annotations

import datetime as dt
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


EXPIRY_HEADER = "github-authentication-token-expiration"

# GitHub documents "2022-11-28 15:30:00 UTC". Parsed tolerantly because an
# unparseable date must read as "could not tell", never as "fine".
EXPIRY_FORMATS = ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d")


def expiry_note(raw: str | None, warn_days: int, today: dt.date) -> tuple[bool, str]:
    """Pure: (is_warning, line). A date we cannot read is not a reassurance."""
    if not raw:
        return False, (
            "GitHub reported no expiry for this token. Either it does not expire, "
            "or it does not say so for this token type — this cannot tell which, "
            "so treat the daily run as the warning rather than this line."
        )

    when = None
    for fmt in EXPIRY_FORMATS:
        try:
            when = dt.datetime.strptime(raw.strip(), fmt).date()
            break
        except ValueError:
            continue
    if when is None:
        return True, f"could not parse the expiry GitHub reported ({raw!r}); check it by hand"

    left = (when - today).days
    if left < 0:
        return True, f"the token's stated expiry was {when} — {-left} day(s) ago, and it still answered"
    if left <= warn_days:
        return True, (
            f"the token expires {when}, in {left} day(s). Re-issue it now: when it "
            "lapses, `parity` goes red and the mirrors stop being checked."
        )
    return False, f"the token expires {when}, in {left} day(s)"


def probe(repo: str, token: str) -> tuple[int, str | None]:
    """HTTP status and the expiry header, if any. Never prints the token."""
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
            return resp.status, resp.headers.get(EXPIRY_HEADER)
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get(EXPIRY_HEADER)
    except urllib.error.URLError as e:
        print(f"could not reach api.github.com: {e.reason}", file=sys.stderr)
        return 0, None


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


# The expiry half. A missing or unreadable date must never read as "fine" --
# that is the whole point of having it, and the easy way to get it wrong.
TODAY = dt.date(2026, 9, 12)
EXPIRY_SELFTEST = [
    ("no header at all", None, False),
    ("expires well in the future", "2026-12-01 00:00:00 UTC", False),
    ("expires inside the window", "2026-09-15 00:00:00 UTC", True),
    ("expires today", "2026-09-12 00:00:00 UTC", True),
    ("already expired but still answering", "2026-09-01 00:00:00 UTC", True),
    ("a date shape nobody predicted", "next Tuesday", True),
    ("date only, no clock", "2026-09-13", True),
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

    for label, raw, want_warn in EXPIRY_SELFTEST:
        warn, line = expiry_note(raw, warn_days=7, today=TODAY)
        if warn != want_warn:
            failed.append(f"expiry/{label}: expected {'a warning' if want_warn else 'quiet'}, got the other")
        if not line:
            failed.append(f"expiry/{label}: said nothing")

    total = len(SELFTEST) + len(EXPIRY_SELFTEST)
    print(f"selftest: {total - len(failed)}/{total} cases behave as stated")
    for line in failed:
        print("  x " + line)
    if failed:
        return 1
    print("ok: the four ways this can fail are told apart, and each names its fix")
    print("ok: an absent or unreadable expiry reads as unknown, not as time remaining")
    return 0


def summary(headline: str, guidance: list[str], ok: bool, expiry: str | None) -> None:
    """Put the diagnosis on the run page, not only in a collapsed log."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"### Generator access: {'ok' if ok else 'UNAVAILABLE'}\n\n")
        fh.write(f"**{headline}**\n\n")
        for line in guidance:
            fh.write(f"{line}\n\n")
        if expiry:
            fh.write(f"{expiry}\n\n")


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()

    repo = REPO
    if "--repo" in argv:
        repo = argv[argv.index("--repo") + 1]
    warn_days = 7
    if "--warn-days" in argv:
        warn_days = int(argv[argv.index("--warn-days") + 1])
    fail_on_warning = "--fail-on-warning" in argv

    token = os.environ.get("PEER_REPO_TOKEN", "").strip()
    status, expiry_raw = probe(repo, token)
    ok, headline, guidance = diagnose(token_set=bool(token), status=status)

    print(f"probed {repo} {'with' if token else 'without'} PEER_REPO_TOKEN -> HTTP {status}")
    print(("ok: " if ok else "x  ") + headline)
    for line in guidance:
        print()
        print(line)

    # Only meaningful when the token worked: an expiry read off a rejected
    # request would be describing a credential that is already gone.
    warn, expiry_line = (False, None)
    if ok and token:
        warn, expiry_line = expiry_note(expiry_raw, warn_days, dt.date.today())
        print()
        print(("!  " if warn else "   ") + expiry_line)
        if warn:
            # A GitHub annotation, so it is on the run page and not only in a log.
            print(f"::warning title=PEER_REPO_TOKEN needs re-issuing::{expiry_line}")

    summary(headline, guidance, ok, expiry_line)

    if not ok:
        print()
        print("The 12 generator mirrors were NOT compared. Unverified is not verified.")
        return 1
    if warn and fail_on_warning:
        print()
        print(REISSUE)
        print()
        print(
            "Failing on the warning because this run exists only to give notice. "
            "parity's own peer job does not: the mirrors are verifiable today, and "
            "a gate that goes red over a future problem is a gate someone turns off."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
