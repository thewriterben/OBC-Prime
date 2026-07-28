# Reference Bodies

A Reference Body is a complete, runnable deployment: config, firmware, and —
where possible — a seeded database so **it runs before any hardware arrives**.

Not demos. Working templates, each one a deployment that has actually been run
end to end, which you can generate as-is or use as the starting point for your
own.

| Body | What it is | Hardware to try it |
|---|---|---|
| [`trailwatch`](trailwatch) | Wildlife / perimeter camera. Detections into world memory, reflexes on verified person detections, mesh node health over LoRa. | None — ships with 14 days of seeded data |
| [`benchtop`](benchtop) | One ESP32-S3 over serial with a sensor, plus a small Linux host. The five-minute on-ramp. | A host SBC and one dev board |

**Benchtop needs hardware, and says so.** It ships no seeded database, because a
fabricated sensor history would be teaching you to trust numbers nobody measured.
Its README carries a table of what has been verified (the config parses and
starts, the `[deployment]` block is planner-emitted, the hardware resolves with
zero gaps) and what has not (the sensor actually firing the reflex, the Track 0
limit refusing a command on a physical node). A reference body you cannot run is
still worth shipping if it is honest about which half you are getting.

## Two halves

Each body exists in two places, and they are kept deliberately consistent:

- **Here** — the runtime half. `config.toml`, seeded data, and the notes on why
  each threshold is what it is.
- **In the deployment generator** — the inventory half, in
  `lib/reference-bodies.ts`. Loading a body there fills the wizard with the same
  hardware, so the generator emits the deployment this directory describes.

The generator's `tests/reference-bodies.test.ts` enforces the properties that
make a template trustworthy:

- every board and accessory name resolves in the registry — a template naming a
  board that was renamed upstream would otherwise produce a scheme with no
  capabilities, silently
- the planner reports **zero capability gaps** — a Reference Body that warns
  about missing hardware is a broken template by definition
- every board reaches the emitted TOML
- `instantiate()` deep-copies, so loading a body twice in one session doesn't
  hand you whatever you did to it the first time

## Writing a new one

1. Add the inventory to `lib/reference-bodies.ts` in the generator.
2. Run the suite. The gap-warning test will tell you if the hardware doesn't
   actually satisfy the desires you claimed — trust it over your intuition
   about what a board can do. Two examples from building these two:
   - Trailwatch originally claimed `EdgeInference` with no accelerator board.
   - Benchtop originally used a bare `esp32-s3`, which carries `camera_capture`
     and `audio_sample`, so the planner claimed it as a vision or audio agent
     before sensing was considered — then reported "no sensor_read hardware
     found" about the board that was holding the sensor.
3. Add the runtime half here: `config.toml`, any seeded data, and a README that
   says what it's for and what to change to repurpose it.
