"""A tool that actuates must declare it, because the gate reading it believes it.

What this checks, and where the consequence lands
------------------------------------------------
`Tool::risk_class` in `crates/obc-tool-api` defaults to `RiskClass::safe()` --
non-physical, blast radius none -- and its doc comment says tools that touch
the real world "MUST override this so the approval layer and safety gate treat
them accordingly". Nothing enforced that MUST, in either repository.

The gate that acts on the answer is **not vendored here.** `track0_authorize`
lives in the core agent's `obc-agent`, one of the six crates deliberately left
upstream, and it opens with `if !risk.physical { return Ok(()); }` -- not "skip
the limit check" but *return*, before the `SafetyGate` check on
`(node_id, tool, pin, value)` and before the tamper-evident audit record. So a
tool that under-declares itself here is not wrong here; it is wrong where it is
used, in a repository this one does not build. That is the worst shape a defect
can have, and the reason the check belongs on the declaration rather than on
the caller.

On 2026-08-18 upstream found every tool in `obc-peripherals` taking the default
-- `gpio_write`, `pwm_control`, `i2c_write`, `spi_transfer`, `stm32_flash` --
and so did `MqttNodeTool` and `P2pNodeTool` in `obc-spine`, which are vendored
here and are how *every* tool announced by *every* peripheral node reaches the
agent. Every other check stayed green throughout, because nothing else reads
`risk_class`.

Two rules, and the second is the one that would have caught it
--------------------------------------------------------------
1. A tool whose **literal name** says it actuates -- `*_write`, `*_flash`,
   `*_reset`, `*_capture`, `pwm_*`, `spi_transfer`, `move_actuator` -- must
   declare `risk_class`, and must declare it physical.

2. A tool whose name is **not a literal** -- computed at runtime, as
   `MqttNodeTool` and `P2pNodeTool` compute theirs from `self.spec.name` -- must
   declare `risk_class` at all, whatever it says.

Rule 1 alone is the upstream version of this script, and rule 1 alone cannot see
the two tools that motivated writing it: a name-matching heuristic has no name
to match. A tool whose name is decided by a remote peer over a UDP broadcast is
exactly the tool a reviewer cannot classify by reading, so the declaration is
the only place the answer can be.

Limits, stated
--------------
Rule 1 is name-based, deliberately: the name is the part a reviewer reads, and a
tool called `*_write` reporting `physical: false` is either misnamed or
misclassified. It cannot see a tool that actuates under a name that does not say
so -- `siren`, `unlock`, `dispense`. The answer to that is naming, not a longer
regex.

Neither rule can tell a correct `physical` from an incorrect one. `stm32_flash`
being irreversible with a device-wide blast radius, and `gpio_write` being
reversible with a low one, is a judgement no script makes. This checks that the
judgement was made.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from console import use_utf8_stdout  # noqa: E402

use_utf8_stdout()

ROOT = Path(__file__).resolve().parent.parent

IMPL_RE = re.compile(r"impl Tool for (\w+)\s*\{")
NAME_FN_RE = re.compile(r"fn name\(&self\)\s*->\s*&(?:'\w+\s+)?str\s*\{")
NAME_LIT_RE = re.compile(r'fn name\(&self\)\s*->\s*&(?:\'\w+\s+)?str\s*\{\s*"([^"]+)"')
RISK_RE = re.compile(r"fn risk_class\(&self\)")
PHYSICAL_RE = re.compile(r"RiskClass::physical\s*\(")

# Below this the scan is broken, not the tree. OBC-Prime carried 45 `impl Tool`
# blocks when this landed; the floor is set well under that so a genuinely
# smaller vendored set does not trip it, and well over zero so a glob that stops
# matching cannot report a clean bill.
MIN_IMPLS = 30

ACTUATES = (
    lambda n: n.endswith("_write"),
    lambda n: n.endswith("_flash"),
    lambda n: n.endswith("_reset"),
    lambda n: n.endswith("_capture"),
    lambda n: n.startswith("pwm_"),
    lambda n: n == "spi_transfer",
    lambda n: n == "move_actuator",
)


def actuates(name: str) -> bool:
    return any(test(name) for test in ACTUATES)


def impl_blocks(text: str):
    """(struct, body) for every `impl Tool for X` in a file, brace-matched."""
    for m in IMPL_RE.finditer(text):
        depth, i = 0, m.end() - 1
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        yield m.group(1), text[m.end():i]


def main() -> int:
    roots = [ROOT / "src"] + sorted((ROOT / "crates").glob("*/src"))
    files = [f for r in roots if r.is_dir() for f in sorted(r.rglob("*.rs"))]

    impls = 0
    dynamic = 0
    undeclared: list[tuple[str, str, str]] = []
    unphysical: list[tuple[str, str, str]] = []
    unjudgeable: list[tuple[str, str]] = []

    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        if "impl Tool for" not in text:
            continue
        rel = f.relative_to(ROOT).as_posix()
        for struct, body in impl_blocks(text):
            if not NAME_FN_RE.search(body):
                continue  # not the Tool trait we mean
            impls += 1
            declares = bool(RISK_RE.search(body))
            lit = NAME_LIT_RE.search(body)
            if not lit:
                dynamic += 1
                if not declares:
                    unjudgeable.append((rel, struct))
                continue
            name = lit.group(1)
            if not actuates(name):
                continue
            if not declares:
                undeclared.append((rel, struct, name))
            elif not PHYSICAL_RE.search(body):
                unphysical.append((rel, struct, name))

    if impls < MIN_IMPLS:
        print(f"!! found only {impls} `impl Tool` block(s) — the scan is wrong, "
              f"not the tree", file=sys.stderr)
        return 2

    print(f"{impls} tool implementation(s) scanned "
          f"({dynamic} name themselves at runtime)")

    problems = len(undeclared) + len(unphysical) + len(unjudgeable)
    if not problems:
        print("ok: every tool that says it actuates declares itself physical, "
              "and every\n    tool that cannot say declares something")
        return 0

    if undeclared or unphysical:
        print("\n── Actuates by name, and the gate will not see it ──")
        for rel, struct, name in undeclared:
            print(f"  {name:<22} {struct} ({rel})")
            print(f"{'':<24}no risk_class — inherits RiskClass::safe()")
        for rel, struct, name in unphysical:
            print(f"  {name:<22} {struct} ({rel})")
            print(f"{'':<24}declares risk_class, but not as physical")

    if unjudgeable:
        print("\n── Named at runtime, so nothing here can classify it ──")
        for rel, struct in unjudgeable:
            print(f"  {struct} ({rel})")
            print(f"{'':<24}no literal name and no risk_class: this tool's risk "
                  f"is\n{'':<24}decided by whoever announced it")

    print(f"\n{problems} tool(s). Upstream's `track0_authorize` returns before "
          f"the SafetyGate\ncheck and before the audit record when `physical` is "
          f"false, so these calls\nreach the hardware ungated and unlogged.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
