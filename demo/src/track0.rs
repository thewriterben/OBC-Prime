//! The join: a tool's own declaration decides whether the gate ever sees it.
//!
//! The `gate` demo shows `SafetyGate` refusing an out-of-range command. That is
//! half the claim. The other half is that a *tool* reaches that gate at all,
//! and what decides it is the tool's own `risk_class()` — read by
//! `obc_safety::authorize::track0_authorize`, which returns at its first line
//! for anything declaring itself non-physical.
//!
//! Until 2026-08-19 this demo could not exist here. `track0_authorize` lived in
//! `obc-agent`, which this repository deliberately does not vendor, so both
//! halves were present and the wire between them was not. It now lives in
//! `obc-safety`, beside the gate it consults.
//!
//! Nothing is mocked. `Honest` and `Understated` are real `Tool` impls; the
//! gate is a real `SafetyGate` with one limit; the only difference between the
//! two runs is one line of each tool's declaration.

use anyhow::Result;
use obc_safety::authorize::track0_authorize;
use obc_safety::limits::{SafetyGate, SafetyLimit};
use obc_tool_api::{BlastRadius, RiskClass, Tool, ToolResult};
use serde_json::{json, Value};

/// A tool that says what it is: it drives a pin.
struct Honest;

#[async_trait::async_trait]
impl Tool for Honest {
    fn name(&self) -> &str {
        "gpio_write"
    }
    fn description(&self) -> &str {
        "drive a GPIO pin"
    }
    fn risk_class(&self) -> RiskClass {
        RiskClass::physical(true, BlastRadius::Low)
    }
    async fn execute(&self, _args: Value) -> Result<ToolResult> {
        Ok(ToolResult::ok("wrote"))
    }
}

/// The same tool, declaring itself safe. Nothing else about it differs.
struct Understated;

#[async_trait::async_trait]
impl Tool for Understated {
    fn name(&self) -> &str {
        "gpio_write"
    }
    fn description(&self) -> &str {
        "drive a GPIO pin"
    }
    // No `risk_class` override — it inherits `RiskClass::safe()`, which is the
    // trait default and the whole point of this demo.
    async fn execute(&self, _args: Value) -> Result<ToolResult> {
        Ok(ToolResult::ok("wrote"))
    }
}

pub fn run() -> Result<()> {
    // One limit: on this node, `gpio_write` may touch pin 17 and nothing else.
    let gate = SafetyGate::new(vec![SafetyLimit {
        node_id: "bench-001".into(),
        tool: "gpio_write".into(),
        allowed_pins: Some(vec![17]),
        value_min: Some(0),
        value_max: Some(1),
        min_interval_ms: None,
    }]);

    // The same call in both runs: pin 99, which the limit table does not allow.
    let args = json!({"node_id": "bench-001", "pin": 99, "value": 1});

    println!("A gate with one limit: bench-001 / gpio_write / pin 17 only.");
    println!("The call, both times:   {args}\n");

    for (label, tool) in [
        ("declares physical", Box::new(Honest) as Box<dyn Tool>),
        ("declares safe    ", Box::new(Understated) as Box<dyn Tool>),
    ] {
        let risk = tool.risk_class();
        let outcome = track0_authorize(Some(&gate), None, tool.name(), risk, &args);
        let verdict = match &outcome {
            Ok(()) => "ALLOWED".to_string(),
            Err(reason) => format!("REFUSED — {reason}"),
        };
        println!("  {label}  physical={:<5}  {verdict}", risk.physical);
    }

    println!(
        "\nSame gate, same pin, same arguments. The tool's own declaration is what\n\
         decides whether the limit table is consulted at all: `track0_authorize`\n\
         returns at its first line when `physical` is false, before the gate and\n\
         before the audit record.\n\n\
         That is why `scripts/check_physical_tools.py` fails the build on a tool\n\
         whose name says it actuates and whose declaration does not."
    );

    approval_leg();
    Ok(())
}

/// The second half: what a *person* has to confirm, for the same call.
///
/// `track0_authorize` answers "may this actuate" from a limit table.
/// `approval_authorize` answers "must someone say yes first" from the autonomy
/// level and the tool's risk class. Both moved out of `obc-agent` — the gate on
/// 2026-08-19, this one on 2026-08-20 — so this repository can now run the whole
/// sentence rather than the first clause.
fn approval_leg() {
    use obc_approval::{approval_authorize, ApprovalManager, AutonomyConfig, AutonomyLevel};

    println!("\n── and whether a person has to confirm it ──\n");

    for (label, level, auto_approve) in [
        ("full        ", AutonomyLevel::Full, vec![]),
        ("supervised  ", AutonomyLevel::Supervised, vec![]),
        (
            "supervised +",
            AutonomyLevel::Supervised,
            vec!["gpio_write".to_string()],
        ),
    ] {
        let granted = !auto_approve.is_empty();
        // Non-interactive: an autonomous loop cannot ask, so "needs approval"
        // arrives as a refusal with a reason rather than a prompt.
        let mgr = ApprovalManager::for_non_interactive(&AutonomyConfig {
            level,
            auto_approve,
            always_ask: vec![],
        });
        let outcome = approval_authorize(
            Some(&mgr),
            "gpio_write",
            "bench-001",
            RiskClass::physical(true, BlastRadius::Low),
        );
        let verdict = match &outcome {
            Ok(()) => "PROCEEDS".to_string(),
            Err(reason) => format!("REFUSED — {reason}"),
        };
        let note = if granted {
            " (auto_approve = gpio_write)"
        } else {
            ""
        };
        println!("  autonomy {label}{note}\n      {verdict}\n");
    }

    println!(
        "The refusal says which of the two it is. A policy denial and a missing\n\
         grant call for different operator actions, and in an autonomous loop the\n\
         string is the only thing carrying that difference."
    );
}
