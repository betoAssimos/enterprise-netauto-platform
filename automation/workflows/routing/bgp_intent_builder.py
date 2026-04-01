# automation/workflows/routing/bgp_intent_builder.py
#
# BGP Intent Builder — derives intended advertised prefixes from inventory data.
#
# Input:  Nornir Task (host data sourced from hosts.yaml)
# Output: dict with advertised_prefixes list per device
#
# Intent is derived from the policy chain:
#   neighbor.route_map_out → route-map entries → prefix-list → permit entries
#
# This module contains NO rendering logic. It only reads inventory data
# and produces structured intent. Keep it separate from context builders.


from __future__ import annotations
from nornir.core.task import Task


def build_bgp_intent(task: Task) -> dict:
    """
    Derive BGP advertised prefix intent for a single device.

    Traverses the outbound route-map → prefix-list chain defined in
    custom_fields and returns only prefixes explicitly permitted.

    Returns:
        {
            "advertised_prefixes": [
                {"prefix": "X.X.X.X/32", "source_prefix_list": "PL-NAME"}
            ]
        }

    Returns an empty list if no outbound policy is defined.
    """
    cf = task.host.data.get("custom_fields", {})

    neighbors = cf.get("bgp_neighbors", [])
    route_maps = cf.get("bgp_route_maps", [])
    prefix_lists = cf.get("bgp_prefix_lists", [])

    # Index route-maps and prefix-lists by name for O(1) lookup
    route_map_index = {rm["name"]: rm for rm in route_maps}
    prefix_list_index = {pl["name"]: pl for pl in prefix_lists}

    advertised_prefixes = []
    seen = set()  # guard against duplicates from multiple neighbors

    for neighbor in neighbors:
        route_map_name = neighbor.get("route_map_out")
        if not route_map_name:
            continue

        route_map = route_map_index.get(route_map_name)
        if not route_map:
            continue

        for entry in route_map.get("entries", []):
            if entry.get("action") != "permit":
                continue

            pl_name = entry.get("match_prefix_list")
            if not pl_name:
                continue

            prefix_list = prefix_list_index.get(pl_name)
            if not prefix_list:
                continue

            for pl_entry in prefix_list.get("entries", []):
                if pl_entry.get("action") != "permit":
                    continue

                prefix = pl_entry.get("prefix")
                if prefix and prefix not in seen:
                    seen.add(prefix)
                    advertised_prefixes.append({
                        "prefix": prefix,
                        "source_prefix_list": pl_name,
                    })

    return {"advertised_prefixes": advertised_prefixes}