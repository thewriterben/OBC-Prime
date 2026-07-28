#!/usr/bin/env python3
"""
Trailwatch perception server — a minimal MCP stdio server over the seeded DB.

Why this exists
---------------
A Reference Body has to run on a clean checkout. The production perception
source for this body is the ClawCam gateway, which is a separate project with
its own virtualenv and dependencies — so depending on it would mean nobody
could try Trailwatch without first installing something else.

This serves the same MCP surface from the seeded SQLite next to it, using only
the Python standard library. It is deliberately small and readable: as well as
making the quickstart real, it documents the contract a perception source has
to satisfy to plug into Open Body Control.

The contract
------------
JSON-RPC 2.0, one message per line, on stdin/stdout. Three methods:

    initialize   -> {protocolVersion, capabilities, serverInfo}
    tools/list   -> {tools: [{name, description, inputSchema}]}
    tools/call   -> {content: [{type: "text", text: "<json>"}], isError: bool}

Note the shape of `tools/call`: the agent reads `content[0].text` and parses
*that string* as JSON. The payload is not the JSON-RPC result itself. Getting
this wrong is the most common way a perception source silently returns nothing.

Read tools (polled): list_species_detections, get_anomaly_report,
get_encounter_report, get_calibration_report.
Write tools (reflex actuation): capture_now, set_device_state,
create_alert_rule — recorded to `pending_commands`, since a seeded body has no
camera to actually command.

Run:  python serve.py [--db clawcam_gateway.db]
It speaks on stdio, so run it via the agent, not by hand.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "trailwatch-perception"
SERVER_VERSION = "1.0.0"

DB: sqlite3.Connection | None = None


def log(msg: str) -> None:
    # stdout is the protocol channel — diagnostics must go to stderr or they
    # corrupt the stream and the agent sees a parse error instead of a tool.
    print(f"[trailwatch] {msg}", file=sys.stderr, flush=True)


# ────────────────────────────────────────────────────────────── tools ──

def list_species_detections(args: dict) -> dict:
    """Classifications, newest first.

    Field names are fixed by the agent's ingest struct (ClawCamDetection):
    event_id, device_id, top_label, top_confidence, top_species, review_state,
    ran_at. `ran_at` becomes the fact's valid-time in world memory, so it must
    be RFC-3339 or the ingest falls back to "now" and the history is wrong.
    """
    min_conf = float(args.get("min_confidence") or 0.0)
    limit = int(args.get("limit") or 50)
    device = args.get("device_id")

    # device_id lives on `events`, not on the classification row — a detection
    # knows which event produced it, and the event knows which camera. Reading
    # device_id off inference_results looks right and returns nothing.
    sql = """
        SELECT ir.event_id, e.device_id, ir.top_label, ir.top_confidence,
               ir.top_species, ir.review_state, ir.ran_at
        FROM inference_results ir
        LEFT JOIN events e ON e.event_id = ir.event_id
        WHERE COALESCE(ir.top_confidence, 0) >= ?
    """
    params: list = [min_conf]
    if device:
        sql += " AND e.device_id = ?"
        params.append(device)
    sql += " ORDER BY ir.ran_at DESC LIMIT ?"
    params.append(limit)

    rows = [dict(r) for r in DB.execute(sql, params)]
    for r in rows:
        if not r.get("review_state"):
            r["review_state"] = "unreviewed"
    return {"results": rows, "count": len(rows)}


def _daily_counts() -> list[tuple[str, int]]:
    rows = DB.execute("""
        SELECT substr(ran_at, 1, 10) AS day, COUNT(*) AS n
        FROM inference_results
        WHERE ran_at IS NOT NULL
        GROUP BY day ORDER BY day
    """).fetchall()
    return [(r["day"], r["n"]) for r in rows]


def get_anomaly_report(args: dict) -> dict:
    """Daily detection counts with a z-score per day.

    The agent reads report.series[-1] and escalates when `anomaly` is true, so
    the series must be chronological — last element is the most recent day.
    """
    daily = _daily_counts()
    counts = [n for _, n in daily]
    mean = sum(counts) / len(counts) if counts else 0.0
    var = sum((c - mean) ** 2 for c in counts) / len(counts) if counts else 0.0
    sd = math.sqrt(var)
    z_threshold = float(args.get("z_threshold") or 2.0)

    series = []
    for day, n in daily:
        z = (n - mean) / sd if sd > 0 else 0.0
        series.append({
            "date": day,
            "count": n,
            "z": round(z, 3),
            "anomaly": abs(z) >= z_threshold,
        })

    return {
        "ok": True,
        "report": {
            "kind": "daily_detections",
            "series": series,
            "mean": round(mean, 3),
            "days": len(series),
            "z_threshold": z_threshold,
        },
    }


def get_encounter_report(args: dict) -> dict:
    """Encounters per subject.

    An encounter is a run of detections of the same subject separated by less
    than `gap_minutes` — so twenty frames of one deer is one encounter, not
    twenty. Without that the counts describe the frame rate, not the wildlife.
    """
    gap_minutes = float(args.get("gap_minutes") or 30.0)
    rows = DB.execute("""
        SELECT COALESCE(NULLIF(top_species, ''), NULLIF(top_label, ''), 'unknown') AS subject,
               ran_at
        FROM inference_results
        WHERE ran_at IS NOT NULL
        ORDER BY subject, ran_at
    """).fetchall()

    by_subject: dict[str, dict] = defaultdict(lambda: {"detections": 0, "encounters": 0})
    last_seen: dict[str, datetime] = {}

    for r in rows:
        subject, ts = r["subject"], _parse(r["ran_at"])
        entry = by_subject[subject]
        entry["detections"] += 1
        prev = last_seen.get(subject)
        if prev is None or (ts and (ts - prev).total_seconds() / 60.0 > gap_minutes):
            entry["encounters"] += 1
        if ts:
            last_seen[subject] = ts

    total_detections = sum(v["detections"] for v in by_subject.values())
    total_encounters = sum(v["encounters"] for v in by_subject.values())
    return {
        "ok": True,
        "total_encounters": total_encounters,
        "total_detections": total_detections,
        "by_subject": dict(by_subject),
        "gap_minutes": gap_minutes,
    }


def get_calibration_report(args: dict) -> dict:
    """How well model confidence agrees with human review.

    Only reviewed rows can say anything about precision: an unreviewed
    detection has no ground truth. `well_calibrated` false is what drives the
    calibration-drift escalation.
    """
    target_precision = float(args.get("target_precision") or 0.9)
    rows = DB.execute("""
        SELECT top_confidence, review_state
        FROM inference_results
        WHERE review_state IS NOT NULL AND review_state != 'unreviewed'
    """).fetchall()

    total = DB.execute("SELECT COUNT(*) AS n FROM inference_results").fetchone()["n"]
    reviewed = len(rows)
    if not reviewed:
        return {
            "ok": True, "reviewed": 0.0, "well_calibrated": True,
            "suggested_threshold": None, "overall_precision": None,
            "target_precision": target_precision,
            "note": "no reviewed detections — calibration is unknown, not good",
        }

    confirmed = [r for r in rows if r["review_state"] in ("verified", "confirmed")]
    precision = len(confirmed) / reviewed

    # Lowest confidence threshold that would reach the target precision.
    suggested = None
    for step in range(50, 100):
        t = step / 100.0
        kept = [r for r in rows if (r["top_confidence"] or 0) >= t]
        if not kept:
            break
        good = [r for r in kept if r["review_state"] in ("verified", "confirmed")]
        if len(good) / len(kept) >= target_precision:
            suggested = t
            break

    return {
        "ok": True,
        "reviewed": round(reviewed / total, 3) if total else 0.0,
        "reviewed_count": reviewed,
        "well_calibrated": precision >= target_precision,
        "suggested_threshold": suggested,
        "overall_precision": round(precision, 3),
        "target_precision": target_precision,
    }


def _record_command(kind: str, payload: dict) -> dict:
    """A seeded body has no camera. Record the intent so the reflex path is
    observable end to end, and be explicit that nothing physical happened."""
    now = datetime.now(timezone.utc).isoformat()
    DB.execute(
        "INSERT INTO pending_commands "
        "(command_type, device_id, status, payload_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (kind, payload.get("device_id") or "node-001", "simulated",
         json.dumps(payload), now, now),
    )
    DB.commit()
    return {"ok": True, "simulated": True, "command": kind,
            "note": "recorded to pending_commands; this body has no physical camera"}


def capture_now(args: dict) -> dict:
    return _record_command("capture_now", args)


def set_device_state(args: dict) -> dict:
    return _record_command("set_device_state", args)


def create_alert_rule(args: dict) -> dict:
    return _record_command("create_alert_rule", args)


def _parse(ts: str | None):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


TOOLS = {
    "list_species_detections": (list_species_detections,
        "List AI species classifications, newest first, optionally filtered by confidence.",
        {"type": "object", "properties": {
            "min_confidence": {"type": "number", "description": "Drop detections below this confidence (0-1)."},
            "device_id": {"type": "string", "description": "Only this camera."},
            "limit": {"type": "integer", "description": "Max rows (default 50)."}}}),
    "get_anomaly_report": (get_anomaly_report,
        "Daily detection counts with a z-score per day, flagging unusual days.",
        {"type": "object", "properties": {
            "z_threshold": {"type": "number", "description": "Flag days at or beyond this |z| (default 2)."}}}),
    "get_encounter_report": (get_encounter_report,
        "Encounters per subject, grouping runs of detections separated by less than gap_minutes.",
        {"type": "object", "properties": {
            "gap_minutes": {"type": "number", "description": "Gap that separates encounters (default 30)."}}}),
    "get_calibration_report": (get_calibration_report,
        "Agreement between model confidence and human review, with a suggested accept threshold.",
        {"type": "object", "properties": {
            "target_precision": {"type": "number", "description": "Precision to solve for (default 0.9)."}}}),
    "capture_now": (capture_now,
        "Ask a camera to capture immediately. Simulated in this body.",
        {"type": "object", "properties": {"device_id": {"type": "string"}}, "required": ["device_id"]}),
    "set_device_state": (set_device_state,
        "Arm or disarm a camera. Simulated in this body.",
        {"type": "object", "properties": {"device_id": {"type": "string"}, "state": {"type": "string"}}}),
    "create_alert_rule": (create_alert_rule,
        "Create an alert rule. Simulated in this body.",
        {"type": "object", "properties": {}}),
}


# ─────────────────────────────────────────────────────────── protocol ──

def handle(req: dict) -> dict | None:
    method, req_id = req.get("method"), req.get("id")

    # Notifications have no id and must not be answered.
    if req_id is None:
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    if method == "initialize":
        # Echo the client's protocol version when we recognise it; the agent
        # speaks either the 2024 legacy or the 2026 stateless dialect and both
        # are fine here, since we only implement the common core.
        asked = (req.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        return ok({
            "protocolVersion": asked,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "tools/list":
        return ok({"tools": [
            {"name": name, "description": desc, "inputSchema": schema}
            for name, (_fn, desc, schema) in TOOLS.items()
        ]})

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        entry = TOOLS.get(name)
        if not entry:
            return ok({"content": [{"type": "text", "text": json.dumps(
                {"ok": False, "error": f"unknown tool: {name}"})}], "isError": True})
        try:
            payload = entry[0](args)
            # The agent parses content[0].text as JSON — not the result object.
            return ok({"content": [{"type": "text", "text": json.dumps(payload)}],
                       "isError": False})
        except Exception as exc:  # noqa: BLE001
            log(f"{name} failed: {exc}")
            return ok({"content": [{"type": "text", "text": json.dumps(
                {"ok": False, "error": str(exc)})}], "isError": True})

    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def main() -> int:
    global DB
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(here / "clawcam_gateway.db"),
                    help="seeded SQLite database (default: next to this script)")
    args = ap.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        log(f"database not found: {db_path}")
        return 2

    DB = sqlite3.connect(str(db_path), check_same_thread=False)
    DB.row_factory = sqlite3.Row
    n = DB.execute("SELECT COUNT(*) AS n FROM inference_results").fetchone()["n"]
    log(f"serving {n} detections from {db_path.name}")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            log(f"bad JSON on stdin: {exc}")
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main())
