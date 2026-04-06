# automation/workflows/switching/mlag_intent_builder.py
#
# MLAG Intent Builder — derives expected MLAG domain and interface state
# from inventory data.
#
# Input:  Nornir Task (host data sourced from hosts.yaml)
# Output: dict with expected domain state and expected MLAG interfaces
#
# Intent is fully deterministic — no additional inventory fields required.
# Domain must be Active with peer-link Up. All MLAG port-channels must
# be active-full.
#
# This module contains NO rendering logic. Keep it separate from context
# builders.

from __future__ import annotations
from nornir.core.task import Task


def build_mlag_intent(task: Task) -> dict:
    """
    Derive MLAG intent for a single device.

    Returns:
        {
            "expected_domain": {
                "domain_id": 1,
                "expected_state": "Active",
                "expected_negotiation_status": "Connected",
                "expected_peer_link_status": "Up",
                "peer_link": "Port-Channel1"
            },
            "expected_mlag_interfaces": [
                {"mlag_id": 10, "expected_state": "active-full"},
                {"mlag_id": 20, "expected_state": "active-full"}
            ]
        }

    Returns None for expected_domain and empty list for
    expected_mlag_interfaces if MLAG is not configured on this device.
    """
    cf = task.host.data.get("custom_fields", {})

    domain_id = cf.get("mlag_domain_id")
    peer_link = cf.get("mlag_peer_link")
    portchannels = cf.get("mlag_portchannels", [])

    if not domain_id:
        return {
            "expected_domain": None,
            "expected_mlag_interfaces": [],
        }

    expected_domain = {
        "domain_id": domain_id,
        "expected_state": "Active",
        "expected_negotiation_status": "Connected",
        "expected_peer_link_status": "Up",
        "peer_link": peer_link,
    }

    expected_mlag_interfaces = [
        {
            "mlag_id": pc["mlag_id"],
            "expected_state": "active-full",
        }
        for pc in portchannels
    ]

    return {
        "expected_domain": expected_domain,
        "expected_mlag_interfaces": expected_mlag_interfaces,
    }