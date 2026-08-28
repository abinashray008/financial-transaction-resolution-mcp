# Observability

The server can export investigation traces to [Opik](https://www.comet.com/docs/opik/)
so you can inspect LLM calls, token usage, estimated cost, and the sequence of
MCP tools for one `request_id`.

Tracing is optional. Evidence tools and synthesis work without it. When neither
`OPIK_API_KEY` nor `OPIK_USE_LOCAL` is set, every tracing method is a no-op.
Missing credentials, network errors or span failures are logged to stderr and
swallowed so a successful investigation is never lost to an observability
problem.

## Setup

1. Create a free Comet account at [comet.com/signup](https://www.comet.com/signup)
   and copy the Opik API key and workspace, **or**
   [run Opik locally](https://www.comet.com/docs/opik/self-host/overview) and set
   `OPIK_USE_LOCAL=true`.
2. Put `OPIK_API_KEY` and `OPIK_WORKSPACE` in `.env` (see
   [configuration.md](configuration.md)).
3. Restart the MCP server, run an investigation, then open the Opik UI. Filter
   by project `financial-transaction-resolution` and thread id = the
   investigation `request_id`.

## What is traced

Implementation: `src/observability/tracing.py`.

- Each MCP tool call becomes a span tagged with the investigation `request_id`
  as `thread_id`, so a full `investigate_transaction` loop is one thread.
- Gemini synthesis is decorated with `@track(type="llm")` and wrapped with
  `track_genai`, which records token counts, estimated cost and LLM response
  time (`llm_duration_ms`).
- The HITL dispute graph is wrapped with `track_langgraph` so propose and
  human-resume steps appear on the same thread.

## Sanitization

Span payloads include tool name, request id, masked account id, outcome,
duration and token counts — never customer names, statement descriptors or
transaction bodies. Narrative fields are dropped before they leave the process.

## Online evaluation

Opik **online binary evaluation** for grounded customer responses is
**planned**, not implemented. Offline evals (deterministic fake client and
opt-in live Gemini) live in [`evals/`](../evals/README.md).
