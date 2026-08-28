# MCP client setup

Stdio is the local-trust path used by the demo. HTTP requires Descope and is
documented below.

Generate `data/transactions.db` before connecting any client, and restart the
client's MCP server after changing `.env`.

## Cursor (stdio)

Project-level `.cursor/mcp.json` (committed in this repo):

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

- Replace nothing except the server name if you want a different label.
- `${workspaceFolder}` resolves to the project root. `pydantic-settings` loads
  `.env` from that working directory.
- If the client does not expand `${workspaceFolder}`, use an absolute
  `--directory`:

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

Stdio assumes the local user. Any connected client can query any account in the
synthetic dataset.

## Claude Desktop (stdio)

The same `mcpServers` object works in Claude Desktop's
`claude_desktop_config.json`. Use an absolute `--directory` if the client does
not expand `${workspaceFolder}`.

## MCP Inspector (stdio)

Inspector does not need Descope:

```bash
uv run fastmcp dev src/server.py
```

Equivalent launch:

```bash
npx @modelcontextprotocol/inspector uv run python -m src.server
```

The server waits on stdio. Running `uv run python -m src.server` in a terminal
by itself looks idle until a client connects. Logging stays on stderr; a stray
print to stdout breaks the protocol session.

## HTTP with Descope

1. Create a free Descope account and open [MCP Servers](https://app.descope.com/mcp-servers).
2. Create an MCP Server and enable **Dynamic Client Registration (DCR)**.
3. Copy the well-known URL. FastMCP 3.4 accepts either:
   - Resource-specific: `https://api.descope.com/v1/apps/agentic/P…/M…/.well-known/openid-configuration`
   - Project inbound app: `https://api.descope.com/v1/apps/P…/.well-known/openid-configuration`
4. Set `DESCOPE_CONFIG_URL` and `BASE_URL` in `.env`.
5. Start HTTP:

```bash
uv run python -m src.server --transport http
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`. Bind address and port come
from `HTTP_HOST` / `HTTP_PORT` (or `--host` / `--port`). `BASE_URL` must match
the URL clients use, including any reverse-proxy prefix.

A GET to `http://127.0.0.1:8000/` returns a status page. `/mcp` itself returns
**401** until the client completes Descope OAuth — that is expected, not a
crash.

Do not use `fastmcp run src/server.py --transport http` for this: the
module-level `mcp` object is unauthenticated for Inspector/stdio; only
`python -m src.server --transport http` attaches Descope.

Cursor HTTP example:

```json
{
  "mcpServers": {
    "financial-transaction-resolution": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

The client should discover Descope from protected-resource metadata, register
itself (DCR), and send a bearer JWT.

### Review application

The human review app at `/reviews/{case_id}` is a custom route, so it verifies
JWTs itself: signature, issuer, audience, expiry, then `sub` plus a
`dispute:review` scope or role. Set `REVIEW_AUTH_MODE=local-demo` only if you
need the HTML form to accept a reviewer id locally.

Auth design and threat notes are in [security.md](security.md). Environment
variables are in [configuration.md](configuration.md).
