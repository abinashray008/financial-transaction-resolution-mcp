# Data model

SQLAlchemy tables live in `src/repositories/models.py`. The domain sees frozen
dataclasses (`src/domain/models.py`), never ORM rows.
`src/repositories/mappers.py` is the only translation point.

> Customer names exist in storage so the generator can be realistic. No tool
> returns them.

| Table | Purpose | Notes |
| --- | --- | --- |
| `customers` | Fictional account holders | `first_name`, `last_name`, `state`. Names exist but no tool returns them. |
| `accounts` | Card accounts | `card_last_four` only; no PAN exists anywhere. |
| `merchants` | Merchant catalog | `descriptor_patterns` is a JSON array of billing fragments. |
| `transactions` | Card transactions | `amount_minor` is integer cents. Always queried with `account_id`. |
| `audit_events` | Sanitized tool invocations | Tool name, `request_id`, masked account, outcome, duration. No arguments or payloads. |
| `confirmation_challenges` | One-time customer confirmation tokens | Only the token digest is stored; bound to investigation, account and transaction. |
| `dispute_cases` | Internal synthetic case files | Written at `PENDING_REVIEW` on customer confirmation, then updated in place. Unique on `(account_id, transaction_id)` and on `idempotency_key`. Optimistic `version` for review. |
| `dispute_evidence_snapshots` | Immutable evidence copy | Written in the same transaction as the case; never updated. |
| `dispute_lifecycle_events` | Semantic case lifecycle audit | Distinct from tool telemetry; includes actor type, status transition and hashes. |

LangGraph HITL checkpoints live in a **separate** SQLite file
(`CHECKPOINT_PATH`, default `data/checkpoints.db`), not in these SQLAlchemy
tables. That is the demo checkpointer (`SqliteSaver`). A production deployment
should use PostgreSQL (`PostgresSaver`).

## Amounts

SQLite has no exact decimal type, and duplicate detection turns on exact amount
equality, so storage uses integer minor units and `src/domain/money.py`
converts at the boundary. `Decimal` is the only representation above the
repository layer, and it serializes to JSON as a string.

## Isolation

Every transaction query in `src/repositories/transactions.py` carries
`account_id` in its `WHERE` clause. A transaction on another account and a
transaction that does not exist return the same `TRANSACTION_NOT_FOUND` code
and message.
