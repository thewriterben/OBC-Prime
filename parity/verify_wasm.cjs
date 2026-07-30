#!/usr/bin/env node
/**
 * Execute the vendored WASM bundle against the vendored goldens.
 *
 * Why this exists
 * ---------------
 * Everything else in this directory compares *hashes*. Hashes prove nobody
 * hand-edited a file and, with `--upstream`, that the bundle was built from the
 * planner sources currently on disk. Neither proves the bundle *behaves*
 * correctly, and on 2026-07-29 that distinction was not academic: the vendored
 * bundle emitted a 79-line config where the golden had 119, with a hardcoded
 * `[provider] openai / gpt-4o`, and every hash matched.
 *
 * The assertion that would have caught it lives in the generator's vitest suite
 * — a different repository, with no CI, requiring an npm install. So the public
 * repo could not check its own headline claim. This can: the bundle is a
 * CommonJS `--target nodejs` build and the fixtures are right here, so it needs
 * node and nothing else. No npm install, no Rust, no network.
 *
 * What it does NOT cover: the TypeScript port (that is the generator's suite),
 * and whether the goldens themselves are right (that is the core repo's
 * `tests/planner_parity.rs`, which blesses them). This is one leg of three.
 *
 *   node parity/verify_wasm.cjs
 */
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const FIX = path.join(ROOT, "parity", "fixtures");
const BUNDLE = path.join(ROOT, "wasm", "obc-planner", "obc_planner_wasm.js");

const norm = (s) => s.replace(/\r\n/g, "\n").replace(/\s+$/, "");
const read = (p) => fs.readFileSync(p, "utf-8");
const golden = (p) => norm(read(p));

let failures = 0;

function compare(label, got, want) {
  if (got === want) {
    console.log(`  ✓ ${label}`);
    return;
  }
  failures++;
  const a = got.split("\n");
  const b = want.split("\n");
  console.log(`  ✗ ${label}`);
  console.log(`      got ${a.length} lines, golden has ${b.length}`);
  let shown = 0;
  for (let i = 0; i < Math.max(a.length, b.length) && shown < 8; i++) {
    if (a[i] !== b[i]) {
      console.log(`      line ${i + 1}`);
      console.log(`        bundle: ${JSON.stringify(a[i])}`);
      console.log(`        golden: ${JSON.stringify(b[i])}`);
      shown++;
    }
  }
  if (shown === 8) console.log("      (further differences suppressed)");
}

function assert(label, cond, detail) {
  if (cond) {
    console.log(`  ✓ ${label}`);
  } else {
    failures++;
    console.log(`  ✗ ${label}${detail ? ` — ${detail}` : ""}`);
  }
}

if (!fs.existsSync(BUNDLE)) {
  console.error(`no bundle at ${BUNDLE}`);
  process.exit(1);
}

let wasm;
try {
  wasm = require(BUNDLE);
} catch (e) {
  console.error(`could not load the bundle: ${e.message}`);
  console.error(
    "If this says 'Unexpected token export', the bundle was built --target web.\n" +
      "It must be --target nodejs; see parity/README.md."
  );
  process.exit(1);
}

console.log("wasm bundle behaviour, against the vendored goldens:\n");

const inventory = read(path.join(FIX, "deployment", "nanopi", "inventory.json"));
const siteCase = read(path.join(FIX, "siteplan", "square", "case.json"));

// The whole generated config, byte for byte. This is the assertion whose absence
// let a 17-day-stale bundle pass every check for weeks. Do not narrow it.
const scheme = JSON.parse(wasm.plan_deployment(inventory));
compare(
  "plan_deployment().config_toml == expected-config.toml",
  norm(scheme.config_toml),
  golden(path.join(FIX, "deployment", "nanopi", "expected-config.toml"))
);

compare(
  "deployment_toml() == expected-deployment.toml",
  norm(wasm.deployment_toml(inventory)),
  golden(path.join(FIX, "deployment", "nanopi", "expected-deployment.toml"))
);

compare(
  "plan_site().toml == expected-site.toml",
  norm(JSON.parse(wasm.plan_site(siteCase)).toml),
  golden(path.join(FIX, "siteplan", "square", "expected-site.toml"))
);

// The bundle carries its own copy of the registry. If it disagrees with the
// vendored registry.json, the bundle was built against a different one.
const bundled = JSON.parse(read(path.join(ROOT, "registry", "registry.json")));
const live = JSON.parse(wasm.registry_json());
assert(
  `registry matches registry.json (${live.boards.length} boards, ${live.accessories.length} accessories)`,
  live.boards.length === bundled.boards.length &&
    live.accessories.length === bundled.accessories.length &&
    wasm.registry_schema_version() === bundled.schema_version,
  `bundle ${live.boards.length}/${live.accessories.length} v${wasm.registry_schema_version()} vs ` +
    `vendored ${bundled.boards.length}/${bundled.accessories.length} v${bundled.schema_version}`
);

const roles = scheme.assignments.map((a) => a.role);
assert(
  "planner assigns orchestrator + vision_agent",
  roles.includes("orchestrator") && roles.includes("vision_agent"),
  `roles: ${roles.join(", ")}`
);

let threw = false;
try {
  wasm.plan_deployment("not json");
} catch {
  threw = true;
}
assert("malformed input throws rather than crashing", threw);

console.log("");
if (failures === 0) {
  console.log("ok: the vendored bundle behaves as the goldens say it should");
  process.exit(0);
}
console.log(`${failures} failure(s).`);
console.log(
  "A config_toml mismatch almost always means the bundle is a build of older\n" +
    "planner sources. Rebuild and re-sync:\n" +
    "  python scripts/sync_upstream.py sync --upstream ../Oh-Ben-Claw \\\n" +
    "      --peer ../OBC-deployment-generator --rebuild-wasm"
);
process.exit(1);
