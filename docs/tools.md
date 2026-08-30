# Tool catalog

Eight tools are registered in `src/routers/tools.py`. Evidence tools and
synthesis use `readOnlyHint`. `confirm_unrecognized_transaction` is the write
and requires a server-issued `confirmation_token`.

Every successful or failed call returns the shared envelope
`{status, request_id, data, error}`. Pass `request_id` to `get_audit_trace` to
see what ran.

| Tool | Purpose | Key inputs |
| --- | --- | --- |
| `get_account_summary` | Account type, status, open date, masked card, holder's state. Never returns a name. | `account_id` |
| `search_transactions` | Filtered search inside one account. Rejects invalid date/amount ranges. | `account_id`, optional filters, `limit` (default 20, max 100) |
| `get_transaction_details` | One transaction, only if it belongs to the account. | `account_id`, `transaction_id` |
| `resolve_merchant` | Deterministic descriptor → merchant match with rule, score and explanation. | `raw_descriptor` |
| `check_duplicate_charge` | Rule-based duplicate check with `LOW` / `MEDIUM` / `HIGH` confidence. | `account_id`, `transaction_id` |
| `get_audit_trace` | Sanitized audit events for a correlation id. | `request_id` |
| `synthesize_investigation` | Gemini drafts a customer-facing reply from gathered envelopes. Eligible replies include a one-time `confirmation_token`. Requires `GEMINI_API_KEY`. | `account_id`, `transaction_id`, `investigation_findings` |
| `confirm_unrecognized_transaction` | After explicit customer confirmation, verifies the server-issued token and writes a `PENDING_REVIEW` case. Returns `case_id` and a 10-business-day message. | `investigation_id`, `account_id`, `transaction_id`, `confirmation_token`, `idempotency_key` |

## Resources

| URI | Purpose |
| --- | --- |
| `status://server` | Whether the synthetic dataset is loaded, plus non-identifying row counts |
| `policy://disputes/unrecognized-transaction` | Synthetic dispute policy for unrecognized charges |
| `policy://fees/foreign-transaction` | Synthetic foreign-transaction fee policy |
| `policy://fees/late-payment` | Synthetic late-payment fee policy |

## Prompt

`investigate_transaction` takes optional `account_id` and `transaction_id`. If
either is missing, the generated prompt tells the agent to stop and ask the
caller. Full phase text is in
[investigation-workflow.md](investigation-workflow.md).

## Parameter notes

### `search_transactions`

Optional filters: `start_date`, `end_date`, `merchant_query`, `minimum_amount`,
`maximum_amount`, `status`. `limit` is 1–100 (default 20). A `%` or `_` in
`merchant_query` is escaped so it cannot widen the SQL `LIKE`. The response
includes a `truncated` flag when the row limit was hit.

### `check_duplicate_charge`

- `date_tolerance_days`: 0–30, default 3
- `amount_tolerance`: non-negative decimal, default `0` (exact amount)

Authorization holds that later post, and recurring subscriptions, are
downgraded to `LOW` rather than reported as duplicates.

### `synthesize_investigation`

`investigation_findings` is a JSON object collecting earlier tool envelopes.
The server loads policy from its own resources rather than trusting a `policy`
object the caller embedded. When the charge is eligible, `data.confirmation`
includes `confirmation_token`. This tool does not file disputes or change
account data.

### `confirm_unrecognized_transaction`

Extra fields are forbidden. The only proof accepted is the server-issued
`confirmation_token`, and only after the policy's post_synthesis customer answer.
Repeating the same `idempotency_key` returns the same case. `approved=true` is
not a parameter and is not accepted.

Typed request and response models live in `src/contracts/`.
