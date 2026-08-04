import json
from pathlib import Path

from forgejo_mcp.tools import list_tools


def test_forgejo_v16_contract_covers_every_registered_tool() -> None:
    contract = json.loads(
        Path("tests/contracts/forgejo-v16-openapi.json").read_text(encoding="utf-8")
    )

    assert contract["forgejo_version"] == "16.0.2+gitea-1.22.0"
    assert contract["image"] == "codeberg.org/forgejo/forgejo:16.0.2-rootless"
    assert set(contract["tools"]) == {tool.name for tool in list_tools()}

    for operation in contract["tools"].values():
        assert operation["method"] in {"get", "post", "put", "patch", "delete"}
        assert operation["path"].startswith("/")
        assert operation["operation_id"]
