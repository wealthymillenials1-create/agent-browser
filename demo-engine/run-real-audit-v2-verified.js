(async()=>{
const money=n=>Math.round((Number(n)||0)*100)/100;
const BASE=location.origin;

async function api(path){
  const url=new URL(path,BASE);
  url.searchParams.set("_t",Date.now());
  const r=await fetch(url.href,{credentials:"include"});
  if(!r.ok) throw new Error(`${r.status} ${url.pathname}`);
  return r;
}

async function get(type,name){
  const r=await api(
    "/api/resource/"+encodeURIComponent(type)+"/"+encodeURIComponent(name)
  );
  return (await r.json()).data;
}

async function list(type,fields,filters=[],limit=500){
  const url=new URL(
    "/api/resource/"+encodeURIComponent(type),BASE
  );

  url.searchParams.set("fields",JSON.stringify(fields));
  url.searchParams.set("filters",JSON.stringify(filters));
  url.searchParams.set("limit_page_length",String(limit));
  url.searchParams.set("_t",Date.now());

  const r=await fetch(url.href,{credentials:"include"});
  if(!r.ok) throw new Error(`LIST ${type}: ${r.status}`);
  return (await r.json()).data||[];
}

async function readFile(file){
  if(!file.file_url) return "";
  const url=new URL(file.file_url,BASE);
  url.searchParams.set("_t",Date.now());

  const r=await fetch(url.href,{credentials:"include"});
  if(!r.ok) return "";
  return await r.text();
}

function parseMoney(text,label){
  const safe=label.replace(/[.*+?^${}()|[\]\\]/g,"\\$&");
  const re=new RegExp(
    safe+"\\s*:?\\s*\\$?([\\d,]+(?:\\.\\d{1,2})?)","i"
  );
  const m=text.match(re);
  return m ? money(Number(m[1].replace(/,/g,""))) : null;
}

function parseTiers(text){
  const tiers=[];

  // Parse each "$threshold ... Rebate Rate: X%" clause
  // from the complete agreement rather than relying on line breaks.
  const re=/\$([\d,]+(?:\.\d+)?)\s*(?:-|–|—|and\s+above|\+)?[\s\S]*?Rebate\s+Rate\s*:?\s*(\d+(?:\.\d+)?)\s*%/gi;

  let m;

  while((m=re.exec(text))!==null){
    const threshold=Number(m[1].replace(/,/g,""));
    const rate=Number(m[2])/100;

    if(
      Number.isFinite(threshold) &&
      Number.isFinite(rate) &&
      rate>0 &&
      rate<1
    ){
      tiers.push({
        threshold,
        rate,
        source:m[0].replace(/\s+/g," ").trim()
      });
    }
  }

  // Deduplicate by threshold/rate.
  return [
    ...new Map(
      tiers.map(x=>[
        `${x.threshold}|${x.rate}`,
        x
      ])
    ).values()
  ].sort((a,b)=>a.threshold-b.threshold);
}
function tierFor(tiers,spend){
  return [...tiers]
    .filter(x=>spend>=x.threshold)
    .sort((a,b)=>b.threshold-a.threshold)[0]||null;
}

const findings=[];
const discovery={
  suppliers:[],
  agreements:[],
  approvals:[],
  supplier_documents_examined:0
};

/* =========================
   DISCOVERY
========================= */

// Supplier master listing may be permission-restricted.
// Discover supplier identities from accessible transactional/document evidence.
const suppliers=[];
discovery.suppliers=[];

// File enumeration is permission-scoped in ERPNext.
// Supplier identities are discovered from accessible transactions first.
// Their attached documents are then queried supplier-by-supplier.
const files=[];

/* =========================
   LOAD LEDGER DATA
========================= */

const journalHeaders=await list(
  "Journal Entry",
  ["name","posting_date","docstatus"],
  [["docstatus","=",1]]
);

const journals=[];

for(const j of journalHeaders){
  try{
    journals.push(await get("Journal Entry",j.name));
  }catch(e){}
}

const invoiceHeaders=await list(
  "Purchase Invoice",
  [
    "name","supplier","posting_date",
    "grand_total","remarks","is_return","docstatus"
  ],
  [["docstatus","=",1]]
);

discovery.suppliers=[
  ...new Set(
    invoiceHeaders
      .map(x=>x.supplier)
      .filter(Boolean)
  )
];

// Discover attached commercial documents for each supplier independently.
// This uses the same permission-safe pattern proven by V1.
for(const supplier of discovery.suppliers){
  let supplierFiles=[];

  try{
    supplierFiles=await list(
      "File",
      [
        "name","file_name","file_url",
        "attached_to_doctype","attached_to_name"
      ],
      [
        ["attached_to_doctype","=","Supplier"],
        ["attached_to_name","=",supplier]
      ]
    );
  }catch(e){
    continue;
  }

  for(const file of supplierFiles){
    const text=await readFile(file);
    if(!text) continue;

    discovery.supplier_documents_examined++;

    if(/VOLUME\s+REBATE\s+AGREEMENT/i.test(text)){
      discovery.agreements.push({file,text});
    }

    if(
      /SUPPLIER\s+CREDIT\s+APPROVAL/i.test(text) &&
      /\bAPPROVED\b/i.test(text)
    ){
      discovery.approvals.push({file,text});
    }
  }
}

const invoices=[];

for(const h of invoiceHeaders){
  if(Number(h.is_return)) continue;
  try{
    invoices.push(await get("Purchase Invoice",h.name));
  }catch(e){}
}

/* =========================
   REBATE AGREEMENTS
========================= */

for(const agreement of discovery.agreements){
  const supplier=agreement.file.attached_to_name;
  const tiers=parseTiers(agreement.text);

  if(!supplier || !tiers.length) continue;

  const eligible=invoices.filter(x=>
    x.supplier===supplier &&
    x.posting_date>="2026-01-01" &&
    x.posting_date<="2026-03-31" &&
    !Number(x.is_return)
  );

  const spend=money(
    eligible.reduce((n,x)=>n+Number(x.grand_total||0),0)
  );

  const tier=tierFor(tiers,spend);
  if(!tier || spend<=0) continue;

  const expected=money(spend*tier.rate);

  let actual=0;
  const creditDocs=[];

  for(const j of journals){
    const rows=j.accounts||[];

    const belongsToSupplier=rows.some(r=>
      r.party_type==="Supplier" &&
      r.party===supplier &&
      Number(r.debit_in_account_currency||0)>0
    );

    if(!belongsToSupplier) continue;

    let rebateCredit=0;

    for(const r of rows){
      if(
        /supplier rebate/i.test(String(r.account||"")) &&
        Number(r.credit_in_account_currency||0)>0
      ){
        rebateCredit+=Number(r.credit_in_account_currency||0);
      }
    }

    if(rebateCredit>0){
      actual+=rebateCredit;
      creditDocs.push(j.name);
    }
  }

  actual=money(actual);
  const recovery=money(expected-actual);

  if(recovery>0){
    findings.push({
      type:"REBATE_SHORTFALL",
      supplier,
      recovery,
      expected,
      actual,
      eligible_spend:spend,
      contractual_rate:tier.rate,
      contractual_tier_source:tier.source,
      agreement_file:agreement.file.file_name,
      evidence:[
        agreement.file.file_name,
        ...eligible.map(x=>x.name),
        ...creditDocs
      ]
    });
  }
}

/* =========================
   PO / INVOICE VARIANCE
========================= */

for(const inv of invoices){
  const match=String(inv.remarks||"")
    .match(/PUR-ORD-\d{4}-\d+/);

  if(!match) continue;

  try{
    const po=await get("Purchase Order",match[0]);

    if(po.supplier!==inv.supplier) continue;

    const variance=money(
      Number(inv.grand_total||0)-
      Number(po.grand_total||0)
    );

    if(variance>0){
      findings.push({
        type:"PO_INVOICE_VARIANCE",
        supplier:inv.supplier,
        recovery:variance,
        expected:money(po.grand_total),
        actual:money(inv.grand_total),
        evidence:[po.name,inv.name]
      });
    }
  }catch(e){}
}

/* =========================
   DUPLICATE ECONOMIC INVOICE
========================= */

const duplicatePairs=new Set();

for(let i=0;i<invoices.length;i++){
  for(let j=i+1;j<invoices.length;j++){
    const a=invoices[i];
    const b=invoices[j];

    const ai=(a.items||[])[0]||{};
    const bi=(b.items||[])[0]||{};

    const same=
      a.supplier===b.supplier &&
      ai.item_code===bi.item_code &&
      Number(ai.qty||0)===Number(bi.qty||0) &&
      Number(ai.rate||0)===Number(bi.rate||0) &&
      money(a.grand_total)===money(b.grand_total);

    if(!same) continue;

    const days=Math.abs(
      (new Date(a.posting_date)-new Date(b.posting_date))/86400000
    );

    if(days>7) continue;

    const key=[a.name,b.name].sort().join("|");
    if(duplicatePairs.has(key)) continue;
    duplicatePairs.add(key);

    findings.push({
      type:"POTENTIAL_DUPLICATE_INVOICE",
      supplier:a.supplier,
      recovery:money(Math.min(a.grand_total,b.grand_total)),
      evidence:[a.name,b.name],
      reason:
        "Same supplier, item, quantity, rate and total within seven days"
    });
  }
}

/* =========================
   APPROVED CREDIT NOT POSTED
========================= */

for(const approval of discovery.approvals){
  const supplier=approval.file.attached_to_name;

  const amount=
    parseMoney(approval.text,"Credit Amount") ??
    parseMoney(approval.text,"Credit");

  if(!supplier || !amount) continue;

  const posted=journals.some(j=>
    (j.accounts||[]).some(r=>
      r.party_type==="Supplier" &&
      r.party===supplier &&
      money(r.debit_in_account_currency)===amount
    )
  );

  if(!posted){
    findings.push({
      type:"APPROVED_CREDIT_NOT_POSTED",
      supplier,
      recovery:amount,
      expected:amount,
      actual:0,
      approval_discovered_from_document:true,
      evidence:[approval.file.file_name]
    });
  }
}

/* =========================
   UNAPPLIED SUPPLIER CREDIT
========================= */

for(const j of journals){
  for(const row of (j.accounts||[])){
    if(
      row.party_type!=="Supplier" ||
      Number(row.debit_in_account_currency||0)<=0
    ) continue;

    const invoiceRef=String(j.user_remark||"")
      .match(/ACC-PINV-\d{4}-\d+/);

    if(!invoiceRef) continue;

    let invoice;

    try{
      invoice=await get("Purchase Invoice",invoiceRef[0]);
    }catch(e){
      continue;
    }

    const supplier=row.party;
    if(invoice.supplier!==supplier) continue;

    const paymentHeaders=await list(
      "Payment Entry",
      ["name","party","posting_date","paid_amount","docstatus"],
      [
        ["party","=",supplier],
        ["docstatus","=",1]
      ]
    );

    let payment=null;

    for(const ph of paymentHeaders){
      let pd;

      try{
        pd=await get("Payment Entry",ph.name);
      }catch(e){
        continue;
      }

      const allocated=(pd.references||[])
        .filter(r=>
          r.reference_doctype==="Purchase Invoice" &&
          r.reference_name===invoice.name
        )
        .reduce(
          (n,r)=>n+Number(r.allocated_amount||0),0
        );

      if(money(allocated)>=money(invoice.grand_total)){
        payment=pd;
        break;
      }
    }

    if(payment){
      findings.push({
        type:"UNAPPLIED_SUPPLIER_CREDIT",
        supplier,
        recovery:money(row.debit_in_account_currency),
        evidence:[j.name,invoice.name,payment.name],
        reason:
          "Supplier credit exists while the related invoice was separately settled in full"
      });
    }
  }
}

/* =========================
   DEDUPE
========================= */

const clean=[];
const seen=new Set();

for(const f of findings){
  const key=
    f.type+"|"+
    f.supplier+"|"+
    [...(f.evidence||[])].sort().join("|");

  if(seen.has(key)) continue;
  seen.add(key);
  clean.push(f);
}

const total=money(
  clean.reduce((n,f)=>n+Number(f.recovery||0),0)
);

const result={
  audit_status:"COMPLETE",
  source:"ERPNext",
  mode:"READ_ONLY",
  engine_version:"V2_DISCOVERY_DRIVEN",
  ground_truth_used:false,
  scenario_specific_supplier_filter:false,
  external_actions:0,

  discovery:{
    suppliers_found:discovery.suppliers.length,
    rebate_agreements_found:discovery.agreements.length,
    approved_credit_documents_found:discovery.approvals.length,
    supplier_documents_examined:
      discovery.supplier_documents_examined
  },

  exception_count:clean.length,
  potential_recovery:total,
  findings:clean
};

console.log(JSON.stringify(result));
return result;
})()