# Agent guidance

This repo is a FastMCP server. Cursor can keep a stale MCP catalog (server
instructions, tool descriptions, prompt text) after reconnect. Resource bodies
are live. Prefer the live server over any cached snapshot.

## Always read live MCP resources

At the start of a session, after an MCP reconnect, and before any investigation:

1. Read the matching policy from the MCP server. Do not rely on cached
   instructions or tool descriptions.
2. Apply that JSON: `version`, `post_synthesis`, `required_investigation_steps`,
   `outcomes`, and `prohibited_actions`.
3. If catalog text disagrees with the live policy, follow the live policy.

| Concern | Policy URI |
| --- | --- |
| Unrecognized / unfamiliar charge | `policy://disputes/unrecognized-transaction` |
| Foreign / international fee | `policy://fees/foreign-transaction` |
| Late payment fee | `policy://fees/late-payment` |

Freshness check for the unrecognized policy: `version` is `1.2` and
`post_synthesis.likely_duplicate` requires asking whether the customer already
contacted the merchant. If that block is missing, the catalog is stale — read
the resource again, do not use the cached confirmation rules.

## After MCP restart

Reconnect does not refresh Cursor's catalog cache. To force a new snapshot:

1. Start a new agent chat, or fully quit Cursor (not only toggle MCP).
2. If it is still stale, delete
   `~/.cursor/projects/Users-asray-Desktop-Code-financial-transaction-resolution-mcp/mcps/project-0-financial-transaction-resolution-mcp-financial-transaction-resolution`
   and reconnect.

## Investigation

Follow `docs/investigation-workflow.md` and the live policy. Dataset, policies,
and cases are synthetic. Do not invent identifiers, confirmation tokens, or
issuer decisions.
