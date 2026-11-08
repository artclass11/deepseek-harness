# DeepSeek Harness MCP bridge for ChatGPT

This integration lets ChatGPT call a private MCP server that runs on your Windows PC. The bridge starts the repository's supported Python SDK runtime in the full sdk profile, keeps session history in a dedicated DSH_HOME, and exposes only task/session/approval operations over authenticated Streamable HTTP.

## Prerequisites

- Windows x64.
- Node.js 24.9 or newer and Corepack-enabled pnpm 11.28.5.
- Python 3.11 or newer (required by MCP SDK v2).
- Git and a checkout of this repository on the integration branch.
- cloudflared installed locally.
- A DeepSeek API key. Enter it only in the local PowerShell prompt.

## Get the integration branch

In an existing clone of your fork, fetch and switch to the bridge branch:

    git fetch origin feat/chatgpt-mcp-bridge
    git switch feat/chatgpt-mcp-bridge

Run the remaining commands from the repository root on this branch.

## Build and install

Open PowerShell at the repository root and run:

    Set-ExecutionPolicy -Scope Process Bypass
    .\integrations\chatgpt-mcp\scripts\setup-windows.ps1

The script installs the repository's locked Node dependencies, builds the Windows SDK runtime executable using the repository's build-exe-for-python-sdk script, creates a dedicated Python virtual environment, and installs the local SDK and bridge dependencies. It does not install a cloud service or upload your project files.

## Start the local runtime and temporary tunnel

Run:

    .\integrations\chatgpt-mcp\scripts\start-windows.ps1

The script prompts for DEEPSEEK_API_KEY if the current PowerShell process does not already have it. The key is inherited by the local Harness subprocess and is not written to Git or the bridge session index.

On first start, a random bearer token is created under `%LOCALAPPDATA%\DeepSeekHarness\ChatGPTBridge\secrets`; Harness history and runtime state are kept in the same external state directory. These files are deliberately outside the workspace so the local agent cannot read its own bridge credential. The server binds to 127.0.0.1 only. The script starts cloudflared and prints an HTTPS MCP URL that ends in /mcp. Keep this PowerShell window open while using the ChatGPT plugin. Ctrl+C stops the tunnel and local server.

The quick tunnel uses a temporary trycloudflare.com address. It does not require a Cloudflare account or custom domain, but the address changes when the tunnel restarts. For a lasting endpoint, configure a named Cloudflare Tunnel and a domain you control.

## Connect ChatGPT

After the start script prints the live MCP URL, use the private plugin creator workflow in this ChatGPT conversation. Give ChatGPT only the HTTPS endpoint, for example https://example.trycloudflare.com/mcp. Do not send the bearer token or DEEPSEEK_API_KEY in chat.

The generated private plugin requests bearer API-key authentication. When ChatGPT presents the secure connection prompt, enter the local token from %LOCALAPPDATA%\DeepSeekHarness\ChatGPTBridge\secrets\mcp-bearer-token.txt. Do not paste the token into an ordinary chat message. After connecting, ask ChatGPT to call health_check and verify the returned local runtime and workspace.

## Available tools

- health_check — initialize the local SDK and verify its configured model route.
- start_task, task_status, get_task_output — run and inspect a task asynchronously.
- list_sessions, resume_session — discover and continue bridge-owned persisted sessions.
- set_working_directory — select another existing directory within the configured root.
- pending_approvals, decide_approval — view and decide individual one-time Harness approvals.
- pending_questions, answer_question — answer native Harness user questions.

Only one task may be active at a time. Task records are in memory and disappear when the bridge restarts; Harness session history remains under the dedicated DSH_HOME. Unanswered approvals and questions expire to rejection/cancellation.

## Workspace and safety

The workspace root defaults to the repository checkout. Set `$env:DSH_WORKSPACE_ROOT` before running the launcher to choose a narrower existing project directory. The launcher refuses a workspace that contains the bridge's local application-data state. All selected directories must resolve beneath this root, including symlink targets. The Harness sdk profile supplies the repository's default Windows sandboxed workspace-write policy and risky-operation approval flow. Do not point the workspace root at your whole user profile, drive root, Downloads folder, or a directory containing unrelated secrets.

The bridge does not expose raw shell or filesystem MCP tools. Agent shell and file operations remain inside the Harness runtime and its own permission controls. User authorization is required for every one-time approval; retrieved project instructions are never approval.

## Updating the tunnel URL

A Quick Tunnel URL is temporary. When it changes, rerun the private plugin packaging and update/recreate the ChatGPT plugin with the new endpoint. The bearer token remains under `%LOCALAPPDATA%\DeepSeekHarness\ChatGPTBridge\secrets` unless you delete the local secret file and generate a new one.

## Troubleshooting

- If the SDK build fails, inspect the first failing command in the setup terminal; use docs/development.md and the Python SDK runtime README.
- If the local health route fails, inspect %LOCALAPPDATA%\DeepSeekHarness\ChatGPTBridge\logs\server.err.log.
- If the tunnel does not print a trycloudflare.com address, check cloudflared installation and the cloudflared.out.log / cloudflared.err.log files in that same logs directory.
- If ChatGPT receives 401, re-enter the bearer token in the plugin's secure connection prompt. Never put it in mcp.json.
- If ChatGPT cannot connect after a restart, the Quick Tunnel address has rotated; reconnect using the new URL.

## Plugin archive

The current live URL must be known before packaging the private plugin. The archive builder validates the HTTPS /mcp endpoint and emits the Agent Plugins 1.0 manifest plus Streamable HTTP bearer authentication:

    .\integrations\chatgpt-mcp\.venv\Scripts\python.exe .\integrations\chatgpt-mcp\scripts\build_plugin.py --endpoint https://example.trycloudflare.com/mcp --output .\integrations\chatgpt-mcp\deepseek-harness-chatgpt-plugin.zip
