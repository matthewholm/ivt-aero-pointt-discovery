"""Recursively crawl the PoinTT resource tree via its self-describing
`refEnum` nodes, instead of guessing paths from another device's schema.

A GET on a category path returns either:
  - a leaf value: {"id": ..., "type": "stringValue"/"floatValue"/etc., "value": ...}
  - a category:   {"id": ..., "type": "refEnum", "references": [{"id": ...}, ...]}

We start from a small set of known-good roots (found via the earlier
discover_endpoints.py sweep: /system, /gateway) and follow every
"refEnum" reference until we hit leaves, recording the full tree.

Leaf ids that look like secrets (password, token, secret, key) are noted
as "skipped_sensitive" and never fetched — the K30 exposes a couple of
these (e.g. /gateway/xmppPassword) and we don't want them in a results
file that might get shared or committed.

Run:
    python crawl_tree.py
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from pointt_client import PointtClient, PointtAuthError, TokenState

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

ROOTS = [
    "/system",
    "/gateway",
    "/notifications",
    # /airConditioning itself isn't a fetchable resource (unlike /system,
    # /gateway) — these three are the real entry points, per homecom_alt's
    # rac.py (async_get_stardard / async_get_advanced / async_get_switch).
    "/airConditioning/standardFunctions",
    "/airConditioning/advancedFunctions",
    "/airConditioning/switchPrograms/list",
    "/airConditioning/timers",
]

SENSITIVE_MARKERS = ("password", "secret", "token", "key", "credential")

MAX_DEPTH = 8
REQUEST_DELAY = 0.3


def is_sensitive(path: str) -> bool:
    lower = path.lower()
    return any(marker in lower for marker in SENSITIVE_MARKERS)


def crawl(client: PointtClient) -> dict:
    visited: set[str] = set()
    nodes: dict[str, dict] = {}
    queue: list[tuple[str, int]] = [(root, 0) for root in ROOTS]

    while queue:
        path, depth = queue.pop(0)
        if path in visited or depth > MAX_DEPTH:
            continue
        visited.add(path)

        if is_sensitive(path):
            nodes[path] = {"skipped_sensitive": True}
            print(f"[SKIP] {path} (looks sensitive, not fetched)")
            continue

        status, body = client.get(path)
        time.sleep(REQUEST_DELAY)

        if status != 200:
            nodes[path] = {"status": status, "error": body}
            print(f"[{status}] {path}")
            continue

        nodes[path] = {"status": 200, "body": body}

        if isinstance(body, dict) and body.get("type") == "refEnum":
            # Children are stubs {"id": ..., "uri": ...} — need a follow-up GET.
            refs = body.get("references", [])
            print(f"[200] {path} -> {len(refs)} children (refEnum)")
            for ref in refs:
                child_id = ref.get("id")
                if child_id and child_id not in visited:
                    queue.append((child_id, depth + 1))
        elif isinstance(body, dict) and body.get("type") == "bulk":
            # Children are already fully resolved (id/type/value inline) —
            # record them directly, no extra GET needed.
            refs = body.get("references", [])
            print(f"[200] {path} -> {len(refs)} children (bulk, already resolved)")
            for ref in refs:
                child_id = ref.get("id")
                if child_id:
                    visited.add(child_id)
                    nodes[child_id] = {"status": 200, "body": ref, "via_bulk_parent": path}
        else:
            value_preview = body.get("value") if isinstance(body, dict) else body
            print(f"[200] {path} = {value_preview!r}")

    return nodes


def main() -> None:
    try:
        state = TokenState.load()
    except FileNotFoundError as err:
        print(f"ERROR: {err}")
        return

    try:
        client = PointtClient(state)
    except PointtAuthError as err:
        print(f"ERROR: could not obtain a valid access token: {err}")
        return

    print(f"Crawling PoinTT resource tree for gateway {client.state.device_id}\n")
    nodes = crawl(client)

    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"resource_tree_{timestamp}.json"
    out_path.write_text(
        json.dumps(
            {
                "device_id": client.state.device_id,
                "crawled_at": datetime.now(timezone.utc).isoformat(),
                "roots": ROOTS,
                "nodes": nodes,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    leaves = [p for p, n in nodes.items() if n.get("status") == 200 and isinstance(n.get("body"), dict) and n["body"].get("type") != "refEnum"]
    print(f"\nCrawled {len(nodes)} nodes, {len(leaves)} leaf values. Full tree: {out_path}")


if __name__ == "__main__":
    main()
