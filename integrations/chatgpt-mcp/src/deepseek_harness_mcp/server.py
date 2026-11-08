from __future__ import annotations

import atexit
import logging
import os
from typing import Any

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import BridgeConfig
from .runtime import HarnessRuntime
from .security import is_valid_bearer

_LOG = logging.getLogger("deepseek_harness_mcp")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if not is_valid_bearer(request.headers.get("authorization"), self._token):
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)


def create_app(config: BridgeConfig | None = None) -> Any:
    """Create a bearer-authenticated Streamable HTTP MCP application."""
    selected = config or BridgeConfig.from_env()
    runtime = HarnessRuntime(selected)
    mcp = MCPServer("DeepSeek Harness")

    @mcp.tool(title="Check local Harness health")
    def health_check() -> dict[str, Any]:
        """Start and verify the local DeepSeek Harness runtime and report its configured workspace."""
        return runtime.health_check()

    @mcp.tool(title="Start a local coding task")
    def start_task(task: str, workspace_path: str = "") -> dict[str, Any]:
        """Start one asynchronous coding task in the configured workspace root; returns task and session IDs."""
        return runtime.start_task(task, workspace_path)

    @mcp.tool(title="Check task status")
    def task_status(task_id: str) -> dict[str, Any]:
        """Return the current status of a bridge task without exposing raw tool arguments."""
        return runtime.task_status(task_id)

    @mcp.tool(title="Get task output")
    def get_task_output(task_id: str) -> dict[str, Any]:
        """Retrieve the final response and outcome for a completed or failed task."""
        return runtime.task_output(task_id)

    @mcp.tool(title="List recent Harness sessions")
    def list_sessions() -> list[dict[str, Any]]:
        """List bridge-owned persistent sessions and their approved workspace directories."""
        return runtime.list_sessions()

    @mcp.tool(title="Resume a Harness session")
    def resume_session(session_id: str, task: str) -> dict[str, Any]:
        """Resume a bridge-owned persisted session and run a follow-up task."""
        return runtime.resume_session(session_id, task)

    @mcp.tool(title="Change session working directory")
    def set_working_directory(session_id: str, path: str) -> dict[str, Any]:
        """Change a bridge-owned session's directory to another existing path inside the approved workspace root."""
        return runtime.set_working_directory(session_id, path)

    @mcp.tool(title="List pending approvals")
    def pending_approvals() -> list[dict[str, Any]]:
        """List Harness operations waiting for one-time user approval; expired approvals are rejected."""
        return runtime.pending_approvals()

    @mcp.tool(title="Decide one pending approval")
    def decide_approval(approval_id: str, approved: bool) -> dict[str, Any]:
        """Approve exactly one pending Harness operation only after the user explicitly authorizes it; false rejects it."""
        return runtime.decide_approval(approval_id, approved)

    @mcp.tool(title="List pending user questions")
    def pending_questions() -> list[dict[str, Any]]:
        """List agent questions awaiting an answer from the user; unanswered questions expire as cancelled."""
        return runtime.pending_questions()

    @mcp.tool(title="Answer a Harness user question")
    def answer_question(request_id: str, answers: list[dict[str, Any]]) -> dict[str, Any]:
        """Answer every question ID in one pending request, preserving the original option labels."""
        return runtime.answer_question(request_id, answers)

    # Quick Tunnels do not support SSE. JSON response mode keeps MCP request
    # responses on ordinary HTTP while retaining Streamable HTTP session state.
    # The outer TrustedHost middleware checks the tunnel Host; MCP's own host
    # check is disabled because Cloudflare terminates TLS and forwards that host.
    transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    app = mcp.streamable_http_app(
        json_response=True,
        stateless_http=False,
        transport_security=transport_security,
        host="127.0.0.1",
        max_request_body_size=1_048_576,
        max_sessions=2,
    )
    allowed_hosts = ["localhost", "127.0.0.1", "*.trycloudflare.com"]
    extra_hosts = os.environ.get("MCP_ALLOWED_HOSTS", "").strip()
    if extra_hosts:
        allowed_hosts.extend(host.strip() for host in extra_hosts.split(",") if host.strip())
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    app.add_middleware(BearerAuthMiddleware, token=selected.bearer_token)

    async def healthz(_request: Request) -> Response:
        return JSONResponse({"status": "ok", "service": "deepseek-harness-mcp"})

    app.add_route("/healthz", healthz, methods=["GET"])
    app.state.harness_runtime = runtime
    return app


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    config = BridgeConfig.from_env()
    app = create_app(config)
    runtime = app.state.harness_runtime
    atexit.register(runtime.close)
    _LOG.info("Starting authenticated MCP server on 127.0.0.1:%s", config.port)
    uvicorn.run(app, host="127.0.0.1", port=config.port, log_level="info")


if __name__ == "__main__":
    main()
