from __future__ import annotations

import argparse
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from deepseek_harness_mcp.plugin_builder import build_plugin


def main() -> None:
    parser = argparse.ArgumentParser(description="Package a private DeepSeek Harness ChatGPT MCP plugin.")
    parser.add_argument("--endpoint", required=True, help="Verified HTTPS MCP endpoint ending in /mcp.")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(build_plugin(args.endpoint, args.output))


if __name__ == "__main__":
    main()
