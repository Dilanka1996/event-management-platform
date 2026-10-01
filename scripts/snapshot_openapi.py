"""Regenerate the committed OpenAPI contract snapshot.

Run with:  python -m scripts.snapshot_openapi
CI compares the live spec against this file; regenerate deliberately when the
API changes on purpose.
"""

import json
from pathlib import Path

from app.main import app

SNAPSHOT = Path(__file__).parent.parent / "tests" / "contract" / "openapi.snapshot.json"


def shape(spec: dict) -> dict:
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


def main() -> None:
    spec = app.openapi()
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(shape(spec), indent=2, sort_keys=True) + "\n")
    print(f"[snapshot] wrote {SNAPSHOT}")


if __name__ == "__main__":
    main()
