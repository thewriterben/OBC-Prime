//! The perception gate: default-deny for people, opt-in for everything else.
//!
//! docs/CONSCIENCE.md describes a consent registry that fails closed. This runs
//! it. The interesting cases are not "wildlife allowed, person refused" — those
//! are the easy ones — but the label the classifier has never seen, and the
//! detection the model is not confident about. Both fail closed, and you can
//! watch them do it.

use anyhow::Result;
use obc_conscience::{Conscience, ConscienceConfig, ConsentRule, PerceptionDecision, Transmit};

pub fn run() -> Result<()> {
    let config = ConscienceConfig {
        enabled: true,
        // Deer may be observed for 30 days, weights only. Nothing else is
        // listed, and nothing else is therefore permitted.
        subjects: vec![ConsentRule::allow("wildlife", 30, Transmit::WeightsOnly)],
        confidence_threshold: 0.6,
        ..Default::default()
    };
    let conscience = Conscience::new(&config);

    println!(
        "registry: wildlife allowed (30 days, weights only). \
         Nothing else is listed.\nconfidence threshold: {:.2}\n",
        config.confidence_threshold
    );

    let frames = [
        ("deer", 0.91, "a listed class, confidently seen"),
        ("person", 0.98, "a human, seen very clearly"),
        ("deer", 0.30, "listed, but the model is unsure"),
        ("mailbox", 0.95, "a label the classifier has never seen"),
    ];

    for (label, confidence, note) in frames {
        let decision = conscience.may_perceive_label(label, confidence);
        let verdict = if decision.is_allowed() {
            "ALLOW "
        } else {
            "REFUSE"
        };
        println!("  {verdict}  {label:<8} @ {confidence:.2}   {note}");
        if let PerceptionDecision::Refuse(reason) = &decision {
            println!("            └─ {reason:?}");
        }
    }

    println!("\nreach gate: no hosts listed, so no tool may egress anywhere.");
    for (tool, host) in [("http_get", "example.com"), ("shell", "localhost")] {
        let d = conscience.may_reach(tool, host);
        let verdict = if d.is_allowed() { "ALLOW " } else { "REFUSE" };
        println!("  {verdict}  {tool} -> {host}");
    }

    println!(
        "\nThe two refusals worth noticing are the last perception pair: a listed\n\
         class below the confidence threshold, and a label nobody has classified.\n\
         Neither is a person, and both are refused. That is what fail-closed means."
    );
    Ok(())
}
