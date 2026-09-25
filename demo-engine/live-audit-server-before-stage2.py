from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone
import subprocess
import json
import os
import uuid

ROOT = Path("/workspaces/agent-browser")
OUTPUT = ROOT / "demo-output"
ENGINE = ROOT / "demo-engine" / "run-real-audit-v3-live.js"
ERP = "https://erpnext-dbe-squ.v.frappe.cloud/desk"

os.chdir(OUTPUT)

def parse_agent_output(raw):
    raw = raw.strip()
    if not raw:
        raise RuntimeError("Audit engine returned no output.")

    obj = json.loads(raw)

    if isinstance(obj, str):
        obj = json.loads(obj)

    return obj

class Handler(SimpleHTTPRequestHandler):

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):
        if self.path != "/api/run-audit":
            self.send_error(404)
            return

        run_id = "AUD-" + datetime.now(timezone.utc).strftime(
            "%Y%m%d-%H%M%S"
        ) + "-" + uuid.uuid4().hex[:6].upper()

        started = datetime.now(timezone.utc)

        try:
            # Ensure agent-browser is on authenticated ERP origin.
            opened = subprocess.run(
                [
                    "npx",
                    "agent-browser",
                    "open",
                    ERP
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30
            )

            if opened.returncode != 0:
                raise RuntimeError(
                    "Could not open authenticated ERP session."
                )

            script = ENGINE.read_text()

            run = subprocess.run(
                [
                    "npx",
                    "agent-browser",
                    "eval",
                    script
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=120
            )

            if run.returncode != 0:
                err = (
                    run.stderr.strip()
                    or run.stdout.strip()
                    or "Unknown audit-engine error."
                )
                raise RuntimeError(err)

            result = parse_agent_output(run.stdout)

            completed = datetime.now(timezone.utc)

            result["run_id"] = run_id
            result["started_at"] = started.isoformat()
            result["completed_at"] = completed.isoformat()
            result["duration_seconds"] = round(
                (completed-started).total_seconds(), 2
            )

            result["execution"] = {
                "source": "ERPNext",
                "mode": "READ_ONLY",
                "fresh_run": True,
                "engine": "V3_LIVE_FROM_VERIFIED_V2",
                "ground_truth_used": False,
                "external_actions": 0
            }

            # Current result consumed by dashboard.
            (OUTPUT / "live-audit.json").write_text(
                json.dumps(result, indent=2)
            )

            # Immutable-style run receipt.
            receipts = OUTPUT / "audit-receipts"
            receipts.mkdir(exist_ok=True)

            (receipts / f"{run_id}.json").write_text(
                json.dumps(result, indent=2)
            )

            body = json.dumps(result).encode()

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/json"
            )
            self.send_header(
                "Content-Length",
                str(len(body))
            )
            self.end_headers()
            self.wfile.write(body)

        except Exception as e:
            body = json.dumps({
                "audit_status": "ERROR",
                "error": str(e),
                "run_id": run_id,
                "external_actions": 0
            }).encode()

            self.send_response(500)
            self.send_header(
                "Content-Type",
                "application/json"
            )
            self.send_header(
                "Content-Length",
                str(len(body))
            )
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(
            "[LIVE AUDIT]",
            self.address_string(),
            fmt % args
        )

if __name__ == "__main__":
    server = ThreadingHTTPServer(
        ("127.0.0.1", 8081),
        Handler
    )

    print("========================================")
    print("RECOVERY CONTROL CENTER — LIVE")
    print("========================================")
    print("Dashboard:")
    print(
      "http://127.0.0.1:8081/"
      "recovery-control-center-pitch.html"
    )
    print()
    print("Audit endpoint: POST /api/run-audit")
    print("ERP mode: READ ONLY")
    print("External actions: DISABLED")
    print("Port: LOCALHOST ONLY")
    print("========================================")

    server.serve_forever()
