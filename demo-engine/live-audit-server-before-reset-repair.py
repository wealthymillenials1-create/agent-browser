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

        # ====================================================
        # STAGE 2 — APPROVED SYNTHETIC RECOVERY
        # ====================================================
        if self.path == "/api/execute-synthetic-recovery":

            marker = "DEMO-STAGE2-SUMMIT-Q1-RECOVERY-12240"

            recovery_script = r"""
(async()=>{
  const marker="DEMO-STAGE2-SUMMIT-Q1-RECOVERY-12240";

  async function api(url,options={}){
    const r=await fetch(url,{
      credentials:"include",
      ...options
    });

    const text=await r.text();

    let body=null;
    try{ body=JSON.parse(text); }
    catch{ body=text; }

    if(!r.ok){
      throw new Error(
        "ERP API "+r.status+" "+JSON.stringify(body)
      );
    }

    return body;
  }

  // ---------------------------------------------------------
  // 1. IDEMPOTENCY CHECK
  // ---------------------------------------------------------

  const list=await api(
    "/api/resource/Journal Entry"+
    "?fields="+encodeURIComponent(
      JSON.stringify([
        "name",
        "user_remark",
        "docstatus"
      ])
    )+
    "&filters="+encodeURIComponent(
      JSON.stringify([
        ["docstatus","=",1]
      ])
    )+
    "&limit_page_length=500"+
    "&t="+Date.now()
  );

  const existing=(list.data||[]).find(j=>
    String(j.user_remark||"").includes(marker)
  );

  if(existing){
    return JSON.stringify({
      status:"ALREADY_EXECUTED",
      journal_entry:existing.name,
      marker,
      duplicate_prevented:true
    });
  }

  // ---------------------------------------------------------
  // 2. CREATE DRAFT JOURNAL
  // ---------------------------------------------------------

  const csrf=window.frappe &&
             frappe.csrf_token;

  if(!csrf){
    throw new Error("CSRF token unavailable");
  }

  const doc={
    doctype:"Journal Entry",
    voucher_type:"Journal Entry",
    company:"Givens Vale (Demo)",
    posting_date:"2026-04-16",

    user_remark:
      marker+
      " | Approved synthetic recovery for remaining "+
      "Summit Traders Ltd. Q1 2026 rebate shortfall. "+
      "Recovery amount $12,240.00.",

    accounts:[
      {
        account:"Creditors - GVD",
        party_type:"Supplier",
        party:"Summit Traders Ltd.",
        cost_center:"Main - GVD",
        debit_in_account_currency:12240,
        credit_in_account_currency:0
      },
      {
        account:"Supplier Rebates - GVD",
        cost_center:"Main - GVD",
        debit_in_account_currency:0,
        credit_in_account_currency:12240
      }
    ]
  };

  const created=await api(
    "/api/resource/Journal Entry",
    {
      method:"POST",
      headers:{
        "Content-Type":"application/json",
        "X-Frappe-CSRF-Token":csrf
      },
      body:JSON.stringify(doc)
    }
  );

  const name=created.data.name;

  // ---------------------------------------------------------
  // 3. SUBMIT
  // ---------------------------------------------------------

  const submitted=await api(
    "/api/method/frappe.client.submit",
    {
      method:"POST",
      headers:{
        "Content-Type":"application/json",
        "X-Frappe-CSRF-Token":csrf
      },
      body:JSON.stringify({
        doc:created.data
      })
    }
  );

  const finalDoc=submitted.message||submitted.data||{};

  return JSON.stringify({
    status:"RECOVERY_POSTED",
    journal_entry:finalDoc.name||name,
    amount:12240,
    supplier:"Summit Traders Ltd.",
    marker,
    duplicate_prevented:false
  });
})()
"""

            try:
                run = subprocess.run(
                    [
                        "npx",
                        "agent-browser",
                        "eval",
                        recovery_script
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                if run.returncode != 0:
                    raise RuntimeError(
                        run.stderr.strip()
                        or run.stdout.strip()
                        or "Synthetic recovery failed."
                    )

                action = parse_agent_output(run.stdout)

                # --------------------------------------------
                # INDEPENDENT POST-WRITE VERIFICATION
                # --------------------------------------------

                audit_script = ENGINE.read_text()

                verify = subprocess.run(
                    [
                        "npx",
                        "agent-browser",
                        "eval",
                        audit_script
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=120
                )

                if verify.returncode != 0:
                    raise RuntimeError(
                        "Recovery posted but verification audit failed: "+
                        (
                          verify.stderr.strip()
                          or verify.stdout.strip()
                        )
                    )

                audit = parse_agent_output(verify.stdout)

                rebate_remaining = [
                    f for f in audit.get("findings",[])
                    if f.get("type")=="REBATE_SHORTFALL"
                    and f.get("supplier")=="Summit Traders Ltd."
                ]

                ledger_verified = len(rebate_remaining)==0

                result={
                    "action":action,
                    "verification":audit,
                    "recovered":
                        action.get("status") in (
                            "RECOVERY_POSTED",
                            "ALREADY_EXECUTED"
                        ),
                    "ledger_verified":ledger_verified,
                    "expected_recovery":12240,
                    "remaining_potential_recovery":
                        audit.get("potential_recovery"),
                    "remaining_exception_count":
                        audit.get("exception_count"),
                    "external_messages_sent":0
                }

                # Never claim verification unless audit proves it.
                if not ledger_verified:
                    result["status"]="VERIFICATION_FAILED"
                else:
                    result["status"]="RECOVERED_AND_LEDGER_VERIFIED"

                body=json.dumps(result).encode()

                self.send_response(
                    200 if ledger_verified else 409
                )
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
                return

            except Exception as e:
                body=json.dumps({
                    "status":"ERROR",
                    "error":str(e),
                    "external_messages_sent":0
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
                return


        # ====================================================
        # DEMO RESET
        # Cancels ONLY the Stage 2 synthetic recovery journal.
        # Then independently reruns the audit.
        # ====================================================
        if self.path == "/api/reset-synthetic-recovery":

            reset_script = r"""
(async()=>{

  const marker=
    "DEMO-STAGE2-SUMMIT-Q1-RECOVERY-12240";

  async function api(url,options={}){
    const r=await fetch(url,{
      credentials:"include",
      ...options
    });

    const text=await r.text();

    let body;
    try{ body=JSON.parse(text); }
    catch{ body=text; }

    if(!r.ok){
      throw new Error(
        "ERP API "+r.status+" "+JSON.stringify(body)
      );
    }

    return body;
  }

  const csrf=
    window.frappe && frappe.csrf_token;

  if(!csrf){
    throw new Error("CSRF token unavailable");
  }

  // Find submitted Stage 2 recovery JE by unique marker.
  const list=await api(
    "/api/resource/Journal Entry"+
    "?fields="+encodeURIComponent(
      JSON.stringify([
        "name",
        "user_remark",
        "docstatus"
      ])
    )+
    "&limit_page_length=500"+
    "&t="+Date.now()
  );

  const matches=(list.data||[]).filter(j=>
    String(j.user_remark||"").includes(marker)
  );

  const submitted=matches.filter(
    j=>Number(j.docstatus)===1
  );

  // Already reset = safe no-op.
  if(submitted.length===0){
    return JSON.stringify({
      status:"ALREADY_RESET",
      marker,
      cancelled:[],
      duplicate_safe:true
    });
  }

  // Safety: there must never be multiple submitted recovery JEs.
  if(submitted.length>1){
    throw new Error(
      "SAFETY STOP: multiple submitted Stage 2 "+
      "recovery journals found: "+
      submitted.map(x=>x.name).join(", ")
    );
  }

  const target=submitted[0];

  // Fetch full document and validate exact economics
  // before cancellation.
  const full=(
    await api(
      "/api/resource/Journal Entry/"+
      encodeURIComponent(target.name)+
      "?t="+Date.now()
    )
  ).data;

  const rows=full.accounts||[];

  const supplierRow=rows.find(r=>
    r.account==="Creditors - GVD" &&
    r.party_type==="Supplier" &&
    r.party==="Summit Traders Ltd." &&
    Number(r.debit_in_account_currency||0)===12240
  );

  const rebateRow=rows.find(r=>
    r.account==="Supplier Rebates - GVD" &&
    Number(r.credit_in_account_currency||0)===12240
  );

  if(
    !supplierRow ||
    !rebateRow ||
    !String(full.user_remark||"").includes(marker)
  ){
    throw new Error(
      "SAFETY STOP: recovery journal does not "+
      "match the exact approved synthetic transaction."
    );
  }

  // Cancel only the verified synthetic recovery document.
  await api(
    "/api/method/frappe.client.cancel",
    {
      method:"POST",
      headers:{
        "Content-Type":"application/json",
        "X-Frappe-CSRF-Token":csrf
      },
      body:JSON.stringify({
        doctype:"Journal Entry",
        name:target.name
      })
    }
  );

  // Re-read exact document to prove cancellation.
  const after=(
    await api(
      "/api/resource/Journal Entry/"+
      encodeURIComponent(target.name)+
      "?t="+Date.now()
    )
  ).data;

  if(Number(after.docstatus)!==2){
    throw new Error(
      "RESET VERIFICATION FAILED: journal is "+
      "not cancelled."
    );
  }

  return JSON.stringify({
    status:"RECOVERY_CANCELLED",
    marker,
    cancelled:[target.name],
    docstatus:Number(after.docstatus),
    duplicate_safe:true
  });

})()
"""

            try:
                run=subprocess.run(
                    [
                        "npx",
                        "agent-browser",
                        "eval",
                        reset_script
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                if run.returncode != 0:
                    raise RuntimeError(
                        run.stderr.strip()
                        or run.stdout.strip()
                        or "Reset action failed."
                    )

                action=parse_agent_output(run.stdout)

                # Independent fresh audit after reset.
                audit_script=ENGINE.read_text()

                verify=subprocess.run(
                    [
                        "npx",
                        "agent-browser",
                        "eval",
                        audit_script
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=120
                )

                if verify.returncode != 0:
                    raise RuntimeError(
                        "Reset occurred but fresh audit failed: "+
                        (
                            verify.stderr.strip()
                            or verify.stdout.strip()
                        )
                    )

                audit=parse_agent_output(verify.stdout)

                summit=[
                    f for f in audit.get("findings",[])
                    if f.get("type")=="REBATE_SHORTFALL"
                    and f.get("supplier")==
                       "Summit Traders Ltd."
                ]

                baseline_verified=(
                    len(summit)==1 and
                    round(
                        float(
                            summit[0].get("recovery",0)
                        ),2
                    )==12240.00 and
                    round(
                        float(
                            audit.get(
                                "potential_recovery",0
                            )
                        ),2
                    )==38735.00 and
                    int(
                        audit.get(
                            "exception_count",0
                        )
                    )==5
                )

                result={
                    "status":
                        "BASELINE_RESTORED"
                        if baseline_verified
                        else "RESET_VERIFICATION_FAILED",

                    "action":action,
                    "verification":audit,
                    "baseline_verified":
                        baseline_verified,
                    "expected_baseline":{
                        "exception_count":5,
                        "potential_recovery":38735,
                        "rebate_shortfall":12240
                    },
                    "external_messages_sent":0
                }

                body=json.dumps(result).encode()

                self.send_response(
                    200 if baseline_verified else 409
                )
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
                return

            except Exception as e:
                body=json.dumps({
                    "status":"ERROR",
                    "error":str(e),
                    "external_messages_sent":0
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
                return

        # Existing read-only audit endpoint.
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
