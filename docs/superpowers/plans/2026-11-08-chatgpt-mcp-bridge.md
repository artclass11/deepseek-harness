# ChatGPT DeepSeek Harness Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a secure Windows-hosted MCP bridge that lets this ChatGPT account invoke the user's local DeepSeek Harness SDK runtime.

**Architecture:** An isolated Python MCP server wraps the existing Python SDK, persists Harness sessions under a dedicated DSH_HOME, and limits task directories to one configured workspace root. A loopback-only HTTP service is exposed through a temporary Cloudflare Quick Tunnel; a private ChatGPT plugin archive is generated only after the real HTTPS endpoint exists.

**Tech Stack:** Python 3.10+, official MCP Python SDK v2, Starlette, Uvicorn, existing DeepSeek Harness Python SDK, PowerShell, cloudflared.

**Spec:** docs/superpowers/specs/2026-11-08-chatgpt-mcp-bridge-design.md

## Global Constraints

- Do not modify upstream Harness package code or package manifests.
- Use the full sdk profile and its default workspace sandbox; do not use sdk-minimal, whose policy is danger-full-access.
- Require a non-empty bearer token of at least 32 characters and never commit credentials.
- Bind the MCP HTTP server to 127.0.0.1 only.
- Permit one active task at a time.
- Reject workspace paths outside DSH_WORKSPACE_ROOT after resolving symlinks.
- Approval requests expire to rejection; never auto-approve.
- Quick Tunnel is for temporary testing, not permanent production availability.

## Review Focus

- A symlink inside the workspace points outside the approved root: reject after path resolution.
- A missing or malformed Authorization header reaches /mcp: return 401 before MCP handling.
- A task requests a workspace outside the configured root: reject without starting an agent.
- An approval or question outlives its timeout or the runtime disconnects: fail closed.
- An old or unknown session ID is supplied: require a bridge-owned session record before resume.

---

### Task 1: Bridge contracts and workspace validation

**Files:**
- Create: integrations/chatgpt-mcp/src/deepseek_harness_mcp/config.py
- Create: integrations/chatgpt-mcp/src/deepseek_harness_mcp/workspace.py
- Create: integrations/chatgpt-mcp/src/deepseek_harness_mcp/security.py
- Test: integrations/chatgpt-mcp/tests/test_workspace_security.py

**Interfaces:**
- Produces BridgeConfig.from_env(), resolve_workspace(candidate, root), validate_session_id(value), and is_valid_bearer(header, token).

- [ ] Write tests for path traversal, symlink escape, nonexistent directories, session ID grammar, bearer parsing, and missing credentials.
- [ ] Run the focused unittest module and verify the new tests fail before implementation.
- [ ] Implement the config, workspace, and security helpers with explicit environment validation and constant-time bearer comparison.
- [ ] Run the focused unittest module and verify all cases pass.

### Task 2: Persistent Harness runtime, task lifecycle, approvals, and questions

**Files:**
- Create: integrations/chatgpt-mcp/src/deepseek_harness_mcp/runtime.py
- Test: integrations/chatgpt-mcp/tests/test_runtime_contracts.py

**Interfaces:**
- HarnessRuntime.health_check() -> dict
- HarnessRuntime.start_task(task, workspace_path="") -> dict
- HarnessRuntime.resume_session(session_id, task) -> dict
- HarnessRuntime.task_status(task_id) -> dict
- HarnessRuntime.task_output(task_id) -> dict
- HarnessRuntime.list_sessions() -> list[dict]
- HarnessRuntime.set_working_directory(session_id, path) -> dict
- HarnessRuntime.pending_approvals(), decide_approval(...), pending_questions(), and answer_question(...).

- [ ] Test prompt bounds, active-task limits, approval state, rejection on expiry, exact question-answer IDs, and persisted session ownership.
- [ ] Implement the SDK wrapper with profile sdk, provider deepseek-official, approval_requests=True, and user-question callbacks.
- [ ] Persist only session ID and approved workspace metadata; leave prompts and credentials out of the registry.
- [ ] Run the focused tests and verify all state transitions and fail-closed paths.

### Task 3: Streamable HTTP MCP server and private plugin package builder

**Files:**
- Create: integrations/chatgpt-mcp/src/deepseek_harness_mcp/server.py
- Create: integrations/chatgpt-mcp/src/deepseek_harness_mcp/plugin_builder.py
- Create: integrations/chatgpt-mcp/plugin-template/plugin.json
- Create: integrations/chatgpt-mcp/plugin-template/skills/deepseek-harness/SKILL.md
- Create: integrations/chatgpt-mcp/scripts/build_plugin.py
- Test: integrations/chatgpt-mcp/tests/test_plugin_builder.py

**Interfaces:**
- create_app(config=None) creates the authenticated MCP ASGI app.
- build_plugin(endpoint, output) creates one Agent Plugins 1.0 ZIP with Streamable HTTP and bearer API-key authentication.

- [ ] Test endpoint validation and the generated manifest/ZIP contents.
- [ ] Register the narrow MCP tools and add bearer and Host middleware before enabling the Streamable HTTP route.
- [ ] Add a protected /healthz route and loopback-only Uvicorn entry point.
- [ ] Run the focused tests and inspect the ZIP manifest after packaging.

### Task 4: Windows setup, tunnel launcher, and operating guide

**Files:**
- Create: integrations/chatgpt-mcp/requirements.txt
- Create: integrations/chatgpt-mcp/.gitignore
- Create: integrations/chatgpt-mcp/pytest.ini
- Create: integrations/chatgpt-mcp/scripts/setup-windows.ps1
- Create: integrations/chatgpt-mcp/scripts/start-windows.ps1
- Create: integrations/chatgpt-mcp/README.md

- [ ] Add prerequisite checks for Node 24.9+, pnpm, Python, the built Windows SDK runtime, and cloudflared.
- [ ] Build the bundled runtime with the repository's supported build-exe-for-python-sdk script and install the local SDK packages plus MCP bridge dependencies.
- [ ] Start the MCP server on loopback, create/read a local random bearer token, launch Quick Tunnel, and display only the endpoint and local credential handling instructions.
- [ ] Document ChatGPT private plugin installation, temporary URL rotation, approval flow, troubleshooting, and teardown.
- [ ] Run Python compile checks, all focused tests, PowerShell parser checks where available, and inspect the final diff.
- [ ] Create a pull request and verify its GitHub state.

## Execution Notes

The local Windows build, cloudflared tunnel, and ChatGPT handshake require the user's PC and authenticated ChatGPT UI. The implementer must stop at a clearly documented local handoff until the user supplies the generated endpoint; do not create a plugin with a placeholder URL or claim it is connected.
