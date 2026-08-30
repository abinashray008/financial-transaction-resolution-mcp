# Demo guide

Use these from Cursor (or another MCP client) after the server is connected.
Reuse one `request_id` across a whole investigation. Scenario ids are from the
seed-42 dataset; see [dataset.md](dataset.md).

The recorded demo walks the live unrecognized-charge loop for `TXN-INT-0002` on
`ACCT-0133` (Lumen Streaming $21.35, likely duplicate `TXN-INT-0001`, merchant
contact, then case `DSP-D8CF82D7`). The seeded Halcyon pair below is the same
policy path with fixed ids.

```text
# Example 1: investigate_transaction prompt (user-feedback + full loop)
Investigate TXN-INT-0002 on Acct-0133
# or the seeded pair:
Customer doesn't recognize TXN-SCN-DUP-A on ACCT-0001

# Example 2: get_account_summary
Summarize account ACCT-0001

# Example 3: search_transactions
Search ACCT-0001 for charges of exactly 89.99

# Example 4: resolve_merchant
What merchant is "HALCYON ELEC 0417 SEATTLE WA"?

# Example 5: check_duplicate_charge
Is TXN-SCN-DUP-A on ACCT-0001 a duplicate?

# Example 6: contrast — expected repeat, not a duplicate
Check TXN-SCN-HOLD-02 on ACCT-0001 (hotel hold vs posted settlement)

# Example 7: after synthesis, customer already contacted the merchant
The customer does not recognize TXN-SCN-DUP-A on ACCT-0001 and already contacted the merchant
```

## Expected highlights for the duplicate scenario

1. `get_account_summary(account_id="ACCT-0001")` → consumer credit card, active,
   card `•••• 4412`, WA.
2. `get_transaction_details` / `search_transactions` → `TXN-SCN-DUP-A` and
   `TXN-SCN-DUP-B`, both 89.99 USD on 2026-06-12, descriptor
   `HALCYON ELEC 0417 SEATTLE WA`.
3. `resolve_merchant` → Halcyon Electronics, `HIGH` confidence, `prefix_match`.
4. `check_duplicate_charge` → `duplicate_likely: true`, `HIGH`, candidate
   `TXN-SCN-DUP-B`.
5. `get_audit_trace` → tool names, timestamps, masked account, outcome,
   duration. No arguments or names.
6. After synthesis, show the reply. This scenario is a likely duplicate, so ask
   whether they already contacted the merchant. If they say yes and `confirmation`
   is present, `confirm_unrecognized_transaction` → `PENDING_REVIEW` with a `DSP-…`
   `case_id` and “We will investigate the case and get back in 10 business days.”
7. An authenticated reviewer records APPROVE or REJECT at `/reviews/{case_id}`
   with `expected_version`. That updates the existing case. `approved=true` is
   not accepted.

The hotel pair (`TXN-SCN-HOLD-01` / `TXN-SCN-HOLD-02`) returns **LOW**
confidence: an authorization hold paired with a posted charge is normal
settlement, not a duplicate. Monthly subscriptions (`TXN-SCN-SUB-*`) are
downgraded the same way.

## Other useful probes

- Foreign fee question: route to `policy://fees/foreign-transaction` and inspect
  `TXN-SCN-FX-01`.
- Isolation: `TXN-SCN-OTHER-01` belongs to `ACCT-0002`. Asking for it on
  `ACCT-0001` should look the same as a missing id.
- Aggregator descriptor: `TXN-SCN-DESC-01` resolves `SQ *RVRBND COFFEE…` to
  Riverbend Coffee Roasters.
