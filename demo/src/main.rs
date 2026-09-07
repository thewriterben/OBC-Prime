//! Watch the vendored crates do the things this repository claims they do.
//!
//! Everything else here is a library or a hash. This is the first host binary
//! in the repository, and it exists because "1098 tests pass" and "you can see
//! it refuse" are different kinds of evidence, and only one of them survives
//! someone not trusting you.
//!
//! Each subcommand is deliberately small enough to read in full next to its
//! output. None of them mock anything: the gate is `obc_safety::SafetyGate`,
//! the planner is `obc_navigation::planning::plan`, the conscience is
//! `obc_conscience::Conscience`. If a demo prints "refused", a real
//! deterministic check refused it.
//!
//!     cargo run -p obc-demo -- gate
//!     cargo run -p obc-demo -- plan
//!     cargo run -p obc-demo -- conscience
//!     cargo run -p obc-demo -- track0
//!     cargo run -p obc-demo -- safing
//!     cargo run -p obc-demo -- bench

use anyhow::Result;

mod bench;
mod conscience;
mod gate;
mod plan;
mod safing;
mod track0;

const USAGE: &str = "\
obc-demo — run the vendored Open Body Control crates

USAGE:
    cargo run -p obc-demo -- <DEMO>

DEMOS:
    gate         Track 0 refusing an out-of-range actuator command
    plan         A* over an occupancy grid, with and without inflation
    conscience   the perception gate allowing wildlife and refusing a person
    track0       the same call gated or not, decided by the tool's own risk_class
    safing       the escalation playbook and the rules that carry it, checked
                 against each other — both vendored here since 2026-08-20
    bench        the Benchtop reference body's own Track 0 limit table, read
                 from its config.toml and run
";

#[tokio::main]
async fn main() -> Result<()> {
    let which = std::env::args().nth(1);
    match which.as_deref() {
        Some("gate") => gate::run().await,
        Some("plan") => plan::run(),
        Some("conscience") => conscience::run(),
        Some("track0") => track0::run(),
        Some("safing") => safing::run(),
        Some("bench") => bench::run(),
        Some(other) => {
            eprintln!("unknown demo '{other}'\n\n{USAGE}");
            std::process::exit(2);
        }
        None => {
            print!("{USAGE}");
            Ok(())
        }
    }
}
