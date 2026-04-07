from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional

from .registry import Registry


def collect_prompt_hops(
    registry: Registry,
    family_id: str,
    start_version_id: str,
    *,
    max_hops: int = 3,
    metrics_by_version: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    metrics_by_version = metrics_by_version or {}
    versions = registry.list_versions(family_id)
    by_id = {version.id: version for version in versions}
    if start_version_id not in by_id:
        raise FileNotFoundError(f"Prompt version not found: {family_id}@{start_version_id}")

    neighbors: Dict[str, set[str]] = {version.id: set() for version in versions}
    for version in versions:
        if version.parent_id and version.parent_id in neighbors:
            neighbors[version.id].add(version.parent_id)
            neighbors[version.parent_id].add(version.id)

    hops: List[Dict[str, Any]] = []
    queue = deque([(start_version_id, 0)])
    seen: set[str] = set()

    while queue:
        current_id, distance = queue.popleft()
        if current_id in seen or distance > max_hops:
            continue
        version = by_id[current_id]
        hops.append(
            {
                "version_id": version.id,
                "label": version.label,
                "parent_id": version.parent_id,
                "hop_distance": distance,
                "status": version.status,
                "hypothesis": version.hypothesis,
                "prompt": version.body,
                "summary": metrics_by_version.get(version.id, {}),
            }
        )
        seen.add(current_id)
        for neighbor_id in sorted(neighbors[current_id]):
            if neighbor_id not in seen:
                queue.append((neighbor_id, distance + 1))

    return hops
