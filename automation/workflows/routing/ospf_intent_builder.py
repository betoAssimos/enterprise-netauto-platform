# automation/workflows/routing/ospf_intent_builder.py
#
# OSPF Intent Builder — derives expected neighbor state and route presence
# from inventory data.
#
# Input:  Nornir Task (host data sourced from hosts.yaml)
# Output: dict with expected_neighbors and expected_routes per device
#
# Two intent signals:
#   expected_neighbors — each neighbor that must be in FULL state
#   expected_routes    — each neighbor's router-ID (/32) that must appear
#                        in the local OSPF routing table
#
# ospf_route_expected: false on a neighbor entry excludes its router-ID
# from expected_routes. Use this when the route is reachable via a
# lower-AD protocol (e.g. eBGP AD 20 beats OSPF AD 110 on the eBGP
# peering link between rtr-01 and rtr-02).
#
# This module contains NO rendering logic. Keep it separate from context
# builders.

from __future__ import annotations
from nornir.core.task import Task


def build_ospf_intent(task: Task) -> dict:
    """
    Derive OSPF intent for a single device.

    Returns:
        {
            "expected_neighbors": [
                {
                    "neighbor_id": "3.3.3.3",
                    "neighbor_ip": "10.1.0.2",
                    "expected_state": "Full"
                }
            ],
            "expected_routes": ["3.3.3.3/32", "4.4.4.4/32"]
        }

    Neighbors with ospf_route_expected: false are included in
    expected_neighbors (state is still checked) but excluded from
    expected_routes (route presence is not checked).
    """
    cf = task.host.data.get("custom_fields", {})
    neighbors = cf.get("ospf_neighbors", [])

    expected_neighbors = [
        {
            "neighbor_id": n["neighbor_id"],
            "neighbor_ip": n["neighbor_ip"],
            "expected_state": n.get("expected_state", "Full"),
        }
        for n in neighbors
    ]

    expected_routes = [
        f"{n['neighbor_id']}/32"
        for n in neighbors
        if n.get("ospf_route_expected", True)
    ]

    return {
        "expected_neighbors": expected_neighbors,
        "expected_routes": expected_routes,
    }