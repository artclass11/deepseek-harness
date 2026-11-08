# ChatGPT DeepSeek Harness Bridge — Design

## Intent

Make the user's existing DeepSeek Harness runtime callable from this ChatGPT account through a private remote MCP plugin, while keeping model execution and project files on the user's Windows PC.

## Goals

- Reuse the repository's supported Python SDK and full sdk runtime profile.
- Expose a narrow Streamable HTTP MCP interface for starting tasks, checking results, resuming owned sessions, changing session directories, and reviewing pending approvals or user questions.
- Bind the runtime to one configured workspace root and validate every requested directory after resolving symlinks.
- Require a bearer token for every HTTP route; bind Uvicorn to loopback only; use Cloudflare Quick Tunnel for temporary HTTPS reachability.
- Keep upstream Harness packages untouched and isolate the integration under integrations/chatgpt-mcp.
- Provide a reproducible Windows build/start path, tests, and a plugin archive builder that accepts the live HTTPS endpoint after tunnel startup.

## Non-goals

- No hosted DeepSeek runtime, permanent public domain, or unattended always-on service.
- No arbitrary filesystem or process MCP tools outside the Harness agent's existing sandbox and permission policy.
- No automatic approval of Harness operations. Pending approvals and user questions must be returned to ChatGPT and explicitly decided.
- No public plugin-directory submission.

## Architecture

The bridge is a separate Python process using the official MCP Python SDK Streamable HTTP transport. It owns one DeepSeekHarness SDK instance in the full sdk profile, one active task at a time, an approval-request reader, task status, and a small session-to-workspace index. Harness history remains in the explicitly configured DSH_HOME. Cloudflare Quick Tunnel forwards HTTPS requests to the loopback MCP server; it does not host the Harness runtime.

HTTP uses a random bearer token, a Host allowlist, loopback binding, bounded tool inputs, a configured workspace root, and symlink-aware path resolution. The upstream SDK retains its default sandboxed workspace-write policy and risky-operation approval flow.

## Operating assumptions

- Windows x64 PC, Node.js 24.9 or newer, Corepack/pnpm 11.28.5, Python 3.10 or newer, and cloudflared installed locally.
- The repository checkout is on the integration branch.
- The user supplies DEEPSEEK_API_KEY locally in the start terminal; it is never stored in the repository or sent to ChatGPT.
- Quick Tunnel URLs are temporary and change when the tunnel process restarts. A new private plugin release is required when the URL changes.

## Security boundaries

- MCP bearer credentials are stored in an ignored local secrets directory and never printed by the bridge.
- The server binds only to 127.0.0.1. Cloudflare is the sole external ingress.
- The server validates bearer authorization before MCP dispatch and validates Host values.
- Workspace paths must resolve to an existing directory beneath DSH_WORKSPACE_ROOT.
- Tool prompts, retrieved files, and agent output are untrusted data. They cannot authorize approvals.
- Approval requests default to rejection on expiry or disconnect. ChatGPT may grant one operation only after the user explicitly asks.
- The integration does not expose generic shell, arbitrary file, environment, secret, or arbitrary URL tools.

## Acceptance criteria

- Focused tests cover bearer parsing, workspace traversal and symlink escape, task input bounds, approval expiry/rejection, and exact answer-question IDs.
- Windows scripts verify prerequisites, build the repository's supported Python runtime executable, install the bridge and SDK, start the loopback MCP server, and launch Quick Tunnel.
- The private plugin archive builder validates HTTPS /mcp endpoints and configures bearer API-key authentication.
- The live tunnel URL and authenticated ChatGPT handshake are verified after the user runs the Windows start script; they cannot be claimed before that local step.
