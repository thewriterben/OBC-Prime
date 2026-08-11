//! Track 0: a deterministic limit table refusing a command the model asked for.
//!
//! This is the claim in docs/SAFETY.md, executed:
//!
//!     a compromised host, a poisoned skill, or a hallucinated tool call still
//!     cannot drive an actuator outside the limits the node itself holds
//!
//! Nothing here is a mock. `SafetyGate` is the same type the agent constructs,
//! `MovementController` is the same caller, and the refusal below is the same
//! code path a real actuator command takes.

use std::sync::Arc;

use anyhow::Result;
use obc_memory::world::WorldMemory;
use obc_movement::{LoggingActuatorSink, MovementCommand, MovementController};
use obc_safety::limits::{SafetyGate, SafetyLimit};

pub async fn run() -> Result<()> {
    // One limit: servo "pan" on channel 0, 20°–160°. Anything else is refused.
    let mut limit = SafetyLimit::new("bench", "servo_angle");
    limit.allowed_pins = Some(vec![0]);
    limit.value_min = Some(20);
    limit.value_max = Some(160);

    let world = Arc::new(WorldMemory::open_in_memory()?);
    let controller = MovementController::new(
        "bench",
        Arc::new(SafetyGate::new(vec![limit])),
        Arc::new(LoggingActuatorSink),
    )
    .with_world_memory(Arc::clone(&world))
    .with_source("obc-demo");

    println!("limit table: node=bench tool=servo_angle channel=0 range=20..=160\n");

    let attempts = [
        ("in range", 90.0),
        ("above the ceiling", 200.0),
        ("below the floor", 5.0),
    ];
    for (label, degrees) in attempts {
        let cmd = MovementCommand::ServoAngle {
            name: "pan".into(),
            channel: 0,
            degrees,
        };
        match controller.apply(&cmd, 1_000).await {
            Ok(applied) => println!(
                "  {degrees:>6.1}°  {label:<18} APPLIED   -> {}",
                applied.tool
            ),
            Err(e) => println!("  {degrees:>6.1}°  {label:<18} REFUSED   -> {e}"),
        }
    }

    // A channel the table does not mention at all.
    let cmd = MovementCommand::ServoAngle {
        name: "tilt".into(),
        channel: 3,
        degrees: 90.0,
    };
    match controller.apply(&cmd, 2_000).await {
        Ok(_) => println!("    90.0°  undeclared channel  APPLIED   <- this would be a bug"),
        Err(e) => println!("    90.0°  undeclared channel  REFUSED   -> {e}"),
    }

    // What the world remembers afterwards. The gate runs *before* the record,
    // so a refused command leaves nothing behind — it was never commanded.
    let facts = world.entities()?;
    println!("\nworld memory now holds {} actuator fact(s):", facts.len());
    for entity in facts {
        if let Some(fact) = world.current(&entity)? {
            println!("  {entity} = {}", fact.value);
        }
    }
    println!(
        "\nOne applied command, three refused, one fact remembered. A refusal is\n\
         not recorded as a commanded state, because it never became one."
    );
    Ok(())
}
