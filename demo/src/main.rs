//! Watch the vendored crates do the things this repository claims they do.
//!
//! Everything else here is a library or a hash. This is the first host binary
//! in the repository, and it exists because "653 tests pass" and "you can see
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

use anyhow::Result;

mod conscience;
mod gate;
mod plan;

const USAGE: &str = "\
obc-demo — run the vendored Open Body Control crates

USAGE:
    cargo run -p obc-demo -- <DEMO>

DEMOS:
    gate         Track 0 refusing an out-of-range actuator command
    plan         A* over an occupancy grid, with and without inflation
    conscience   the perception gate allowing wildlife and refusing a person
";

#[tokio::main]
async fn main() -> Result<()> {
    let which = std::env::args().nth(1);
    match which.as_deref() {
        Some("gate") => gate::run().await,
        Some("plan") => plan::run(),
        Some("conscience") => conscience::run(),
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
