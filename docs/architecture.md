# Architecture

How the server is put together and why. For what it does, see the
[README](../README.md). Related detail: [data model](data-model.md),
[security](security.md), [investigation workflow](investigation-workflow.md),
[observability](observability.md).

> All data described here is fictional and synthetically generated. This project is not affiliated
> with or representative of any financial institution.

## Layers

Dependencies point inward. Nothing in `domain/` imports from `contracts/`, `repositories/`,
`routers/` or `app/`, so the business rules can be read and tested on their own.

| Layer | Directory | Responsibility | May depend on |
| --- | --- | --- | --- |
| Transport | `src/server.py` | Build the FastMCP app, set instructions, run stdio or Descope-authenticated HTTP. | Routers, container, config, `src/security/descope.py` |
| Registration | `src/routers/` | Declare tools, prompts, resources and the human review HTTP routes. Translate MCP arguments into request contracts. | Handlers, contracts |
| Handlers | `src/tools/` | Validate identifiers, call a service or repository, present the result. | App, contracts, domain |
| Workflows | `src/workflows/` | LangGraph HITL dispute registration (`interrupt` / `Command`) with a durable checkpointer. | Domain, repositories |
| Application | `src/app/` | Cross-cutting execution, composition root, validators, presenters, data generation. | Contracts, domain, repositories, audit, security, workflows |
| Contracts | `src/contracts/` | Pydantic request and response models and the shared envelope. | Domain enums and error codes |
| Domain | `src/domain/` | Models, validated criteria, analysis services, error taxonomy. | Nothing else in the project |
| Persistence | `src/repositories/` | SQLAlchemy tables, sessions, account-scoped queries, row mapping. | Domain |
| Cross-cutting | `src/security/`, `src/audit/`, `src/observability/`, `src/utils/`, `src/config/` | Masking, Descope HTTP auth, verified reviewer identity, audit writes, Opik traces, logging, settings. | Domain, repositories |

## Project structure

### Server and registration

- `src/server.py` — FastMCP instance, instructions, stdio and Descope-authenticated HTTP.
- `src/routers/tools.py` — Eight tools. Evidence tools and synthesis use `readOnlyHint`;
  `confirm_unrecognized_transaction` is the write and requires a server-issued `confirmation_token`.
- `src/routers/prompts.py` — `investigate_transaction`.
- `src/routers/resources.py` — `status://server` and three policy URIs.
- `src/routers/reviews.py` — Human review application: display a persisted case and record
  APPROVE/REJECT against the existing row.

### MCP capabilities

- `src/tools/` — One handler per tool (`get_account_summary`, `search_transactions`,
  `get_transaction_details`, `resolve_merchant`, `check_duplicate_charge`, `get_audit_trace`,
  `synthesize_investigation`, `confirm_unrecognized_transaction`).
- `src/workflows/dispute_case.py` — LangGraph graph: checkpoint the already-written PENDING_REVIEW
  case, interrupt for back-office review, resume after the case row is updated. SQLite-checkpointed
  so pending reviews survive restarts (PostgreSQL in production).
- `src/workflows/checkpointer.py` — Demo `SqliteSaver` factory. Production should use `PostgresSaver`.
- `src/prompts/investigate_transaction_prompt.py` — Agentic workflow text, including the ask-the-caller
  gate and the post-synthesis confirmation phase.
- `src/resources/` — Server status plus unrecognized-transaction, foreign-transaction-fee and
  late-payment-fee policies.

### Domain, persistence and contracts

- `src/domain/` — Frozen models, search criteria, merchant resolver, duplicate-charge service,
  money conversion, error taxonomy.
- `src/repositories/` — SQLAlchemy tables, account-scoped queries, row mappers, session factory.
- `src/contracts/` — Pydantic request/response models and the shared `{status, request_id, data, error}`
  envelope.

### Cross-cutting

- `src/app/container.py`, `execution.py`, `presenters.py`, `validators.py`, `data_seed.py`
- `src/security/masking.py` — Account and card masking.
- `src/security/descope.py` — Descope well-known URL parsing and `DescopeProvider` construction.
- `src/security/reviewer.py` — Review-route auth: verified JWT identity, or explicit `local-demo`.
- `src/audit/service.py` — Append-only sanitized audit events.
- `src/observability/tracing.py` — Optional Opik traces, Gemini token usage and latency, HITL graph.
- `src/llm/gemini_client.py` — The only module that calls a model.
- `src/config/settings.py` — Environment-backed settings.

### Data, tests and docs

- `scripts/generate_data.py` — Regenerates `data/transactions.db`. Dataset notes: [dataset.md](dataset.md).
- `tests/` — Handler, isolation, data-reproducibility, protocol and synthesis tests.
- `evals/` — Deterministic and live Gemini scorecards. See [evals/README.md](../evals/README.md).

Tool parameters: [tools.md](tools.md).

## Request lifecycle

A call to `search_transactions` travels like this:

1. **`src/routers/tools.py`** receives flat, typed MCP arguments. FastMCP has already validated them
   against the generated JSON Schema. The router builds a `SearchTransactionsRequest` and calls the
   handler. It contains no logic.
2. **`src/tools/search_transactions_tool.py`** defines an `operation` closure and hands it to
   `execute_tool`. The closure validates the account id, constructs a `TransactionSearchCriteria`
   (which validates the ranges), confirms the account exists, queries, and presents.
3. **`src/app/execution.py`** resolves the correlation id, starts a timer, runs the closure, catches
   what it must, records an audit event, records an Opik span (when configured), and returns the
   populated envelope.
4. **`src/repositories/transactions.py`** builds one account-scoped `SELECT`.
5. **`src/app/presenters.py`** maps domain objects to contracts, masking identifiers on the way.

```
Client → router → handler ─┬─→ validators
                           ├─→ domain criteria (range validation)
                           ├─→ repository (account-scoped SQL)
                           ├─→ domain service (deterministic analysis)
                           └─→ presenter (masking)
                    wrapped by execute_tool (correlation id, timing, errors, audit, Opik span)
```

## Why handlers are thin

Everything cross-cutting lives in `execute_tool`, so a handler is only ever "validate, fetch,
present". That has three consequences worth the indirection:

- **Auditing cannot be forgotten.** It is not a decorator a new tool might omit; it is the only path
  by which a response is constructed.
- **Error handling is uniform.** `DomainError` becomes its stable code. `SQLAlchemyError` becomes a
  generic data-store message with the real reason logged to stderr. Anything else becomes
  `INTERNAL_ERROR`. No handler repeats this, and no handler can get it wrong.
- **Audit writes cannot break a call.** `_record_audit` swallows and logs its own failures, so a
  successful investigation is never lost to an audit problem.
- **Opik tracing cannot break a call.** Missing credentials, network errors or span failures are
  logged to stderr and swallowed. Tool responses stay the same with or without observability.

## Agent observability

`src/observability/tracing.py` exports investigation traces to [Opik](https://www.comet.com/docs/opik/)
when `OPIK_API_KEY` is set (Opik Cloud) or `OPIK_USE_LOCAL=true` (self-hosted). Setup, span contents
and sanitization are in [observability.md](observability.md). Opik online binary evaluation is
planned, not implemented.

## Dependency injection

`Container` (`src/app/container.py`) is the composition root: the single place repositories and
services are constructed. `create_mcp_server()` accepts one, so tests build a container over a
temporary SQLite file and drive the whole stack — routers included — without touching the real
dataset. Handlers receive the container as their first argument rather than importing globals.
The container also opens the LangGraph SQLite checkpointer (`src/workflows/checkpointer.py`). Tests
keep a sibling `*.checkpoints.db` next to the temporary dataset so paused threads stay isolated;
the demo process uses `CHECKPOINT_PATH` (`data/checkpoints.db`). Production should pass a
`PostgresSaver` instead.

Repositories take a `sessionmaker` and open a short-lived session per call. With stdio or a single
HTTP listener plus SQLite that is simple and safe; there is no ambient session to leak between requests.

## Data model

Tables, isolation rules and integer minor-unit amounts are documented in
[data-model.md](data-model.md). The domain sees frozen dataclasses
(`src/domain/models.py`), never ORM rows. `src/repositories/mappers.py` is the
only translation point. LangGraph checkpoints live in a separate SQLite file
(`CHECKPOINT_PATH`); production should use `PostgresSaver`.

## Deterministic analysis

Both analysis services are pure: they take domain objects and return a verdict. No I/O, no clock, no
randomness, no model calls. Customer-facing narrative synthesis lives outside the domain, in
`src/llm/` and the `synthesize_investigation` tool.

**Human-in-the-loop dispute cases.** After synthesis, eligible replies include a server-issued
`confirmation_token`. `confirm_unrecognized_transaction` verifies that token, writes a
`PENDING_REVIEW` `dispute_cases` row plus an immutable evidence snapshot, then runs a LangGraph
graph (`src/workflows/dispute_case.py`) that interrupts for back-office review. Paused graph state
lives in `CHECKPOINT_PATH` so a process restart does not drop the review slot. Production should
replace this with `PostgresSaver`. An authenticated reviewer records a decision at
`GET/POST /reviews/{case_id}` using a verified JWT (`sub` plus a `dispute:review` scope) and
`ReviewDecisionRequest` (`case_id`, `expected_version`, `APPROVE`/`REJECT`, `reason_code`, optional
`note`). `reviewer_id` is never read from JSON. That path updates the existing case; nothing is
submitted to an issuer or card network. The customer's name never enters graph state or the MCP
response.

**`MerchantResolverService`** normalizes a descriptor (upper-case, strip punctuation, drop leading
aggregator prefixes such as `SQ *`, drop store numbers of three or more digits, drop noise tokens like
`INC` and `POS`), then scores it against every registered pattern and display name:

| Rule | Score | Meaning |
| --- | --- | --- |
| `exact_match` | 1.00 | Normalized descriptor equals the pattern |
| `prefix_match` | 0.92 | Descriptor starts with the pattern; the rest is location detail |
| `contains_match` | 0.85 | Pattern appears as a whole phrase inside the descriptor |
| `token_overlap` | Jaccard | Shared tokens as a fraction of the union |

Confidence is `HIGH` at 0.80, `MEDIUM` at 0.50, `LOW` at 0.25; below that nothing is reported. Ties
break on score, then pattern length, then merchant id, so the answer never depends on catalog
ordering. Every response names the rule that fired and the pattern it matched.

**`DuplicateChargeService`** receives only candidates the repository already scoped to the same
account, merchant and currency, inside the requested date and amount windows. Rules are evaluated in
order, first match wins:

| Condition | Confidence | Why |
| --- | --- | --- |
| One is an authorization hold, the other posted | `LOW` | Normal settlement, not a duplicate |
| Either is flagged recurring | `LOW` | Repeated charges are expected |
| Either is reversed | `LOW` | The pair nets out |
| Same amount, same date | `HIGH` | The classic double-post |
| Same amount, within the date tolerance | `MEDIUM` | Plausible, but the gap weakens it |
| Otherwise (inside tolerance but not equal) | `LOW` | Similar is not identical |

The overall confidence is the strongest candidate's, and `duplicate_likely` is true only at `MEDIUM`
or above. The first three rules are what keep the service from crying wolf on the hotel and
subscription scenarios.

## Security boundaries

Threat scenarios, Descope HTTP auth and reviewer JWT rules are in
[security.md](security.md). The architectural constraints are:

**Prompt injection is treated as untrusted data, not as instructions.** MCP prompt arguments are
accepted only when they match identifier patterns; anything else is dropped rather than interpolated
into the host prompt (`src/prompts/investigate_transaction_prompt.py`). Free-text tool fields reject
ASCII control characters (`src/security/prompt_injection.py`, `src/app/validators.py`). Gemini
synthesis fences caller findings behind a nonce delimiter, loads policy from this server's resources
instead of a `policy` object the caller embedded, and rejects model output that tries to hijack the
host agent (`src/llm/gemini_client.py`). Opening a case still requires a server-issued
`confirmation_token` even if a model or tool payload asks to skip confirmation: the write path
verifies that token, and a boolean `approved` flag is not accepted.

**Descope authenticates HTTP, not stdio.** `--transport http` constructs FastMCP's
`DescopeProvider` (`src/security/descope.py`) from `DESCOPE_CONFIG_URL` and `BASE_URL`. Unauthenticated
requests are rejected at the transport layer before any tool runs. Stdio and in-process tests do not
attach the provider: OAuth DCR is not a stdio protocol. HTTP refuses to bind if the well-known URL
is missing or not a Descope MCP Server / inbound-app URL.

**Reviewer identity is a verified JWT claim, not a client-supplied field.** FastMCP's Descope
middleware wraps `/mcp` only. Both `GET /reviews/{case_id}` and
`POST /reviews/{case_id}/decision` authenticate in `src/security/reviewer.py`: the bearer JWT
signature, issuer, audience and expiry are verified, identity is taken from `sub`, and a
`dispute:review` scope or role is required. `X-Reviewer-Id` and HTML form reviewer ids are accepted
only when `REVIEW_AUTH_MODE=local-demo`. Unsigned JWT payloads are never trusted.

**Account scoping is structural.** Every transaction query in `src/repositories/transactions.py`
carries `account_id` in its `WHERE` clause. There is no "fetch by id, then check ownership" path,
because that shape is one careless refactor away from a leak.

**Not-found is deliberately ambiguous.** A transaction on another account and a transaction that does
not exist return the same code and the same message. `TransactionAccountMismatchError` exists in the
taxonomy for documentation but inherits `TransactionNotFoundError`, so it cannot report a
distinguishable code even if a future contributor raises it.

**Masking happens in presenters, not handlers.** `src/app/presenters.py` is the only place domain
objects become contracts, so masking cannot be skipped by a new tool that forgets to call it.

**The audit service is constrained by its signature.** `record()` accepts a tool name, request id,
account id, outcome and duration. There is no parameter that could carry arguments, names,
descriptors or payloads, and the account id is masked before it is written. Sanitization runs before
masking, so even a malformed identifier containing free text is reduced to identifier characters and
truncated.

## Error taxonomy

| Code | Raised by | Client sees |
| --- | --- | --- |
| `INVALID_INPUT` | `src/app/validators.py`, criteria `__post_init__` | What shape was expected |
| `ACCOUNT_NOT_FOUND` | Account handlers | That the account is unknown |
| `TRANSACTION_NOT_FOUND` | Transaction handlers | That no such transaction exists **on this account** |
| `INVALID_DATE_RANGE` | `TransactionSearchCriteria` | That start is after end |
| `INVALID_AMOUNT_RANGE` | `TransactionSearchCriteria`, `DuplicateCheckCriteria` | That the range is impossible |
| `SYNTHESIS_UNAVAILABLE` | Synthesis handler | Gemini is not configured or failed |
| `DISPUTE_ALREADY_EXISTS` | Dispute workflow | A case is already registered for this charge |
| `DISPUTE_WORKFLOW_NOT_FOUND` | Dispute workflow | No paused review for this `case_id` |
| `DISPUTE_NOT_AWAITING_REVIEW` | Dispute workflow | The graph is not waiting on a human decision |
| `DISPUTE_CASE_NOT_FOUND` | Review application | No case exists for this `case_id` |
| `DISPUTE_CASE_VERSION_CONFLICT` | Review application | `expected_version` does not match the stored case |
| `DISPUTE_REVIEW_ALREADY_RECORDED` | Review application | The case is no longer `PENDING_REVIEW` |
| `CONFIRMATION_NOT_FOUND` | Confirmation service | No challenge matches this `confirmation_token` |
| `CONFIRMATION_EXPIRED` | Confirmation service | The token is past `expires_at` |
| `CONFIRMATION_ALREADY_USED` | Confirmation service | The one-time token was already used |
| `CONFIRMATION_MISMATCH` | Confirmation service | The token was issued for a different investigation subject |
| `INTERNAL_ERROR` | `execute_tool` fallbacks | A generic message; detail goes to stderr |

FastMCP is additionally configured with `mask_error_details=True`, so an exception escaping the
envelope still cannot carry internals to a client.

## Testing strategy

| Level | What it covers |
| --- | --- |
| Unit | Masking, money conversion, descriptor normalization, duplicate rules the seed data cannot produce |
| Handler | Every tool against a seeded temporary database, including all error codes |
| Isolation | Cross-account access from both directions, plus indistinguishability of foreign and missing ids |
| Prompt injection | Identifier interpolation, Gemini fencing, forged policy documents, control characters in free text |
| Data | Determinism under a fixed seed, idempotent regeneration, no date drift |
| Protocol | Tool, prompt and resource discovery, annotations, schemas, a full investigation, HITL dispute registration through a real `Client`, checkpoint survival across a container rebuild, Descope HTTP wiring without a live tenant, and review-route JWT identity (signature, issuer, audience, expiry, `dispute:review`) |

Tests never reach for module-level globals; they build a `Container` and inject it, which is the same
seam `create_mcp_server()` uses.

## Logging

All logging goes to stderr (`src/utils/logging.py`). Under stdio, stdout is the protocol wire, and a
single stray log line there corrupts the session.
