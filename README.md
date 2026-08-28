# Financial Transaction Resolution MCP Server

![Python](https://img.shields.io/badge/python-3.14-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![MCP](https://img.shields.io/badge/MCP-FastMCP-purple.svg)

▶️ [Watch the demo video](demo/financial-transaction-resolution-demo.mp4)

> **Disclaimer.** All customers, accounts, transactions, policies and decision rules in this
> repository are fictional and synthetically generated. No employer, card-network or customer data
> was used. This project is not affiliated with or representative of any financial institution.

- [Project Overview](#project-overview) — what the server does and its use cases
- [Required Features](#required-features)
- [Custom Features](#custom-features)
- [Setup Instructions](#setup-instructions) — clone, `uv`, `.env`, generate data, run
- [Environment Variables](#environment-variables)
- [Agent observability (Opik)](#agent-observability-opik)
- [Connecting from an MCP Client](#connecting-from-an-mcp-client)

## Project Overview

This [Model Context Protocol](https://modelcontextprotocol.io) server lets an AI assistant
investigate fictional card transactions the way a support agent would. A cardholder asks “what is
this charge?” and the assistant uses read-only tools to confirm the account, locate the posting,
translate an unreadable statement descriptor into a merchant a human recognizes, and check whether
the charge is a duplicate rather than an expected repeat (a subscription or an authorization hold
that later posted).

Every evidence tool is scoped to a single account. Analysis is deterministic and rule-based, so the
same question always produces the same answer and every conclusion names the rule that produced it.
The host agent supplies judgement; the server supplies facts it cannot invent. The reusable
`investigate_transaction` prompt sequences that work, then `synthesize_investigation` calls Gemini
to draft the customer-facing reply. After that reply, a LangGraph human-in-the-loop workflow can
register a synthetic dispute case — but only if the end user explicitly approves.

This is a local demo of MCP server design, layered architecture, PII handling and deterministic
domain logic. It is not a real issuer dispute system. Registering a case writes a row to SQLite; it
does not file, approve or resolve a dispute with a card network.

### Use cases

- **Unrecognized charge.** A cardholder does not recognize a statement line such as
  `HALCYON ELEC 0417 SEATTLE WA`. Resolve the merchant, then check for a same-day duplicate.
- **Possible double billing.** Two postings share merchant, amount and date. Return a
  `LOW` / `MEDIUM` / `HIGH` duplicate confidence with rule-based reasons.
- **Expected repeats that are not duplicates.** A hotel authorization hold that later posts, or a
  monthly subscription, should be downgraded rather than treated as fraud.
- **Foreign or fee questions.** Route the concern to `policy://fees/foreign-transaction` or
  `policy://fees/late-payment` and answer from the synthetic policy plus the charge details.
- **Investigation audit.** Reuse one `request_id` across tool calls and reconstruct the trail with
  `get_audit_trace` (tool names and outcomes only; no PII).
- **Customer-facing summary.** After evidence is gathered, synthesize a reply with Gemini that
  follows the selected policy and never claims an issuer filed a dispute.
- **Human-approved dispute case.** After synthesis, `create_dispute_draft` returns a
  `PENDING_REVIEW` proposal (no approval required). A human reviewer records a decision in the
  review application, which mints a one-time `approval_id`. `submit_dispute_case` writes a
  `dispute_cases` row only after that id is verified.

## Demo

Run the server from Cursor (or another MCP client) and ask:

> Customer doesn't recognize the transaction `TXN-SCN-DUP-A` on `ACCT-0001`

That scenario is a same-day double post at Halcyon Electronics. The agent should ask for any missing
ids, read `policy://disputes/unrecognized-transaction`, gather evidence with the tools, finish
with `synthesize_investigation`, then — only if you approve — register a synthetic dispute case
through the LangGraph human-in-the-loop tools. A full tool-by-tool walkthrough is in
[Example Queries](#example-queries).

## Architecture & System Design

The server is a local FastMCP process. Cursor, Claude Desktop or the MCP Inspector can launch it
over **stdio** (local-trust, no OAuth). For a network listener, start **HTTP**; that path requires
[Descope](https://www.descope.com/) and validates bearer JWTs at the transport layer. Stdio logs
still go to stderr so stdout stays the protocol wire.

Layers are strictly separated. Dependencies point inward: the MCP layer knows about handlers,
handlers know about services and repositories, and the domain knows about nothing else.

```
        MCP client (Cursor, Claude Desktop, Inspector)
                          │  stdio  or  HTTP + Descope JWT
┌─────────────────────────▼──────────────────────────────────┐
│ src/server.py            FastMCP app, instructions, auth    │
├────────────────────────────────────────────────────────────┤
│ src/routers/             Registration only. Translates MCP  │
│   tools.py               arguments into request contracts.  │
│   prompts.py             No logic, no SQL.                  │
│   resources.py                                              │
├────────────────────────────────────────────────────────────┤
│ src/tools/               Thin handlers: validate, call a    │
│   *_tool.py              service, present the result.       │
├────────────────────────────────────────────────────────────┤
│ src/app/                 execution.py  audit + error + time │
│                          container.py  composition root     │
│                          validators.py identifier checks    │
│                          presenters.py domain → contract    │
│                          data_seed.py  synthetic generator  │
├────────────────────────────────────────────────────────────┤
│ src/contracts/           Pydantic request and response      │
│                          models; the shared envelope.       │
├────────────────────────────────────────────────────────────┤
│ src/domain/              models.py    frozen dataclasses    │
│                          criteria.py  validated queries     │
│                          services/    merchant resolution,  │
│                                       duplicate detection   │
│                          exceptions.py stable error codes   │
├────────────────────────────────────────────────────────────┤
│ src/repositories/        SQLAlchemy 2.x. Every transaction  │
│                          query is account-scoped.           │
├────────────────────────────────────────────────────────────┤
│ src/security/masking.py  │  src/audit/service.py            │
│ src/llm/gemini_client.py │  src/observability/tracing.py    │
│ src/workflows/           LangGraph HITL dispute registration  │
│ SQLite data/transactions.db  │  Opik (optional agent traces)    │
└────────────────────────────────────────────────────────────┘
```

A typical tool call travels from `src/routers/tools.py` into a handler, then through
`execute_tool` in `src/app/execution.py`. That wrapper is the only path that constructs a response:
it assigns a correlation id, times the work, translates domain errors into a stable envelope,
writes a sanitized audit event, and (when Opik is configured) records a tool span. Handlers stay
thin — validate identifiers, ask a repository or service, present the result — so auditing,
tracing and error handling cannot be forgotten by a new tool.

`Container` (`src/app/container.py`) is the composition root. Repositories and services are wired
there, and `create_mcp_server()` accepts a container so tests can inject an in-memory SQLite
database and exercise the whole stack without a live client.

Tools, prompts and resources work together as one investigation loop. The host starts from the
`investigate_transaction` prompt. If `account_id` or `transaction_id` is missing, the prompt tells
the agent to stop and ask the caller — that is the user-feedback gate. The agent then reads one
policy resource (`policy://disputes/unrecognized-transaction`, `policy://fees/foreign-transaction`,
or `policy://fees/late-payment`), calls the evidence tools, and finishes with
`synthesize_investigation`. Evidence analysis never calls a model. Gemini is used only to draft the
final customer-facing narrative from the gathered envelopes and the selected policy. If the end user
then wants a dispute case, `create_dispute_draft` starts a LangGraph graph and returns a
`PENDING_REVIEW` proposal without writing a case. A human reviewer mints a one-time `approval_id`
at `/reviews/{request_id}` after presenting a verified JWT (`sub` plus `dispute:review`);
`submit_dispute_case` accepts only `request_id` and `approval_id` and
writes `dispute_cases` only when that record is an unused, unexpired approval.

The only external API is Google Gemini (`google-genai`, default model `gemini-2.5-pro`), and only
the synthesis tool needs `GEMINI_API_KEY`. Search, merchant resolution, duplicate detection and
audit stay local against SQLite. Amounts are stored as integer minor units and exposed as `Decimal`
strings so duplicate checks are exact rather than floating-point. Every transaction query includes
`account_id` in its `WHERE` clause; a charge on another account is indistinguishable from one that
does not exist.

The design is deliberately not a concurrent network service. Stdio plus synchronous SQLite is
enough for a single local client. Scalability here means reproducible data, bounded search results
(`limit` max 100, with a `truncated` flag) and a uniform error envelope rather than horizontal
scale. Full layer notes live in [`docs/architecture.md`](docs/architecture.md).

## Project Structure

The layout follows the FastMCP course pattern: a server entry point, routers that only register
capabilities, and separate packages for tool/resource/prompt logic, application services and
configuration.

### Recommended Structure (Reference)

- `src/server.py`: Creates the `FastMCP` app and registers the routers.
- `src/routers/`: `tools.py`, `resources.py` and `prompts.py` import implementations and register
  them with FastMCP decorators.
- `src/tools/`, `src/resources/`, `src/prompts/`: Business logic for each MCP capability.
- `src/app/`: Core application logic (execution, seeding, presenters, validators).
- `src/utils/`: Logging and other helpers.
- `src/config/settings.py`: `pydantic-settings` for server name, version, database path, log level
  and Gemini configuration.

### Your Project Structure

#### Server and registration

- `src/server.py` — FastMCP instance, instructions, stdio and Descope-authenticated HTTP.
- `src/routers/tools.py` — Nine tools. Evidence tools and synthesis use `readOnlyHint`;
  `submit_dispute_case` is the only write and requires a minted `approval_id`.
- `src/routers/prompts.py` — `investigate_transaction`.
- `src/routers/resources.py` — `status://server` and three policy URIs.
- `src/routers/reviews.py` — Human review application: display a draft and mint `approval_id`.

#### MCP capabilities

- `src/tools/` — One handler per tool (`get_account_summary`, `search_transactions`,
  `get_transaction_details`, `resolve_merchant`, `check_duplicate_charge`, `get_audit_trace`,
  `synthesize_investigation`, `create_dispute_draft`, `submit_dispute_case`).
- `src/workflows/dispute_case.py` — LangGraph graph: load context, build a PENDING_REVIEW draft,
  interrupt, persist only after a verified approval record. SQLite-checkpointed so pending drafts
  survive restarts (PostgreSQL in production).
- `src/workflows/checkpointer.py` — Demo `SqliteSaver` factory. Production should use `PostgresSaver`.
- `src/prompts/investigate_transaction_prompt.py` — Agentic workflow text, including the ask-the-caller
  gate and the post-synthesis human-approval phase.
- `src/resources/` — Server status plus unrecognized-transaction, foreign-transaction-fee and
  late-payment-fee policies.

#### Domain, persistence and contracts

- `src/domain/` — Frozen models, search criteria, merchant resolver, duplicate-charge service,
  money conversion, error taxonomy.
- `src/repositories/` — SQLAlchemy tables, account-scoped queries, row mappers, session factory.
- `src/contracts/` — Pydantic request/response models and the shared `{status, request_id, data, error}`
  envelope.

#### Cross-cutting

- `src/app/container.py`, `execution.py`, `presenters.py`, `validators.py`, `data_seed.py`
- `src/security/masking.py` — Account and card masking.
- `src/security/descope.py` — Descope well-known URL parsing and `DescopeProvider` construction.
- `src/security/reviewer.py` — Review-route auth: verified JWT identity, or explicit `local-demo`.
- `src/audit/service.py` — Append-only sanitized audit events.
- `src/observability/tracing.py` — Optional Opik traces, Gemini token usage and latency, HITL graph.
- `src/llm/gemini_client.py` — The only module that calls a model.
- `src/config/settings.py` — Environment-backed settings.

#### Data, tests and docs

- `scripts/generate_data.py` — Regenerates `data/transactions.db`.
- `tests/` — Handler, isolation, data-reproducibility, protocol and synthesis tests.
- `docs/architecture.md` — Layered design, request lifecycle and security boundaries.

### Dataset Sources

All data is invented for this project. Nothing is scraped or licensed from a financial institution.

- **Name:** Synthetic card-transaction dataset
- **Source:** Generated in-repo by `src/app/data_seed.py` via `scripts/generate_data.py`
- **Storage:** `data/transactions.db` (SQLite; gitignored). Recreate with
  `uv run python scripts/generate_data.py --seed 42`. Paused LangGraph dispute threads are stored
  separately in `data/checkpoints.db` (also gitignored).
- **Format:** SQLite tables `customers`, `accounts`, `merchants`, `transactions`, `audit_events`,
  `dispute_cases`, `approval_records`
- **Preprocessing:** None. Tables are dropped and recreated on each run. Dates are anchored to a
  fixed reference date (`2026-06-30`), so the dataset does not drift.
- **License / attribution:** Original synthetic content under this repository's MIT license.
  Names, merchants and descriptors correspond to no real person or business.

Approximate volumes at seed 42: **100** customers, **150** accounts, **75** merchants, **5,000**
background transactions, **100–200** interesting transactions (`TXN-INT-*`), and **12** hand-written
scenario rows on the demo accounts.

| Scenario | Transactions |
| --- | --- |
| Exact duplicate charge | `TXN-SCN-DUP-A`, `TXN-SCN-DUP-B` on `ACCT-0001` |
| Recurring subscription | `TXN-SCN-SUB-01/02/03` |
| Descriptor ≠ display name | `TXN-SCN-DESC-01` (`SQ *RVRBND COFFEE…` → Riverbend Coffee Roasters) |
| Hotel authorization hold | `TXN-SCN-HOLD-01` (hold) and `TXN-SCN-HOLD-02` (posted) |
| Foreign transaction | `TXN-SCN-FX-01` — 64.20 EUR in France |
| Posted / pending | `TXN-SCN-POSTED-01`, `TXN-SCN-PENDING-01` |
| Same charge, other account | `TXN-SCN-OTHER-01` on `ACCT-0002` (isolation tests) |

`ACCT-0001` is the scenario account. Background generation never reuses the scenario merchants on it.

## Required Features

Course-required capabilities implemented in this server, with a brief description of each.

| Feature | Description |
| --- | --- |
| **MCP server in Python with FastMCP** | `src/server.py` creates a FastMCP app, sets instructions, enables `mask_error_details=True`, and registers tools, prompts and resources. Stdio is the default (`uv run python -m src.server`). HTTP (`--transport http`) requires Descope. |
| **MCP tools** | Nine tools in `src/tools/`, registered in `src/routers/tools.py`. Evidence tools are read-only and return `{status, request_id, data, error}`. Catalog below. |
| **MCP prompt with user feedback** | `investigate_transaction` (`src/prompts/investigate_transaction_prompt.py`). If `account_id` or `transaction_id` is missing, the agent must stop and ask the caller before any tool call. If the concern is unclear, it asks one clarifying question, then maps the concern to a policy resource. |
| **Structured tool inputs and outputs** | Pydantic v2 request/response models in `src/contracts/`. FastMCP generates JSON Schema from typed arguments. |
| **Synthetic data in SQLite** | Generated dataset in `data/transactions.db` via `scripts/generate_data.py` / `src/app/data_seed.py`. No live financial APIs. |
| **Deterministic transaction analysis** | Merchant resolution and duplicate detection in `src/domain/services/` use fixed rules only — no model calls and no randomness. |
| **Gemini synthesis of findings** | `synthesize_investigation` turns gathered tool envelopes into a customer-facing reply with Gemini (`src/llm/gemini_client.py`). Requires `GEMINI_API_KEY`. |
| **PII masking** | Account ids and card last-fours are masked in presenters (`src/security/masking.py`). Customer names are never returned. |
| **Audit logging** | Every tool call writes a sanitized event (tool name, `request_id`, masked account, outcome, duration). No arguments or payloads. |
| **Automated tests** | `tests/` covers masking, search filters, cross-account isolation, analysis rules, audit, data seed, protocol discovery and synthesis. |
| **Documentation** | This README plus [`docs/architecture.md`](docs/architecture.md). |

**Tools**

| Tool | Purpose | Key inputs |
| --- | --- | --- |
| `get_account_summary` | Account type, status, open date, masked card, holder's state. Never returns a name. | `account_id` |
| `search_transactions` | Filtered search inside one account. Rejects invalid date/amount ranges. | `account_id`, optional filters, `limit` (default 20, max 100) |
| `get_transaction_details` | One transaction, only if it belongs to the account. | `account_id`, `transaction_id` |
| `resolve_merchant` | Deterministic descriptor → merchant match with rule, score and explanation. | `raw_descriptor` |
| `check_duplicate_charge` | Rule-based duplicate check with `LOW` / `MEDIUM` / `HIGH` confidence. | `account_id`, `transaction_id` |
| `get_audit_trace` | Sanitized audit events for a correlation id. | `request_id` |
| `synthesize_investigation` | Gemini drafts a customer-facing reply from gathered envelopes. Requires `GEMINI_API_KEY`. | `account_id`, `transaction_id`, `investigation_findings` |
| `create_dispute_draft` | Builds a `PENDING_REVIEW` proposal (reason code, evidence, policy, proposed action, draft hash). Does not require approval and does not write a case. | `account_id`, `transaction_id`, `investigation_findings`, `synthesis_summary` |
| `submit_dispute_case` | Creates a synthetic dispute case after verifying a minted `approval_id`. `approved=true` is not accepted. | `request_id`, `approval_id` |

## Custom Features

Features implemented beyond the course minimum, with a brief description of each.

| Feature | Description |
| --- | --- |
| **MCP resources (status and policies)** | Read-only URIs: `status://server`, `policy://disputes/unrecognized-transaction`, `policy://fees/foreign-transaction`, `policy://fees/late-payment`. Implemented in `src/resources/` and registered in `src/routers/resources.py`. |
| **Authorization-hold awareness** | A hold followed by a posted charge at the same merchant for the same amount is treated as normal settlement. Duplicate confidence is downgraded to `LOW` with that reason (`src/domain/services/duplicate_charge.py`). |
| **Recurring-subscription awareness** | If either charge is flagged recurring, repeated amounts at that merchant are expected and confidence is downgraded instead of reported as a duplicate. |
| **Capture-channel signal** | When two same-day, same-amount charges used different channels (card present vs not), the reason string says so — often a retried payment. |
| **Payment-aggregator normalization** | Descriptors like `SQ *RVRBND COFFEE 8821 SEATTLE WA` have aggregator prefixes, store numbers and noise tokens stripped before matching (`src/domain/services/merchant_resolver.py`). |
| **Explainable match scoring** | Merchant resolution reports which rule fired (`exact_match`, `prefix_match`, `contains_match`, `token_overlap`), the pattern matched, a numeric score and a `HIGH` / `MEDIUM` / `LOW` category. |
| **Correlation ids across an investigation** | Pass one `request_id` to every tool; `get_audit_trace` reconstructs the sequence. |
| **Search `truncated` flag** | `search_transactions` reports when it hit the row limit rather than exhausted the data. |
| **Integer minor units in storage** | Amounts are stored as integer cents so duplicate equality is exact; JSON still serializes amounts as decimal strings. |
| **Escaped `LIKE` wildcards** | A `%` or `_` in `merchant_query` cannot widen the SQL search. |
| **Cross-account isolation** | Every transaction query includes `account_id` in `WHERE`. A charge on another account returns the same `TRANSACTION_NOT_FOUND` as a missing id. |
| **Opik agent observability** | Optional [Opik](https://www.comet.com/docs/opik/) tracing (`src/observability/tracing.py`). MCP tool calls become spans grouped by `request_id`; Gemini synthesis is `@track`'d for token usage and LLM call latency; the HITL LangGraph workflow is wrapped with `track_langgraph`. Payloads are sanitized (no names, descriptors or transaction bodies). |
| **LangGraph human-in-the-loop disputes** | After synthesis, `create_dispute_draft` interrupts a LangGraph graph with a `PENDING_REVIEW` proposal. The demo persists paused threads with a SQLite checkpointer (`CHECKPOINT_PATH`) so they survive process restarts; production should use PostgreSQL (`PostgresSaver`). A human reviewer records a decision at `/reviews/{request_id}` with a verified JWT (`sub` plus `dispute:review`). That mints a one-time `approval_id`. `submit_dispute_case` verifies that id before writing. An approved record inserts a `dispute_cases` row for the same `customer_id` as the account; a decline writes nothing. |
| **Descope HTTP authentication** | `--transport http` uses FastMCP's `DescopeProvider`. MCP clients register via Dynamic Client Registration and send a Descope JWT. Custom `/reviews/*` routes are not wrapped by that middleware; they verify JWTs themselves (`src/security/reviewer.py`) and require `dispute:review`. Stdio stays local-trust and does not speak OAuth. |
| **Prompt-injection hardening** | Prompt arguments are interpolated only when they match identifier patterns. Gemini fences untrusted findings, uses a server-loaded policy, and rejects host-agent hijack output. Free-text fields reject control characters. |

## Setup Instructions

Step-by-step setup: clone the repo, install with `uv`, configure `.env`, generate data, and run.

### Prerequisites

- **Python 3.14.0** (pinned in `pyproject.toml` as `requires-python = "==3.14.0"`)
- [uv](https://github.com/astral-sh/uv) for dependency management
- A [Google AI Studio](https://aistudio.google.com/apikey) API key **only if** you want
  `synthesize_investigation` (evidence tools work offline with no API keys)
- An [Opik / Comet](https://www.comet.com/signup) API key **only if** you want agent traces in the
  Opik UI (optional; the server runs without it)
- A [Descope](https://www.descope.com/sign-up) project **only if** you want HTTP (`--transport http`).
  Stdio for Cursor does not need Descope.

### 1. Clone the repository

```bash
git clone https://github.com/<your-username>/financial-transaction-resolution-mcp.git
cd financial-transaction-resolution-mcp
```

If you already have the project locally, `cd` into the project root instead.

### 2. Install dependencies using uv

```bash
uv sync
```

This creates `.venv` and installs runtime plus dev dependencies from `pyproject.toml`.

Install git hooks so Ruff linting and formatting run on every commit:

```bash
uv run pre-commit install
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in the values in [Environment Variables](#environment-variables). For a
read-only investigation without Gemini, you can leave `GEMINI_API_KEY` empty.

### 4. Generate the synthetic dataset

```bash
uv run python scripts/generate_data.py --seed 42
```

This writes `data/transactions.db`. Run it once before connecting a client; running it again
recreates the same logical dataset (seed 42) without duplicating rows.

### 5. Run the project

Attach an MCP client (recommended). Add the JSON block in
[Connecting from an MCP Client](#connecting-from-an-mcp-client) to `.cursor/mcp.json`, then restart
the MCP server in Cursor.

To start the process yourself (it waits on stdio; it will look idle until a client connects):

```bash
uv run python -m src.server
```

HTTP with Descope (refuses to start unless `DESCOPE_CONFIG_URL` is set):

```bash
uv run python -m src.server --transport http
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`. A GET to `http://127.0.0.1:8000/` returns a
status page so you can confirm the process is up. `/mcp` itself returns **401** until the client
completes Descope OAuth — that is expected, not a crash. Clients complete OAuth against Descope via
Dynamic Client Registration, then send the access token as a bearer JWT.

Optional Inspector UI (stdio, no Descope):

```bash
uv run fastmcp dev src/server.py
```

### Environment Variables

Copy `.env.example` to `.env` and set the variables below. `src/config/settings.py` loads `.env`
via `pydantic-settings`.

**Different from the course.** Many FastMCP course examples use `OPENAI_API_KEY` (OpenAI Platform).
This project does **not** use OpenAI. Customer-facing synthesis uses **Google Gemini**, so the key
to add is `GEMINI_API_KEY` from [Google AI Studio](https://aistudio.google.com/apikey). Evidence
tools (`get_account_summary`, search, merchant resolution, duplicate check, audit) need **no API
keys** and make no network calls.

```bash
# Advertised to MCP clients
SERVER_NAME=financial-transaction-resolution
SERVER_VERSION=0.1.0

# SQLite file relative to the project root (no credentials)
DATABASE_PATH=data/transactions.db

# SQLite file for LangGraph HITL checkpoints (demo). Production: PostgreSQL.
CHECKPOINT_PATH=data/checkpoints.db

# Stderr logger: DEBUG, INFO, WARNING or ERROR
LOG_LEVEL=INFO

# Required only for synthesize_investigation (not used in the course OpenAI examples)
# Get a key at: https://aistudio.google.com/apikey
GEMINI_API_KEY=your-gemini-api-key

# Gemini model for the customer-facing synthesis
GEMINI_MODEL=gemini-2.5-pro

# Optional Opik observability (not used in the course OpenAI examples)
# Sign up at https://www.comet.com/signup then copy API key + workspace from Opik settings
OPIK_API_KEY=your-opik-api-key
OPIK_WORKSPACE=your-opik-workspace
OPIK_PROJECT_NAME=financial-transaction-resolution
OPIK_USE_LOCAL=false
OPIK_URL_OVERRIDE=
OPIK_ENABLED=true

# Required only for --transport http. Create an MCP Server at
# https://app.descope.com/mcp-servers with Dynamic Client Registration enabled,
# then paste its well-known OpenID configuration URL.
DESCOPE_CONFIG_URL=
BASE_URL=http://127.0.0.1:8000
HTTP_HOST=127.0.0.1
HTTP_PORT=8000

# How long a minted dispute approval_id remains usable
APPROVAL_TTL_SECONDS=900

# Review-route identity. jwt (default) verifies bearer JWTs on GET/POST /reviews/*
# and takes reviewer_id from the token sub. local-demo allows form/header ids.
REVIEW_AUTH_MODE=jwt
REVIEW_REQUIRED_SCOPE=dispute:review
```

| Variable | Required to run? | Default | What it does | How to obtain |
| --- | --- | --- | --- | --- |
| `SERVER_NAME` | No | `financial-transaction-resolution` | Name advertised to MCP clients | Choose freely; not a secret |
| `SERVER_VERSION` | No | `0.1.0` | Version advertised to MCP clients | Choose freely; not a secret |
| `DATABASE_PATH` | No | `data/transactions.db` | SQLite file for the synthetic dataset | Local path; no credentials |
| `CHECKPOINT_PATH` | No | `data/checkpoints.db` | SQLite file for LangGraph HITL checkpoints so pending drafts survive restarts. Demo only; production should use PostgreSQL. | Local path; no credentials |
| `LOG_LEVEL` | No | `INFO` | Stderr log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | Choose freely |
| `GEMINI_API_KEY` | Only for `synthesize_investigation` | _(empty)_ | Google Gemini API key. **Not** `OPENAI_API_KEY`. | Create a key at [Google AI Studio](https://aistudio.google.com/apikey) |
| `GEMINI_MODEL` | No | `gemini-2.5-pro` | Gemini model id for synthesis | A Gemini model id from AI Studio; default is fine |
| `OPIK_API_KEY` | No | _(empty)_ | Opik Cloud API key. Enables traces, token usage and investigation threads. | Sign up at [comet.com](https://www.comet.com/signup), open Opik, copy the API key |
| `OPIK_WORKSPACE` | With Opik Cloud | _(empty)_ | Opik Cloud workspace name | From your Comet URL: `https://www.comet.com/<workspace>/...` |
| `OPIK_PROJECT_NAME` | No | `financial-transaction-resolution` | Opik project that receives traces | Choose freely |
| `OPIK_USE_LOCAL` | No | `false` | Send traces to a self-hosted Opik instead of Opik Cloud | `true` if you [run Opik locally](https://www.comet.com/docs/opik/self-host/overview) |
| `OPIK_URL_OVERRIDE` | With local Opik | _(empty)_ | Opik API URL | Default local API is typically `http://localhost:5173/api` |
| `OPIK_ENABLED` | No | `true` | Master switch. Tracing still needs `OPIK_API_KEY` or `OPIK_USE_LOCAL=true` | Set `false` to force tracing off |
| `DESCOPE_CONFIG_URL` | HTTP only | _(empty)_ | Descope MCP Server or inbound-app `.well-known/openid-configuration` URL | [Descope MCP Servers](https://app.descope.com/mcp-servers); enable DCR |
| `BASE_URL` | HTTP only | `http://127.0.0.1:8000` | Public URL advertised in OAuth protected-resource metadata | Match the URL clients use to reach this server |
| `HTTP_HOST` | HTTP only | `127.0.0.1` | Bind address for `--transport http` | Use `0.0.0.0` only if you intend to listen beyond loopback |
| `HTTP_PORT` | HTTP only | `8000` | Bind port for `--transport http` | Choose freely |
| `APPROVAL_TTL_SECONDS` | No | `900` | Lifetime of a minted dispute `approval_id` | 60–86400 seconds |
| `REVIEW_AUTH_MODE` | No | `jwt` | How `/reviews/*` identifies the reviewer. `jwt` verifies signature, issuer, audience and expiry, then uses `sub`. `local-demo` allows `X-Reviewer-Id` and the HTML form — local demos only | `jwt` or `local-demo` |
| `REVIEW_REQUIRED_SCOPE` | No | `dispute:review` | Scope or role a verified reviewer JWT must include | Choose freely; grant it only to human reviewers |

**Important:**

- Never commit `.env`. It is listed in `.gitignore`.
- Commit `.env.example` (and `.env.sample`) with placeholder values so others can set up the project.

### Agent observability (Opik)

The server can export investigation traces to [Opik](https://www.comet.com/docs/opik/) so you can
inspect LLM calls, token usage, estimated cost, and the sequence of MCP tools for one
`request_id`.

1. Create a free Comet account at [comet.com/signup](https://www.comet.com/signup) and copy the
   Opik API key and workspace, **or** [run Opik locally](https://www.comet.com/docs/opik/self-host/overview)
   and set `OPIK_USE_LOCAL=true`.
2. Put `OPIK_API_KEY` and `OPIK_WORKSPACE` in `.env` (see the table above).
3. Restart the MCP server, run an investigation, then open the Opik UI. Filter by project
   `financial-transaction-resolution` and thread id = the investigation `request_id`.

Gemini synthesis is decorated with `@track(type="llm")` and wrapped with `track_genai`, which logs
the model call, token counts, estimated cost, and LLM response time. The HITL dispute graph is
wrapped with `track_langgraph` so propose and human-resume steps appear on the same
`request_id` thread. Each MCP tool is a span. Payloads are sanitized: no customer names, statement
descriptors or transaction bodies. Tracing is off when neither `OPIK_API_KEY` nor `OPIK_USE_LOCAL`
is set, so offline evidence tools stay local.

## Running the Server

### As a Command-Line Tool

```bash
uv run python -m src.server
```

The server speaks MCP over stdio and waits for a client. All logging goes to stderr, because stdout
is the protocol wire. Running this in a terminal by itself will look idle; attach an MCP client.

HTTP with Descope (fails fast unless `DESCOPE_CONFIG_URL` is set):

```bash
uv run python -m src.server --transport http
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`. Bind address and port come from `HTTP_HOST` /
`HTTP_PORT` (or `--host` / `--port`). `BASE_URL` must match the URL clients use, including any
reverse-proxy prefix. Opening `http://127.0.0.1:8000/` in a browser should show a status page;
`/mcp` is the protocol endpoint and will 401 until OAuth succeeds. Do not use
`fastmcp run src/server.py --transport http` for this: the module-level `mcp` object is
unauthenticated for Inspector/stdio; only `python -m src.server --transport http` attaches Descope.

### Example Queries

Use these from Cursor (or another MCP client) after the server is connected. Reuse one `request_id`
across a whole investigation.

```text
# Example 1: investigate_transaction prompt (user-feedback + full loop)
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

# Example 7: after synthesis, human-approved dispute registration
The customer wants a dispute case for TXN-SCN-DUP-A on ACCT-0001 (approve the LangGraph proposal)
```

Expected highlights for the duplicate scenario:

1. `get_account_summary(account_id="ACCT-0001")` → consumer credit card, active, card `•••• 4412`, WA.
2. `get_transaction_details` / `search_transactions` → `TXN-SCN-DUP-A` and `TXN-SCN-DUP-B`, both
   89.99 USD on 2026-06-12, descriptor `HALCYON ELEC 0417 SEATTLE WA`.
3. `resolve_merchant` → Halcyon Electronics, `HIGH` confidence, `prefix_match`.
4. `check_duplicate_charge` → `duplicate_likely: true`, `HIGH`, candidate `TXN-SCN-DUP-B`.
5. `get_audit_trace` → tool names, timestamps, masked account, outcome, duration. No arguments or names.
6. After synthesis, `create_dispute_draft` → `pending_review` (no `dispute_cases` row yet).
7. If a human reviewer records an approval at `/reviews/{request_id}`, `submit_dispute_case` with
   that `approval_id` → `DSP-…` registered for the same customer as `ACCT-0001`. A declined
   approval record writes nothing. `approved=true` is not accepted.

The hotel pair (`TXN-SCN-HOLD-01` / `TXN-SCN-HOLD-02`) returns **LOW** confidence: an authorization
hold paired with a posted charge is normal settlement, not a duplicate. Monthly subscriptions are
downgraded the same way.

### Other Commands

```bash
# Generate (or regenerate) the synthetic dataset
uv run python scripts/generate_data.py --seed 42

# MCP Inspector (interactive tool/prompt explorer)
uv run fastmcp dev src/server.py

# Equivalent Inspector launch
npx @modelcontextprotocol/inspector uv run python -m src.server

# Tests and lint
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy

# Run every git hook against the whole tree
uv run pre-commit run --all-files
```

### Connecting from an MCP Client

Add the following block to the project-level MCP settings file (`.cursor/mcp.json`). The same
`mcpServers` object works for Claude Desktop's `claude_desktop_config.json`.

```json
{
  "mcpServers": {
    "financial-transaction-resolution": {
      "command": "uv",
      "args": [
        "run",
        "python",
        "-m",
        "src.server"
      ],
      "cwd": "${workspaceFolder}",
      "env": {
        "ENV_FILE_PATH": "${workspaceFolder}/.env"
      }
    }
  }
}
```

**Configuration notes:**

- Replace nothing except the server name if you want a different label in Cursor. The module path
  is `src.server`.
- This uses **relative paths** and **project-level scope**, so it is safe to commit.
- `${workspaceFolder}` resolves to the project root. `pydantic-settings` loads `.env` from that
  working directory. `ENV_FILE_PATH` is included so MCP clients that follow the course template
  pass the same file explicitly.
- Generate `data/transactions.db` before connecting. Restart the MCP server in Cursor after
  changing `.env`.
- If your client does not expand `${workspaceFolder}`, use an absolute `--directory` instead:

  ```json
  {
    "mcpServers": {
      "financial-transaction-resolution": {
        "command": "uv",
        "args": [
          "--directory",
          "/absolute/path/to/financial-transaction-resolution-mcp",
          "run",
          "python",
          "-m",
          "src.server"
        ]
      }
    }
  }
  ```

This stdio configuration assumes the local user. Any connected client can query any account in the
synthetic dataset.

### HTTP with Descope

1. Create a free Descope account and open [MCP Servers](https://app.descope.com/mcp-servers).
2. Create an MCP Server and enable **Dynamic Client Registration (DCR)**.
3. Copy the well-known URL. FastMCP 3.4 accepts either:
   - Resource-specific: `https://api.descope.com/v1/apps/agentic/P…/M…/.well-known/openid-configuration`
   - Project inbound app: `https://api.descope.com/v1/apps/P…/.well-known/openid-configuration`
4. Set `DESCOPE_CONFIG_URL` and `BASE_URL` in `.env`, then start HTTP:

```bash
uv run python -m src.server --transport http
```

5. Point an MCP client at the URL. Cursor example:

```json
{
  "mcpServers": {
    "financial-transaction-resolution": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

The client should discover Descope from protected-resource metadata, register itself (DCR), and
send a bearer JWT. Unauthenticated `/mcp` calls are rejected at the transport layer. The human
review app at `/reviews/{request_id}` is a custom route, so it verifies JWTs itself: signature,
issuer, audience, expiry, then `sub` plus a `dispute:review` scope or role. Set
`REVIEW_AUTH_MODE=local-demo` only if you need the HTML form to accept a reviewer id locally.

## Testing

```bash
uv run pytest              # full suite
uv run pytest -v           # per-test names
uv run ruff check .        # lint
uv run ruff format --check .
uv run ruff format .       # apply formatter
uv run mypy                 # strict type checking
uv run pre-commit run --all-files
```

Ruff is configured in `pyproject.toml` (`[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.format]`). After `uv run pre-commit install`, the same checks run automatically on `git commit`.

The suite covers account and card masking, every search filter, invalid date and amount ranges,
cross-account access, deterministic merchant resolution, duplicate detection across confidence
categories, audit sanitization, data reproducibility under a fixed seed, MCP tool/prompt/resource
discovery, Gemini synthesis (with an injected client), Opik observability (with an injected sink),
and an end-to-end investigation through a real FastMCP `Client`. Descope wiring is unit-tested
without contacting a live tenant: HTTP refuses to start without a well-known URL; stdio does not
require one. Review-route identity is tested with locally signed JWTs (signature, issuer, audience,
expiry, and `dispute:review`); unsigned payloads, spoofed headers, and HTML form ids are rejected
except in explicit `local-demo` mode.

## Troubleshooting

### Issue: Tools return errors or the status resource says the dataset is missing

**Solution:** Generate the database, then restart the MCP server in the client:

```bash
uv run python scripts/generate_data.py --seed 42
```

### Issue: `synthesize_investigation` returns `SYNTHESIS_UNAVAILABLE`

**Solution:** Set `GEMINI_API_KEY` in `.env` (see [Environment Variables](#environment-variables)).
Evidence tools do not need a key. Confirm the client was restarted after editing `.env`.

### Issue: `uv sync` or the server fails on Python version

**Solution:** This project pins **Python 3.14.0**. Install that interpreter and let `uv` use it
(`uv python install 3.14.0`).

### Issue: The process looks hung after `uv run python -m src.server`

**Solution:** That is expected. The server waits on stdio for an MCP client. Use Cursor, Claude
Desktop or `uv run fastmcp dev src/server.py` instead of typing JSON by hand.

### Issue: No traces appear in Opik

**Solution:** Confirm `OPIK_API_KEY` and `OPIK_WORKSPACE` are set (or `OPIK_USE_LOCAL=true` for a
local instance), `OPIK_ENABLED` is not `false`, and the MCP server was restarted after editing
`.env`. Tracing never changes tool results; failures are logged to stderr only.

### Issue: `--transport http` looks idle or `http://127.0.0.1:8000/` returned 404

**Solution:** The listener is up when the log says `Uvicorn running on http://127.0.0.1:8000`.
There is no website at `/mcp`; that path is the MCP protocol and returns **401** until Descope
OAuth completes. Restart the process after pulling the status-page change, then open
`http://127.0.0.1:8000/` (JSON/HTML status) or `http://127.0.0.1:8000/health`. Point Cursor at
`http://127.0.0.1:8000/mcp` with a URL-based MCP config, not the stdio `command` block.

### Issue: `--transport http` exits with `DESCOPE_CONFIG_URL is empty`

**Solution:** Create an MCP Server at [app.descope.com/mcp-servers](https://app.descope.com/mcp-servers)
with Dynamic Client Registration enabled. Put its `.well-known/openid-configuration` URL in `.env`
as `DESCOPE_CONFIG_URL`. Stdio (`uv run python -m src.server`) does not need this.

### Issue: The MCP client cannot start the server

**Solution:** Confirm `uv` is on the client's `PATH`, `cwd` / `--directory` points at this repo,
and you have run `uv sync`. Logging must stay on stderr; a stray print to stdout will break the
protocol session.

## Contributing

This is a course / portfolio project. If you fork it, keep the synthetic-data disclaimer intact and
do not introduce real customer or card data. Prefer small, tested changes: add a failing test, then
the fix. Install hooks with `uv run pre-commit install`, then run `uv run pytest`,
`uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy` before
opening a pull request.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
