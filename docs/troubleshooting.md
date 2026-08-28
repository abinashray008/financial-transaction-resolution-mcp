# Troubleshooting

### Tools return errors or the status resource says the dataset is missing

Generate the database, then restart the MCP server in the client:

```bash
uv run python scripts/generate_data.py --seed 42
```

### `synthesize_investigation` returns `SYNTHESIS_UNAVAILABLE`

Set `GEMINI_API_KEY` in `.env` (see [configuration.md](configuration.md)).
Evidence tools do not need a key. Confirm the client was restarted after
editing `.env`.

### `uv sync` or the server fails on Python version

This project pins **Python 3.14.0**. Install that interpreter and let `uv` use
it (`uv python install 3.14.0`).

### The process looks hung after `uv run python -m src.server`

That is expected. The server waits on stdio for an MCP client. Use Cursor,
Claude Desktop or `uv run fastmcp dev src/server.py` instead of typing JSON by
hand.

### No traces appear in Opik

Confirm `OPIK_API_KEY` and `OPIK_WORKSPACE` are set (or `OPIK_USE_LOCAL=true`
for a local instance), `OPIK_ENABLED` is not `false`, and the MCP server was
restarted after editing `.env`. Tracing never changes tool results; failures
are logged to stderr only. See [observability.md](observability.md).

### `--transport http` looks idle or `http://127.0.0.1:8000/` returned 404

The listener is up when the log says `Uvicorn running on http://127.0.0.1:8000`.
There is no website at `/mcp`; that path is the MCP protocol and returns **401**
until Descope OAuth completes. Open `http://127.0.0.1:8000/` (JSON/HTML status)
or `http://127.0.0.1:8000/health`. Point Cursor at `http://127.0.0.1:8000/mcp`
with a URL-based MCP config, not the stdio `command` block. See
[client-setup.md](client-setup.md).

### `--transport http` exits with `DESCOPE_CONFIG_URL is empty`

Create an MCP Server at [app.descope.com/mcp-servers](https://app.descope.com/mcp-servers)
with Dynamic Client Registration enabled. Put its
`.well-known/openid-configuration` URL in `.env` as `DESCOPE_CONFIG_URL`.
Stdio (`uv run python -m src.server`) does not need this.

### The MCP client cannot start the server

Confirm `uv` is on the client's `PATH`, `cwd` / `--directory` points at this
repo, and you have run `uv sync --frozen`. Logging must stay on stderr; a stray
print to stdout will break the protocol session.
