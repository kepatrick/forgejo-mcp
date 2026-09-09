import importlib.util
from pathlib import Path
from types import ModuleType


def _comparison_module() -> ModuleType:
    path = Path("scripts/compare_forgejo_openapi.py")
    spec = importlib.util.spec_from_file_location("compare_forgejo_openapi", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


comparison = _comparison_module()
compare = comparison.compare
render_markdown = comparison.render_markdown


def test_openapi_comparison_reports_every_structural_change() -> None:
    before = {
        "info": {"version": "16.0.2"},
        "definitions": {"IssueMeta": {"type": "object"}},
        "paths": {"/user": {"get": {"operationId": "userGetCurrent"}}},
    }
    after = {
        "info": {"version": "16.0.3"},
        "definitions": {"IssueMeta": {"type": "object", "required": ["index", "owner", "repo"]}},
        "paths": {"/user": {"get": {"operationId": "userGetCurrent"}}},
    }

    result = compare(before, after)

    assert result["summary"] == {
        "total": 2,
        "added": 1,
        "removed": 0,
        "changed": 1,
        "endpoint_changes": 0,
        "schema_changes": 1,
        "other_changes": 1,
    }
    assert result["differences"] == [
        {
            "kind": "added",
            "pointer": "/definitions/IssueMeta/required",
            "after": ["index", "owner", "repo"],
        },
        {
            "kind": "changed",
            "pointer": "/info/version",
            "before": "16.0.2",
            "after": "16.0.3",
        },
    ]
    assert "Endpoint differences: 0" in render_markdown(result)


def test_openapi_comparison_identifies_endpoint_changes() -> None:
    before = {"info": {"version": "old"}, "paths": {}}
    after = {"info": {"version": "new"}, "paths": {"/repos/search": {"get": {}}}}

    result = compare(before, after)

    assert result["summary"]["endpoint_changes"] == 1
    assert result["differences"][1]["pointer"] == "/paths/~1repos~1search"
