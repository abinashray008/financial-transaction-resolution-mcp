# Production readiness

This repository is a local reference implementation. It is not a production
issuer dispute system. Registering a case writes a row to SQLite; it does not
file, approve or resolve a dispute with a card network.

A production deployment would need at least the following.

## Persistence

- Replace SQLite (`data/transactions.db`) with PostgreSQL (or another durable
  store) and run migrations rather than dropping tables on seed.
- Replace the demo LangGraph `SqliteSaver` (`CHECKPOINT_PATH`) with
  `PostgresSaver` from `langgraph-checkpoint-postgres` so paused reviews can be
  shared across processes.
- Keep amounts as integer minor units (or `NUMERIC`) so duplicate equality stays
  exact.

## Secrets and configuration

- Manage `GEMINI_API_KEY`, Descope credentials and Opik keys in a secret
  manager, not a committed `.env`.
- Pin `BASE_URL` to the public HTTPS origin clients actually use.
- Keep `REVIEW_AUTH_MODE=jwt`. Do not enable `local-demo` outside a laptop.

## Reliability

- Add bounded retries and circuit breakers around Gemini and Opik. Synthesis
  already retries a small number of Gemini failures; a production client should
  also isolate latency and quota errors.
- Run HTTP behind TLS termination. Bind to loopback or a private network; do
  not expose `--transport http` on `0.0.0.0` without an authenticating proxy.
- Cap search results (already `limit` max 100 with a `truncated` flag) and keep
  the uniform error envelope.

## Authorization and workflow

- Integrate case creation with an authorized dispute-processing system. This
  repo's `PENDING_REVIEW` row is an internal synthetic case file, not a network
  filing.
- Keep Gemini outside the authorization boundary: model output must not be able
  to approve, submit, refund or change workflow state.
- Preserve account-scoped queries, confirmation-token expiry and replay
  protection, and verified reviewer JWTs (`sub` plus `dispute:review`).

## Observability

- Retain sanitized audit events and Opik traces. Do not log descriptors, names
  or transaction bodies.
- Online binary evaluation of grounded customer responses is planned; do not
  treat the current offline eval suite as a production model-quality gate by
  itself.

## What this demo already does

Layered architecture, deterministic analysis, PII masking, prompt-injection
hardening, typed contracts, HITL review and a reproducible synthetic dataset
are in place so those production choices have somewhere to land. See
[architecture.md](architecture.md) and [security.md](security.md).
