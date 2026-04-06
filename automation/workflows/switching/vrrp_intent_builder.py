# automation/workflows/switching/vrrp_intent_builder.py
#
# VRRP Intent Builder — derives expected VRRP group state from inventory data.
#
# Input:  Nornir Task (host data sourced from hosts.yaml)
# Output: dict with expected_vrrp_groups list per device
#
# Intent is derived directly from vrrp_groups in inventory.
# Each group entry defines the VLAN, group ID, virtual IP, and expected state.
#
# This module contains NO rendering logic. Keep it separate from context
# builders.

from __future__ import annotations
from nornir.core.task import Task


def build_vrrp_intent(task: Task) -> dict:
    """
    Derive VRRP intent for a single device.

    Reads vrrp_groups from inventory and returns the expected state
    for each group.

    Returns:
        {
            "expected_vrrp_groups": [
                {
                    "vlan": 10,
                    "group": 10,
                    "virtual_ip": "10.10.10.1",
                    "expected_state": "Master"
                },
                ...
            ]
        }

    Returns empty list if vrrp_groups is not defined.
    """
    cf = task.host.data.get("custom_fields", {})
    vrrp_groups = cf.get("vrrp_groups", [])

    expected_vrrp_groups = [
        {
            "vlan": g["vlan"],
            "group": g["group"],
            "virtual_ip": g["virtual_ip"],
            "expected_state": g.get("expected_state", "Master"),
        }
        for g in vrrp_groups
    ]

    return {"expected_vrrp_groups": expected_vrrp_groups}