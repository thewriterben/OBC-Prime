# Firmware — flashing guide

Four firmwares, for four jobs. Two are Rust on the Espressif toolchain; two are
Arduino sketches you can flash from the IDE with no Rust at all.

| Directory | Board | What it becomes |
|---|---|---|
| [`obc-esp32-s3/`](obc-esp32-s3/) | Waveshare ESP32-S3 Touch LCD 2.1, XIAO ESP32-S3, most ESP32-S3 | An **embodied node**: GPIO, sensors, on-MCU reflex + safing, Track 0 safety gate |
| [`heltec-lora-linktest/`](heltec-lora-linktest/) | Heltec WiFi LoRa 32 V3 (ESP32-S3 + SX1262) | A **LoRa spine gateway** — bridges a wired compute node onto the mesh |
| [`lora-node/`](lora-node/) | T-Beam, T-Deck, Heltec v2, RAK4631 *(Arduino)* | A **dumb USB-serial ⇄ LoRa modem** for the fleet mesh |
| [`t-deck-terminal/`](t-deck-terminal/) | LilyGO T-Deck / T-Deck Plus *(Arduino)* | A **handheld console** — screen, keyboard, and a drop-in replacement for the Heltec gateway |

> **These sources are vendored from the core agent repository**, where they are
> authored, and verified here by hash. Do not edit them in place — see
> [CONTRIBUTING.md](../CONTRIBUTING.md). Building here is fine (`target/` and
> `.embuild/` are ignored), but if the drift gate later reports a changed
> `Cargo.lock`, that is a dependency resolution having moved under you: re-sync
> rather than committing the new lock, or the vendored copy stops matching the
> firmware that upstream's test compiles. One of them is not only vendored but
> *compiled* upstream: `heltec-lora-linktest/src/spine.rs` is `#[path]`-included by a
> host-side test, so the frame codec and line framer are covered by ordinary
> `cargo test` rather than by hoping. That is why the firmware did not simply move
> here.

---

## If you have one ESP32-S3 and nothing else

Start with `obc-esp32-s3`. It is the only one that does something visible on its own:
the reflex and safing engines run on the microcontroller, so the board derives its own
power mode, watches a link-silence watchdog, and self-safes **with no host connected
at all**. That is the part of the safety story you can check yourself in ten minutes.

```bash
cargo install espup espflash
espup install
source ~/export-esp.sh              # Windows: %USERPROFILE%\export-esp.ps1

cd firmware/obc-esp32-s3
cargo run --release                 # builds, flashes, and opens the monitor
```

`cargo run` flashes because `.cargo/config.toml` sets `runner = "espflash flash
--monitor"`. The toolchain channel is pinned to `esp` in `rust-toolchain.toml`, so
you do not need to select it by hand — and it must stay pinned, because otherwise
rustup walks up to the workspace's `stable`, which has no Xtensa target.

Then talk to it: newline-terminated JSON in, newline-terminated JSON out, 115200 8N1.
[`obc-esp32-s3/BRINGUP.md`](obc-esp32-s3/BRINGUP.md) is an ordered runbook with the
exact command for each capability and what a healthy board returns, so a failure is
localized instead of mysterious.

**Read the "Status of on-board peripherals" note at the top of BRINGUP.md before you
believe a sensor reading.** `gpio_read`/`gpio_write`, the reflex/safing engine and the
Track 0 gate are real. `sensor_read`, `camera_capture` and `audio_sample` currently
return placeholder values pending the ESP-IDF drivers. The control path is genuine;
some perception values are canned, and the runbook says which.

### Windows: the path-length trap

`esp-idf-sys` aborts with `Too long output directory` on ordinary Windows paths, and
`subst` or a junction will not help — the check resolves the real path. Either build
under WSL2 on its native filesystem, or move the target directory to a short root:

```powershell
$env:CARGO_TARGET_DIR = "C:\e"
git config --global core.longpaths true
```

The crates already set `ESP_IDF_TOOLS_INSTALL_DIR = "custom:C:/esp"` for the same
reason: ESP-IDF ships test certificates whose full paths exceed 260 characters.

---

## Two boards: a LoRa link you can watch

`heltec-lora-linktest` on a Heltec WiFi LoRa 32 V3 is the spine gateway. Same
toolchain, same one-liner:

```bash
cd firmware/heltec-lora-linktest
cargo run --release
```

It emits a slow keepalive on its own, so a single board is still observable —
you see frames on the console before any second board exists. With two, you get
de-duplicated flood relay and a real link.

Wiring, for when you add a compute node: UART1 is the uplink (TX=GPIO4, RX=GPIO2,
115200 8N1); UART0 on GPIO43/44 is the USB console and is left alone. Wire the
compute node's TX to GPIO2 and tie the grounds. Radio is 915 MHz US ISM, SF7 /
BW 125 kHz / CR 4-5 — **change the region to match your regulatory domain before
transmitting.**

---

## No Rust toolchain: the Arduino sketches

`lora-node` and `t-deck-terminal` are `.ino` sketches. Open in the Arduino IDE with
ESP32 board support and RadioLib installed, select your board, flash.

`lora-node` is deliberately dumb: it relays opaque bytes and knows nothing about their
meaning. Every mesh semantic lives on the host, which is what lets the frame format
change without reflashing a single radio.

`t-deck-terminal` is the interesting one if you have the hardware — console, gateway
and relay at once, and a drop-in replacement for the Heltec base station with no host
changes. It has **no authority of its own**: a command it sends executes only if the
*target node's* on-MCU Track 0 mirror clears it. The handheld cannot talk a node into
exceeding its own bounds.

Two nets share the radio, toggled at runtime with `/net`: `spine` (SF7, sync `0x12`)
interoperates with the Heltec gateway and ESP32-S3 nodes; `fleet` (SF10, sync `0x2B`)
interoperates with `lora-node` bridges.

---

## What you cannot do yet

Flash a node, watch it self-safe, and put two radios on a link — all of that works
today with nothing else. **Talking to a node from an agent does not**, because the
core agent is not in this repository yet. See [PLAN.md](../PLAN.md) for the order
things land in. Better to say so here than to have you wire up a board and then go
looking for the half that is missing.
