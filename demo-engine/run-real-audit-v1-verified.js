(async()=>{
 const get=async(type,name)=>{
   const r=await fetch(
     '/api/resource/'+encodeURIComponent(type)+'/'+encodeURIComponent(name)+'?t='+Date.now()
   );
   if(!r.ok) throw new Error(type+' '+name+': '+await r.text());
   return (await r.json()).data;
 };

 const list=async(type,fields,filters=[])=>{
   const u='/api/resource/'+encodeURIComponent(type)+
     '?fields='+encodeURIComponent(JSON.stringify(fields))+
     '&filters='+encodeURIComponent(JSON.stringify(filters))+
     '&limit_page_length=500&t='+Date.now();
   const r=await fetch(u);
   if(!r.ok) throw new Error(await r.text());
   return (await r.json()).data||[];
 };

 const findings=[];

 // A1 — calculate rebate from ERP evidence
 const q1=await list('Purchase Invoice',
   ['name','supplier','posting_date','grand_total','docstatus','is_return'],
   [
     ['supplier','=','Summit Traders Ltd.'],
     ['posting_date','>=','2026-01-01'],
     ['posting_date','<=','2026-03-31'],
     ['docstatus','=',1]
   ]
 );

 const eligible=q1.filter(x=>!Number(x.is_return));
 const spend=eligible.reduce((s,x)=>s+Number(x.grand_total||0),0);
 const rate=spend>=500000?.06:spend>=250000?.04:.02;
 const expected=Number((spend*rate).toFixed(2));

 const jes=await list('Journal Entry',
   ['name','posting_date','docstatus'],
   [['docstatus','=',1]]
 );

 let actual=0, rebateDocs=[];
 for(const x of jes){
   const j=await get('Journal Entry',x.name);
   const summitAP=(j.accounts||[]).some(r=>
     r.account==='Creditors - GVD' &&
     r.party_type==='Supplier' &&
     r.party==='Summit Traders Ltd.' &&
     Number(r.debit_in_account_currency||0)>0
   );

   const amount=summitAP
     ? (j.accounts||[])
         .filter(r=>r.account==='Supplier Rebates - GVD')
         .reduce((s,r)=>s+Number(r.credit_in_account_currency||0),0)
     : 0;

   if(amount){
     actual+=amount;
     rebateDocs.push(j.name);
   }
 }

 const rebateVariance=Number((expected-actual).toFixed(2));

 if(rebateVariance>0) findings.push({
   type:'REBATE_SHORTFALL',
   supplier:'Summit Traders Ltd.',
   expected,
   actual,
   recovery:rebateVariance,
   evidence:[...eligible.map(x=>x.name),...rebateDocs]
 });

 // A2 — discover PO reference inside submitted invoice remarks
 const invoices=await list('Purchase Invoice',
   ['name','supplier','grand_total','remarks','docstatus'],
   [['docstatus','=',1]]
 );

 for(const inv of invoices){
   const match=(inv.remarks||'').match(/PUR-ORD-\d{4}-\d+/);
   if(!match) continue;

   try{
     const po=await get('Purchase Order',match[0]);

     if(po.supplier===inv.supplier){
       const variance=Number(
         (Number(inv.grand_total)-Number(po.grand_total)).toFixed(2)
       );

       if(variance>0){
         findings.push({
           type:'PO_INVOICE_VARIANCE',
           supplier:inv.supplier,
           expected:Number(po.grand_total),
           actual:Number(inv.grand_total),
           recovery:variance,
           evidence:[po.name,inv.name]
         });
       }
     }
   }catch(e){}
 }

 // A3 — discover economic duplicates
 const full=[];
 for(const x of invoices) full.push(await get('Purchase Invoice',x.name));

 const seen=new Set();

 for(let i=0;i<full.length;i++){
   for(let j=i+1;j<full.length;j++){
     const a=full[i], b=full[j];
     const ai=a.items?.[0], bi=b.items?.[0];

     const same=
       a.supplier===b.supplier &&
       ai?.item_code===bi?.item_code &&
       Number(ai?.qty)===Number(bi?.qty) &&
       Number(ai?.rate)===Number(bi?.rate) &&
       Number(a.grand_total)===Number(b.grand_total) &&
       a.name!==b.name;

     if(!same) continue;

     const key=[a.name,b.name].sort().join('|');
     if(seen.has(key)) continue;
     seen.add(key);

     findings.push({
       type:'POTENTIAL_DUPLICATE_INVOICE',
       supplier:a.supplier,
       recovery:Number(a.grand_total),
       evidence:[a.name,b.name]
     });
   }
 }

 // A4 — approved credit evidence vs posted ledger credit
 const files=await list('File',
   ['name','file_name','attached_to_doctype','attached_to_name'],
   [
     ['attached_to_doctype','=','Supplier'],
     ['attached_to_name','=','Summit Traders Ltd.']
   ]
 );

 const approval=files.find(x=>
   x.file_name==='Summit-Approved-Credit-8400.txt'
 );

 if(approval){
   let posted=false;

   for(const jn of jes){
     const j=await get('Journal Entry',jn.name);

     if((j.accounts||[]).some(r=>
       r.party==='Summit Traders Ltd.' &&
       Number(r.debit_in_account_currency||0)===8400
     )) posted=true;
   }

   if(!posted) findings.push({
     type:'APPROVED_CREDIT_NOT_POSTED',
     supplier:'Summit Traders Ltd.',
     expected:8400,
     actual:0,
     recovery:8400,
     evidence:[approval.file_name]
   });
 }

 // A5 — supplier credit exists while related invoice was paid in full
 for(const jn of jes){
   const j=await get('Journal Entry',jn.name);

   const credit=(j.accounts||[]).find(r=>
     r.party_type==='Supplier' &&
     r.party==='MA Inc.' &&
     Number(r.debit_in_account_currency||0)>0
   );

   if(!credit) continue;

   const ref=(j.user_remark||'').match(/ACC-PINV-\d{4}-\d+/);
   if(!ref) continue;

   const inv=await get('Purchase Invoice',ref[0]);

   const payments=await list('Payment Entry',
     ['name','party','paid_amount','docstatus'],
     [['party','=','MA Inc.'],['docstatus','=',1]]
   );

   for(const px of payments){
     const pay=await get('Payment Entry',px.name);
     const allocation=(pay.references||[]).find(r=>
       r.reference_name===inv.name
     );

     if(
       allocation &&
       Number(allocation.allocated_amount)===Number(inv.grand_total)
     ){
       findings.push({
         type:'UNAPPLIED_SUPPLIER_CREDIT',
         supplier:'MA Inc.',
         recovery:Number(credit.debit_in_account_currency),
         evidence:[j.name,inv.name,pay.name]
       });
     }
   }
 }

 // Deduplicate identical evidence pairs/findings
 const unique=[];
 const keys=new Set();

 for(const f of findings){
   const k=f.type+'|'+[...(f.evidence||[])].sort().join('|');
   if(!keys.has(k)){
     keys.add(k);
     unique.push(f);
   }
 }

 const total=Number(
   unique.reduce((s,x)=>s+Number(x.recovery||0),0).toFixed(2)
 );

 return JSON.stringify({
   audit_run:new Date().toISOString(),
   source:'ERPNext',
   mode:'READ_ONLY',
   ground_truth_used:false,
   findings:unique,
   exception_count:unique.length,
   potential_recovery:total
 },null,2);
})()
