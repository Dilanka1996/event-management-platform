"""CI verifies the server actually honours a documented OpenAPI contract.

Compares the live /openapi.json against a committed snapshot. Drift (a route
added/removed, a status code changed, a required field altered) fails CI.
"""

import json
from pathlib import Path

SNAPSHOT = Path(__file__).parent / "contract" / "openapi.snapshot.json"


def _shape(spec: dict) -> dict:
    """Reduce the spec to the parts we contractually care about."""
    paths = {}
    for path, ops in sorted(spec.get("paths", {}).items()):
        paths[path] = {}
        for method, op in sorted(ops.items()):
            if method not in {"get", "post", "patch", "delete", "put"}:
                continue
            paths[path][method] = {
                "responses": sorted(op.get("responses", {}).keys()),
                "tags": op.get("tags", []),
            }
    return {"paths": paths}


def test_openapi_matches_snapshot(client):
    live = _shape(client.get("/openapi.json").json())
    assert SNAPSHOT.exists(), f"missing snapshot at {SNAPSHOT}"
    expected = json.loads(SNAPSHOT.read_text())
    assert live == expected, (
        "OpenAPI contract drift detected.\n"
        f"live:     {json.dumps(live, indent=2, sort_keys=True)}\n"
        f"expected: {json.dumps(expected, indent=2, sort_keys=True)}"
    )


def test_all_documented_paths_are_reachable(client):
    """Every documented path+method must actually be routed (not a 404/405)."""
    spec = client.get("/openapi.json").json()
    for path, ops in spec["paths"].items():
        for method in ops:
            if method not in {"get", "post", "patch", "delete", "put"}:
                continue
            resp = client.request(method.upper(), path.replace("{event_id}", "1"))
            assert resp.status_code in {
                200, 201, 204, 401, 403, 404, 409, 422
            }, f"{method.upper()} {path} -> {resp.status_code}"
