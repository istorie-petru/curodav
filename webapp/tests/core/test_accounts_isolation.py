"""The Accounts vault is never reachable through the API or MCP: none of their modules may import the vault (features/accounts-vault.md)."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
API_SIDE = ["api_service.py", "api_write.py", "api_library.py", "api_university.py", "api_endnotes.py", "api_auth.py", "api_history.py",
            "mcp_server.py", "routers/api_v1.py", "routers/mcp.py", "routers/oauth.py", "search_index.py"]


def test_no_api_or_mcp_module_imports_the_vault():
    offenders = [name for name in API_SIDE if (SRC / name).exists()
                 and re.search(r"\bvault_(kdbx|service|session|exchange)\b|routers\.accounts|from \.accounts", (SRC / name).read_text(encoding="utf-8"))]
    assert not offenders, f"these must not touch the Accounts vault: {offenders}"
