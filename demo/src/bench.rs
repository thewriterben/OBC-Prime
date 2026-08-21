//! The Track 0 limit table of a reference body, run against the real file.
//!
//! `bodies/benchtop/README.md` carries an honest-status table, and one row read:
//!
//! > The Track 0 limit refuses an out-of-range `gpio_write` on this board —
//! > **not verified here**
//!
//! That row collapsed two claims that need very different things.
//!
//! The second — that the *node* holds its own copy of the limits and refuses
//! even when the host is compromised or gone — needs the board on the bench.
//! `docs/SAFETY-CASE.md` §4 calls that mirror the load-bearing property of the
//! whole safety case, and it stays unverified here until someone flashes an
//! ESP32-S3 and tries it.
//!
//! The first — that *this particular limit table* refuses pin 14 — needed
//! nobody to plug anything in. It needed someone to read the file and run the
//! gate over it. That is this demo, and it is why the row now splits in two.
//!
//! Reading `config.toml` rather than restating it matters: `SafetyConfig` is
//! `#[serde(deny_unknown_fields)]` precisely because a config written from
//! documentation once used `[[safety.limit]]` (singular), parsed cleanly, and
//! enforced nothing while startup logged the gate as active. Parsing the real
//! file here means that failure cannot reach this body unnoticed.

use anyhow::{bail, Result};
use obc_safety::limits::{SafetyConfig, SafetyGate};
use serde::Deserialize;

/// The node-side gate, compiled here from the firmware source this repository
/// already vendors.
///
/// `firmware/obc-esp32-s3/src/safety.rs` says of itself: "Pure (`std` + `serde`),
/// so it unit-tests on the host like `reflex` and `safing`" and "Wire-compatible
/// with the host `SafetyLimit` JSON (same field names)". Both of those are
/// claims, and a `#[path]` shim turns them into something this demo can run —
/// the same trick `planner-wasm/src/` uses to compile the planner it hashes.
///
/// So the mirror is not taken on trust. The same table drives both gates and
/// the verdicts are compared.
///
/// `dead_code` is allowed because this is somebody else's module compiled
/// through a shim: `policy()` is part of the firmware's API and is used by the
/// firmware, and a lint about what *this* demo happens not to call would be a
/// lint about the wrong crate. Nothing here is silenced — the file is compiled
/// and its behaviour is checked below.
///
/// `rustfmt::skip` for a sharper reason, and it is worth stating rather than
/// hiding. `firmware/obc-esp32-s3` is not a workspace member upstream either,
/// so it is in no `cargo fmt` and no `cargo clippy` gate anywhere: `safety.rs`
/// is 56 diff lines from formatted, `reflex.rs` 151, `main.rs` 898. Pulling one
/// file into this crate would make `cargo fmt --all` rewrite a *vendored* file,
/// which `scripts/sync_upstream.py check` correctly reports as drift, and
/// formatting one file upstream to satisfy a shim down here would be the tail
/// wagging the dog.
///
/// So the file is compiled and linted here and not formatted, and the gap is
/// on the record. The two clippy errors this shim did surface were fixed
/// upstream on 2026-08-21 — they were errors, not style.
#[path = "../../firmware/obc-esp32-s3/src/safety.rs"]
#[allow(dead_code)]
#[rustfmt::skip]
mod fw;

/// The reference body's own config, read at compile time from this repository.
const BENCHTOP: &str = include_str!("../../bodies/benchtop/config.toml");

pub fn run() -> Result<()> {
    // Only the `[safety]` section: `obc-config` is deliberately not vendored
    // here, and this section is declared in `obc-safety`, which is.
    let doc: toml::Value = toml::from_str(BENCHTOP)?;
    let Some(section) = doc.get("safety") else {
        bail!("bodies/benchtop/config.toml has no [safety] section");
    };
    let cfg = SafetyConfig::deserialize(section.clone())?;

    println!("── bodies/benchtop/config.toml, as the gate reads it ──");
    println!("  enabled       {}", cfg.enabled);
    println!("  dynamic_trust {}", cfg.dynamic_trust);
    if cfg.limits.is_empty() {
        bail!("the limit table is empty — the gate would enforce nothing");
    }
    for l in &cfg.limits {
        println!(
            "  limit  node={} tool={} pins={:?} value={:?}..={:?} min_interval={:?}ms",
            l.node_id, l.tool, l.allowed_pins, l.value_min, l.value_max, l.min_interval_ms
        );
    }
    println!();

    let gate = SafetyGate::new(cfg.limits.clone());
    let limit = &cfg.limits[0];
    let node = &limit.node_id;
    let tool = &limit.tool;

    // Derive every case from the table rather than restating it. The first
    // version of this demo hardcoded pins 13, 14 and 12 to match what the file
    // said that day; when the table was corrected on 2026-08-21 the demo went
    // green on three cases that no longer meant anything. A check that has to
    // be edited whenever its subject changes is a check that will one day be
    // edited to agree with a mistake.
    let allowed = *limit
        .allowed_pins
        .as_ref()
        .and_then(|p| p.first())
        .ok_or_else(|| anyhow::anyhow!("no allow-listed pin to test with"))?;
    let refused = (0..64)
        .find(|p| !limit.allowed_pins.as_ref().is_some_and(|a| a.contains(p)))
        .ok_or_else(|| anyhow::anyhow!("every pin is allowed — nothing to refuse"))?;
    let over = limit.value_max.map(|m| m + 1).unwrap_or(2);
    let interval = limit.min_interval_ms.unwrap_or(0);

    println!("── what it does with the table's own pins ──");
    let mut failures = 0;

    failures += expect(
        &format!("pin {allowed}, value {}", limit.value_min.unwrap_or(0)),
        gate.check(node, tool, allowed, limit.value_min.unwrap_or(0), 1_000)
            .is_ok(),
        "allowed",
    );

    failures += expect(
        &format!("pin {refused} (not in the list)"),
        gate.check(node, tool, refused, 1, 2_000).is_err(),
        "refused — pin not in the allow-list",
    );

    failures += expect(
        &format!("pin {allowed}, value {over}"),
        gate.check(node, tool, allowed, over, 3_000).is_err(),
        "refused — value out of range",
    );

    // The out-of-range attempt above was refused, so it did not arm the
    // limiter. Fire a clean one, then crowd it.
    let _ = gate.check(node, tool, allowed, 1, 10_000);
    failures += expect(
        &format!("pin {allowed} again, {}ms later", interval / 2),
        gate.check(node, tool, allowed, 1, 10_000 + interval / 2)
            .is_err(),
        "refused — faster than min_interval_ms",
    );
    failures += expect(
        &format!("pin {allowed} again, {}ms later", interval + 100),
        gate.check(node, tool, allowed, 1, 10_000 + interval + 100)
            .is_ok(),
        "allowed — the interval has passed",
    );

    if failures > 0 {
        bail!("{failures} case(s) did not behave as this body's README says");
    }

    // ── The mirror ───────────────────────────────────────────────────────────
    // Same table, the node's gate. Handed over as JSON, because that is how it
    // reaches a real node — over the retained `obc/nodes/{id}/limits` topic —
    // and because round-tripping it is what actually tests the wire-compatible
    // claim the firmware makes about itself.
    println!();
    println!("── and the same table on the node's own gate ──");

    let wire = serde_json::to_string(&cfg.limits)?;
    let pushed: Vec<fw::SafetyLimit> = serde_json::from_str(&wire)?;
    let mut node_gate = fw::SafetyGate::with_output_pins(&[]);
    if !node_gate.apply_pushed(pushed, node) {
        bail!(
            "the node gate rejected this table: `node_id = \"{node}\"` matches no node. \
             The firmware compares against its own NODE_ID const, not the host's label."
        );
    }
    println!("  host limits round-tripped as JSON and applied: ok");

    // The same commands, in the same order, against the node's clock.
    let mut disagreements = 0;
    let cases: &[(String, i64, i64, u64)] = &[
        (format!("pin {allowed}, in policy"), allowed, 1, 1_000),
        (format!("pin {refused}, not listed"), refused, 1, 2_000),
        (format!("pin {allowed}, value {over}"), allowed, over, 3_000),
    ];
    let host = SafetyGate::new(cfg.limits.clone());
    for (what, pin, value, now) in cases {
        let h = host.check(node, tool, *pin, *value, *now).is_ok();
        let n = node_gate.check(*pin, *value, *now).is_ok();
        let verdict = if h { "allowed" } else { "refused" };
        if h == n {
            println!("  {what:<28} both gates {verdict}");
        } else {
            println!("  {what:<28} DISAGREE — host {h}, node {n}");
            disagreements += 1;
        }
    }
    if disagreements > 0 {
        bail!("{disagreements} case(s) where host and node disagree — the mirror is not a mirror");
    }

    println!();
    println!("  The host half of that row is checkable by running this, and so is");
    println!("  the claim that the node enforces the same table. What is left for");
    println!("  the bench is narrower than the row used to suggest: that a real");
    println!("  ESP32-S3 runs this code, and that a refusal stops the wire moving.");
    Ok(())
}

fn expect(what: &str, ok: bool, says: &str) -> usize {
    println!("  {:<28} {}", what, if ok { says } else { "UNEXPECTED" });
    usize::from(!ok)
}
