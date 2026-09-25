# CASH LEAKAGE RECOVERY AUDIT

**Company:** Givens Vale (Demo)

**AUDIT COMPLETE**

## $38,735 Potential Recovery

**5 high-confidence exceptions**

## A1 — Supplier rebate shortfall

**Supplier:** Summit Traders Ltd.

**Potential recovery:** $12,240

**Confidence:** HIGH

Q1 eligible spend reached the 6% rebate tier. Expected rebate was $36,720; only $24,480 was credited.

**Evidence**
- `Summit-Q1-2026-Rebate-Agreement.txt`
- `ACC-PINV-2026-00002`
- `ACC-PINV-2026-00005`
- `ACC-PINV-2026-00012`
- `ACC-PINV-2026-00013`
- `ACC-PINV-2026-00014`
- `ACC-PINV-2026-00015`
- `ACC-JV-2026-00001`

**Recommended action:** Request the remaining $12,240 supplier rebate credit.

## A2 — Purchase price variance

**Supplier:** MA Inc.

**Potential recovery:** $3,375

**Confidence:** HIGH

Approved PO value was $40,293. Supplier invoice value was $43,668.

**Evidence**
- `PUR-ORD-2026-00008`
- `ACC-PINV-2026-00018`

**Recommended action:** Request correction or credit for the $3,375 variance.

## A3 — Duplicate economic invoice

**Supplier:** Zuckerman Security Ltd.

**Potential recovery:** $9,750

**Confidence:** HIGH

Two submitted invoices represent the same supplier, item, quantity, rate and $9,750 economic event under different references.

**Evidence**
- `ACC-PINV-2026-00019`
- `ACC-PINV-2026-00020`

**Recommended action:** Verify duplicate status and request reversal/credit of $9,750.

## A4 — Approved credit missing from ledger

**Supplier:** Summit Traders Ltd.

**Potential recovery:** $8,400

**Confidence:** HIGH

Supplier documentation approves an $8,400 credit, but no corresponding submitted credit or journal posting was found.

**Evidence**
- `Summit-Approved-Credit-8400.txt`

**Recommended action:** Request issuance/posting of the approved $8,400 credit.

## A5 — Supplier credit not applied at settlement

**Supplier:** MA Inc.

**Potential recovery:** $4,970

**Confidence:** HIGH

A $4,970 supplier credit existed before settlement, while the related $40,404 invoice was subsequently paid in full.

**Evidence**
- `ACC-JV-2026-00002`
- `ACC-PINV-2026-00006`
- `ACC-PAY-2026-00003`

**Recommended action:** Reconcile the unapplied $4,970 supplier credit.

---

## Controls

- Money calculations are deterministic.
- Every finding requires source evidence.
- Ground-truth answer key was not used by the audit.
- No supplier-facing action occurs without human approval.

## Recovery packages

Recovery communications have been prepared as drafts only.
**0 external messages sent.**