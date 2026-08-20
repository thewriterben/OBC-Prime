//! The playbook and the rules that carry it, checked against each other.
//!
//! `docs/playbooks/safing-escalations.md` is vendored here. So, since
//! 2026-08-20, is the rule library whose `Action::Escalate` reasons the playbook
//! is the long form of. Until that day only the prose was in this repository,
//! and `scripts/sync_upstream.py` said so where the playbooks are declared:
//! "the reason strings live in the agent's reflex rules, which are not in this
//! repository, so this side is the side that can be fixed."
//!
//! Both sides are here now, which means a reader who does not believe the
//! playbook no longer has to. This demo drives a real battery reading through
//! world memory into a real escalation and prints what the escalation actually
//! says, then holds the document and the code against each other.

use anyhow::Result;
use obc_memory::world::WorldMemory;
use obc_reflex::safing::{
    audio_alarm_escalate, overheat_escalate, sensor_unreliable_escalate, standard_safing_rules,
    SafingOptions,
};
use obc_reflex::ReflexEngine;
use obc_telemetry::power::{BatteryReading, ChargeState, PowerController, PowerThresholds};
use std::sync::Arc;

pub fn run() -> Result<()> {
    let opts = SafingOptions {
        debounce_ms: 1,
        ..Default::default()
    };

    println!("── the standard safing rules, as the crate emits them ──");
    let rules = standard_safing_rules(&opts);
    for r in &rules {
        println!("  {}", r.id);
    }
    println!("  {} rules\n", rules.len());

    // A real battery reading, classified by the real controller, written to
    // real world memory, read by the real engine. Nothing here is a fixture.
    let world = Arc::new(WorldMemory::open_in_memory()?);
    let power = PowerController::new(PowerThresholds {
        low_pct: 20.0,
        critical_pct: 10.0,
    })
    .with_world_memory(Arc::clone(&world));
    power.ingest(
        &BatteryReading {
            soc_pct: 4.0,
            voltage: None,
            current_a: None,
            charging: ChargeState::Discharging,
            source: Some("bms".to_string()),
        },
        1_000,
        obc_memory::world::Origin::Observed,
    )?;

    let fired = ReflexEngine::new(standard_safing_rules(&opts)).tick(&world, 10_000)?;
    println!("── 4% and discharging, one tick later ──");
    for f in &fired {
        println!("  {}", f.rule_id);
        if let obc_reflex::Action::Escalate { reason, .. } = &f.action {
            println!("      escalation carries: {}", first_sentence(reason));
            println!(
                "      full text is {} characters the model reads verbatim",
                reason.len()
            );
        }
    }
    if fired.is_empty() {
        anyhow::bail!("a 4% battery fired nothing — the rules are not wired");
    }
    println!();

    // ── The two sides, held against each other ───────────────────────────────
    //
    // Not "does the playbook mention each rule id" — it does not, and it should
    // not; a rule id is an implementation name and the document is written for
    // a person. The checkable claim is narrower and stronger.
    //
    // Every escalation ends `Full playbook: <path>[#anchor]`, and that string
    // goes to System 2 verbatim. So each pointer must name a file this
    // repository has, and each anchor must name a heading that file has. Rename
    // a heading and the escalation still reads perfectly while sending the model
    // to a fragment that is not there.
    println!("── every pointer an escalation carries ──");

    let mut checked = 0;
    for text in escalation_texts(&opts) {
        for (path, anchor) in pointers(&text) {
            checked += 1;
            let file = repo_root().join(&path);
            let here = file.exists();
            let doc = std::fs::read_to_string(&file).unwrap_or_default();
            let resolves = anchor.as_deref().is_none_or(|a| has_heading(&doc, a));
            let frag = anchor
                .as_deref()
                .map(|a| format!("#{a}"))
                .unwrap_or_default();
            println!(
                "  {path}{frag}\n      file here: {here}   anchor resolves: {}",
                anchor
                    .as_deref()
                    .map_or("n/a".into(), |_| resolves.to_string())
            );
            if !here {
                anyhow::bail!("an escalation sends a reader to {path}, which is not here");
            }
            if !resolves {
                anyhow::bail!("an escalation names {path}{frag}, and that heading is gone");
            }
        }
    }
    println!("  {checked} pointer(s), all resolving\n");

    println!(
        "  Both halves are in one repository. Before 2026-08-20 the check above\n  \
         could be described here and not run here."
    );
    Ok(())
}

/// The escalation reason of every rule in the standard set that escalates, plus
/// the two the standard set only emits when configured.
fn escalation_texts(opts: &SafingOptions) -> Vec<String> {
    let mut out: Vec<String> = standard_safing_rules(opts)
        .into_iter()
        .filter_map(|r| match r.then {
            obc_reflex::Action::Escalate { reason } => Some(reason),
            _ => None,
        })
        .collect();
    // Audio, sensor and overheat rules are per-configured-stream, so an empty
    // `SafingOptions` emits none of them. Ask for one of each by hand rather
    // than let the demo quietly check three fewer pointers than it claims.
    out.push(audio_alarm_escalate("cabin", opts).escalate_text());
    out.push(sensor_unreliable_escalate("humidity", opts).escalate_text());
    out.push(overheat_escalate("coolant", 90.0, opts).escalate_text());
    out
}

trait EscalateText {
    fn escalate_text(self) -> String;
}
impl EscalateText for obc_reflex::ReflexRule {
    fn escalate_text(self) -> String {
        match self.then {
            obc_reflex::Action::Escalate { reason } => reason,
            other => panic!("expected an escalation, got {other:?}"),
        }
    }
}

/// `("docs/playbooks/x.md", Some("anchor"))` for each `Full playbook:` pointer.
fn pointers(text: &str) -> Vec<(String, Option<String>)> {
    text.match_indices("Full playbook: ")
        .map(|(i, m)| {
            let rest = &text[i + m.len()..];
            let end = rest.find(|c: char| c.is_whitespace()).unwrap_or(rest.len());
            let raw = rest[..end].trim_end_matches('.');
            match raw.split_once('#') {
                Some((p, a)) => (p.to_string(), Some(a.to_string())),
                None => (raw.to_string(), None),
            }
        })
        .collect()
}

/// GitHub's anchor rule, enough of it: lowercase, spaces to hyphens.
fn has_heading(doc: &str, anchor: &str) -> bool {
    doc.lines().filter(|l| l.starts_with('#')).any(|l| {
        let title = l.trim_start_matches('#').trim().to_lowercase();
        let slug: String = title
            .chars()
            .filter(|c| c.is_alphanumeric() || c.is_whitespace() || *c == '-')
            .collect();
        slug.split_whitespace().collect::<Vec<_>>().join("-") == anchor
    })
}

fn repo_root() -> std::path::PathBuf {
    std::path::PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/.."))
}

fn first_sentence(s: &str) -> String {
    let cut = s.find(". ").map(|i| i + 1).unwrap_or(s.len().min(90));
    s[..cut].trim().to_string()
}
