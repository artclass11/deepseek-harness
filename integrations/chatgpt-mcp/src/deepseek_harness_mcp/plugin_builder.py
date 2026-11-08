from __future__ import annotations

import ipaddress
import json
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

_TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "plugin-template"


def _validate_endpoint(endpoint: str) -> str:
    normalized = endpoint.strip()
    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("endpoint must be a valid HTTPS URL") from exc
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ValueError("endpoint must be an HTTPS URL without embedded credentials")
    if parsed.path.rstrip("/") != "/mcp" or parsed.query or parsed.fragment:
        raise ValueError("endpoint must be the MCP endpoint ending in /mcp without query or fragment")
    if port not in (None, 443):
        raise ValueError("endpoint must use the standard HTTPS port")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".test")):
        raise ValueError("endpoint must use a public DNS hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("endpoint must use a DNS hostname, not an IP address")
    return normalized.rstrip("/")


def build_plugin(endpoint: str, output: Path) -> Path:
    """Create a private-plugin-ready ZIP using a verified live HTTPS MCP endpoint."""
    url = _validate_endpoint(endpoint)
    manifest = json.loads((_TEMPLATE_ROOT / "plugin.json").read_text(encoding="utf-8"))
    mcp_config = {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        "mcpServers": {
            "deepseek-harness": {
                "type": "streamable-http",
                "url": url,
                "extensions": {
                    "com.openai": {
                        "auth": {
                            "type": "api_key",
                            "headerScheme": "bearer",
                        }
                    }
                },
            }
        },
    }
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("plugin.json", json.dumps(manifest, indent=2) + "\n")
        archive.writestr("mcp.json", json.dumps(mcp_config, indent=2) + "\n")
        skill = _TEMPLATE_ROOT / "skills" / "deepseek-harness" / "SKILL.md"
        archive.write(skill, "skills/deepseek-harness/SKILL.md")
    with zipfile.ZipFile(output) as archive:
        required = {"plugin.json", "mcp.json", "skills/deepseek-harness/SKILL.md"}
        if set(archive.namelist()) != required:
            raise RuntimeError("generated plugin archive has an unexpected file layout")
        json.loads(archive.read("plugin.json"))
        json.loads(archive.read("mcp.json"))
    return output
