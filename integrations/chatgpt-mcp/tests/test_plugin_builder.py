from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from deepseek_harness_mcp.plugin_builder import build_plugin


class PluginBuilderTests(unittest.TestCase):
    def test_builds_agent_plugin_archive_with_bearer_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "plugin.zip"
            build_plugin("https://sample.trycloudflare.com/mcp", archive)
            with zipfile.ZipFile(archive) as bundle:
                manifest = json.loads(bundle.read("plugin.json"))
                mcp = json.loads(bundle.read("mcp.json"))
            self.assertEqual(manifest["name"], "deepseek-harness-local")
            server = mcp["mcpServers"]["deepseek-harness"]
            self.assertEqual(server["url"], "https://sample.trycloudflare.com/mcp")
            self.assertEqual(server["extensions"]["com.openai"]["auth"]["headerScheme"], "bearer")

    def test_rejects_non_https_or_non_mcp_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "plugin.zip"
            for endpoint in ("http://example.com/mcp", "https://example.com/", "https://user:pw@example.com/mcp"):
                with self.subTest(endpoint=endpoint):
                    with self.assertRaises(ValueError):
                        build_plugin(endpoint, archive)


if __name__ == "__main__":
    unittest.main()
