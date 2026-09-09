import json
from pathlib import Path

from forgejo_mcp.tools import list_tools


def test_forgejo_v16_contract_covers_every_registered_tool() -> None:
    contract = json.loads(
        Path("tests/contracts/forgejo-v16-openapi.json").read_text(encoding="utf-8")
    )

    assert contract["verified_versions"] == {
        "16.0.2+gitea-1.22.0": {
            "image": "data.forgejo.org/forgejo/forgejo:16.0.2-rootless",
            "swagger_sha256": "9e94799decc739c31fa68d8dc1b2d7f392e810a088f10b032c9962665398612b",
        },
        "16.0.3+gitea-1.22.0": {
            "image": "data.forgejo.org/forgejo/forgejo:16.0.3-rootless",
            "swagger_sha256": "f638c2ad8ec38f7f53b5e34ce24506fd142d16c4234bde996a52a1b9ac213b0a",
        },
    }
    assert set(contract["tools"]) == {tool.name for tool in list_tools()}

    for operation in contract["tools"].values():
        assert operation["method"] in {"get", "post", "put", "patch", "delete"}
        assert operation["path"].startswith("/")
        assert operation["operation_id"]


def test_forgejo_16_0_3_diff_fixture_has_no_endpoint_change() -> None:
    comparison = json.loads(
        Path("tests/contracts/forgejo-16.0.2-to-16.0.3-openapi-diff.json").read_text(
            encoding="utf-8"
        )
    )

    assert comparison["summary"] == {
        "total": 2,
        "added": 1,
        "removed": 0,
        "changed": 1,
        "endpoint_changes": 0,
        "schema_changes": 1,
        "other_changes": 1,
    }
    assert comparison["differences"][0] == {
        "kind": "added",
        "pointer": "/definitions/IssueMeta/required",
        "after": ["index", "owner", "repo"],
    }
