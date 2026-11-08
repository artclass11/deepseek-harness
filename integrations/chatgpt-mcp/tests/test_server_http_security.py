from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from starlette.testclient import TestClient

from deepseek_harness_mcp.config import BridgeConfig
from deepseek_harness_mcp.server import create_app


class McpHttpSecurityTests(unittest.TestCase):
    def make_config(self, temporary: str) -> BridgeConfig:
        root = Path(temporary) / "workspace"
        home = Path(temporary) / "state"
        root.mkdir()
        home.mkdir()
        return BridgeConfig(
            dsh_home=home,
            workspace_root=root,
            bearer_token="b" * 64,
        )

    def test_health_route_requires_bearer_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = create_app(self.make_config(temporary))
            client = TestClient(app)
            response = client.get("/healthz", headers={"host": "localhost"})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["www-authenticate"], "Bearer")
            self.assertEqual(response.json(), {"error": "unauthorized"})

    def test_health_route_accepts_valid_bearer_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self.make_config(temporary)
            app = create_app(config)
            client = TestClient(app)
            response = client.get(
                "/healthz",
                headers={
                    "host": "localhost",
                    "authorization": f"Bearer {config.bearer_token}",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "ok")

    def test_rejects_untrusted_host_even_with_valid_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self.make_config(temporary)
            app = create_app(config)
            client = TestClient(app)
            response = client.get(
                "/healthz",
                headers={
                    "host": "attacker.invalid",
                    "authorization": f"Bearer {config.bearer_token}",
                },
            )
            self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
