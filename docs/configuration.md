# Configuration

Copy `.env.example` to `.env`. `src/config/settings.py` loads `.env` via
`pydantic-settings`. Never commit `.env`.

Evidence tools (`get_account_summary`, search, merchant resolution, duplicate
check, audit) need **no API keys** and make no network calls. Customer-facing
synthesis uses **Google Gemini**, so the key to add is `GEMINI_API_KEY` from
[Google AI Studio](https://aistudio.google.com/apikey). This project does not
use `OPENAI_API_KEY`.

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

# Required only for synthesize_investigation
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-2.5-pro

# Optional Opik observability
OPIK_API_KEY=your-opik-api-key
OPIK_WORKSPACE=your-opik-workspace
OPIK_PROJECT_NAME=financial-transaction-resolution
OPIK_USE_LOCAL=false
OPIK_URL_OVERRIDE=
OPIK_ENABLED=true

# Required only for --transport http
DESCOPE_CONFIG_URL=
BASE_URL=http://127.0.0.1:8000
HTTP_HOST=127.0.0.1
HTTP_PORT=8000

# How long a synthesize_investigation confirmation_token remains usable
CONFIRMATION_TTL_SECONDS=900

# Review-route identity
REVIEW_AUTH_MODE=jwt
REVIEW_REQUIRED_SCOPE=dispute:review
```

| Variable | Required to run? | Default | What it does | How to obtain |
| --- | --- | --- | --- | --- |
| `SERVER_NAME` | No | `financial-transaction-resolution` | Name advertised to MCP clients | Choose freely; not a secret |
| `SERVER_VERSION` | No | `0.1.0` | Version advertised to MCP clients | Choose freely; not a secret |
| `DATABASE_PATH` | No | `data/transactions.db` | SQLite file for the synthetic dataset | Local path; no credentials |
| `CHECKPOINT_PATH` | No | `data/checkpoints.db` | SQLite file for LangGraph HITL checkpoints so pending reviews survive restarts. Demo only; production should use PostgreSQL. | Local path; no credentials |
| `LOG_LEVEL` | No | `INFO` | Stderr log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | Choose freely |
| `GEMINI_API_KEY` | Only for `synthesize_investigation` | _(empty)_ | Google Gemini API key | Create a key at [Google AI Studio](https://aistudio.google.com/apikey) |
| `GEMINI_MODEL` | No | `gemini-2.5-pro` in `.env.example` | Gemini model id for synthesis | A Gemini model id from AI Studio; default is fine |
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
| `CONFIRMATION_TTL_SECONDS` | No | `900` | Lifetime of a synthesis `confirmation_token` | 60–86400 seconds |
| `REVIEW_AUTH_MODE` | No | `jwt` | How `/reviews/*` identifies the reviewer. `jwt` verifies signature, issuer, audience and expiry, then uses `sub`. `local-demo` allows `X-Reviewer-Id` and the HTML form — local demos only | `jwt` or `local-demo` |
| `REVIEW_REQUIRED_SCOPE` | No | `dispute:review` | Scope or role a verified reviewer JWT must include | Choose freely; grant it only to human reviewers |

Restart the MCP server in the client after editing `.env`.
