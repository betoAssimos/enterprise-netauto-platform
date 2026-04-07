# ai/mcp_server.py
#
# FastMCP server — exposes read-only network query tools.
#
# Tools:
#   get_device_inventory   — list all devices with role, IP, OS from hosts.yaml
#   get_bgp_state          — live BGP neighbor state + prefix counts from a device
#   get_ospf_neighbors     — live OSPF neighbor state from a device
#
# Each tool connects to the device live via pyATS, runs the query, disconnects.
# No state is cached — every call reflects current network state.
#
# Run:
#   python ai/mcp_server.py

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP
from nornir import InitNornir

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=BASE_DIR / ".env")

mcp = FastMCP(
    name="network-automation-server",
    instructions="Read-only network state query server. "
                 "Use these tools to inspect live BGP, OSPF, and inventory data.",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_nornir():
    return InitNornir(
        inventory={
            "plugin": "SimpleInventory",
            "options": {
                "host_file": str(BASE_DIR / "automation/inventory/hosts.yaml"),
                "group_file": str(BASE_DIR / "automation/inventory/groups.yaml"),
                "defaults_file": str(BASE_DIR / "automation/inventory/defaults.yaml"),
            },
        },
        logging={"enabled": False},
    )


def _connect_device(testbed, device_name: str):
    """Connect to a single device from a pyATS testbed."""
    device = testbed.devices[device_name]
    device.credentials.default.username = os.environ.get("DEVICE_USERNAME")
    device.credentials.default.password = os.environ.get("DEVICE_PASSWORD")
    device.connect(log_stdout=False, timeout=60)
    return device


def _load_testbed():
    from pyats.topology import loader
    return loader.load(str(BASE_DIR / "tests/testbed.yaml"))


# ---------------------------------------------------------------------------
# Tool: get_device_inventory
# ---------------------------------------------------------------------------

@mcp.tool()
def get_device_inventory() -> dict:
    """
    Return all devices from inventory with their role, management IP, and OS.

    No device connection required — reads directly from hosts.yaml.
    """
    nr = _init_nornir()
    inventory = []

    for host_name, host in nr.inventory.hosts.items():
        inventory.append({
            "name": host_name,
            "hostname": host.hostname,
            "role": host.data.get("role", "unknown"),
            "os": host.platform or host.groups[0].name if host.groups else "unknown",
        })

    return {"devices": inventory, "count": len(inventory)}


# ---------------------------------------------------------------------------
# Tool: get_bgp_state
# ---------------------------------------------------------------------------

@mcp.tool()
def get_bgp_state(device_name: str) -> dict:
    """
    Return live BGP neighbor state and prefix counts for a device.

    Connects to the device, parses 'show bgp all summary', disconnects.
    Only applicable to edge routers running BGP.

    Args:
        device_name: Name of the device as defined in inventory (e.g. 'rtr-01')
    """
    testbed = _load_testbed()

    if device_name not in testbed.devices:
        return {"error": f"Device '{device_name}' not found in testbed"}

    try:
        device = _connect_device(testbed, device_name)

        parsed = device.parse("show bgp all summary")
        neighbors = []

        for vrf_data in parsed.get("vrf", {}).values():
            for peer_ip, peer_data in vrf_data.get("neighbor", {}).items():
                af_data = next(iter(peer_data.get("address_family", {}).values()), {})
                state_pfxrcd = str(af_data.get("state_pfxrcd", "unknown"))
                if state_pfxrcd.isdigit():
                    session_state = "established"
                    prefix_count = int(state_pfxrcd)
                else:
                    session_state = state_pfxrcd.lower()
                    prefix_count = 0

                neighbors.append({
                    "neighbor_ip": peer_ip,
                    "remote_as": af_data.get("as"),
                    "session_state": session_state,
                    "prefix_count": prefix_count,
                })

        device.disconnect()
        return {"device": device_name, "bgp_neighbors": neighbors}

    except Exception as exc:
        return {"error": f"Failed to query {device_name}: {str(exc)}"}


# ---------------------------------------------------------------------------
# Tool: get_ospf_neighbors
# ---------------------------------------------------------------------------

@mcp.tool()
def get_ospf_neighbors(device_name: str) -> dict:
    """
    Return live OSPF neighbor state for a device.

    Connects to the device, parses OSPF neighbor table, disconnects.
    Applicable to edge routers and core switches running OSPF.

    IOS XE: Genie parser for 'show ip ospf neighbor'
    EOS:    device.execute() + regex (no Genie OSPF parser for EOS)

    Args:
        device_name: Name of the device as defined in inventory (e.g. 'core-sw-01')
    """
    testbed = _load_testbed()

    if device_name not in testbed.devices:
        return {"error": f"Device '{device_name}' not found in testbed"}

    try:
        device = _connect_device(testbed, device_name)
        neighbors = []

        if device.os == "iosxe":
            parsed = device.parse("show ip ospf neighbor")
            for intf_name, intf_data in parsed.get("interfaces", {}).items():
                for neighbor_id, neighbor_data in intf_data.get("neighbors", {}).items():
                    neighbors.append({
                        "neighbor_id": neighbor_id,
                        "state": neighbor_data.get("state", "unknown").lower(),
                        "interface": intf_name,
                    })
        else:
            output = device.execute("show ip ospf neighbor")
            for line in output.splitlines():
                match = re.match(
                    r"(\d+\.\d+\.\d+\.\d+)\s+\S+\s+\S+\s+\d+\s+(\S+)\s+\S+\s+(\S+)\s+(\S+)",
                    line,
                )
                if match:
                    neighbors.append({
                        "neighbor_id": match.group(1),
                        "state": match.group(2).lower(),
                        "interface": match.group(4),
                    })

        device.disconnect()
        return {"device": device_name, "ospf_neighbors": neighbors}

    except Exception as exc:
        return {"error": f"Failed to query {device_name}: {str(exc)}"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8001)