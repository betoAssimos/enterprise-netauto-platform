# automation/workflows/services/ntp_intent_builder.py
#
# NTP Intent Builder — derives expected NTP sync state from inventory data.
#
# Input:  Nornir Task (host data sourced from hosts.yaml)
# Output: dict with expected NTP server and sync state per device
#
# Intent is derived directly from ntp.server in inventory.
# Device must be synchronized to the configured server.
#
# This module contains NO rendering logic. Keep it separate from context
# builders.

from __future__ import annotations
from nornir.core.task import Task


def build_ntp_intent(task: Task) -> dict:
    """
    Derive NTP intent for a single device.

    Reads ntp.server from inventory and returns the expected sync state.

    Returns:
        {
            "expected_server": "10.20.20.100",
            "expected_status": "synchronized"
        }

    Returns None for expected_server if ntp is not configured.
    """
    cf = task.host.data.get("custom_fields", {})
    ntp = cf.get("ntp", {})
    server = ntp.get("server")

    if not server:
        return {
            "expected_server": None,
            "expected_status": "synchronized",
        }

    return {
        "expected_server": str(server),
        "expected_status": "synchronized",
    }