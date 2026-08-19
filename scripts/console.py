"""One line of console setup, in one place, because upstream wrote it twice.

Every survey that draws its sections with box characters hits the same wall on
Windows: the console defaults to cp1252, which cannot encode them, so the
script raises UnicodeEncodeError *after* doing all its work and often after
printing its counts. It reads as a broken tool and is a broken terminal.

Upstream fixed this three times in three scripts before making it a function --
its own recurring finding, an instrument that records a lesson it does not
enforce, performed on itself. This repository gets the function rather than the
third copy.
"""

from __future__ import annotations

import sys


def use_utf8_stdout() -> None:
    """Make stdout and stderr able to carry the box characters we print.

    A no-op where they already are, which is everywhere this runs in CI.
    Best-effort: a stream without `reconfigure` (a pipe wrapper, a test double)
    is left alone rather than raising, because failing to set an encoding must
    not be the thing that stops a check from running.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
