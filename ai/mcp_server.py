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
# Tool: get_vrrp_state
# ---------------------------------------------------------------------------

@mcp.tool()
def get_vrrp_state(device_name: str) -> dict:
    """
    Return live VRRP group state for a device.

    Connects to the device, parses 'show vrrp' output, disconnects.
    Applicable to core switches running VRRP (EOS only).

    EOS: device.execute() + regex (no Genie VRRP parser available for EOS)

    Args:
        device_name: Name of the device as defined in inventory (e.g. 'core-sw-01')
    """
    testbed = _load_testbed()

    if device_name not in testbed.devices:
        return {"error": f"Device '{device_name}' not found in testbed"}

    try:
        device = _connect_device(testbed, device_name)

        output = device.execute("show vrrp")
        groups = []

        current_vlan = None
        current_group = None
        current_data = {}

        for line in output.splitlines():
            header = re.match(r"Vlan(\d+)\s+-\s+Group\s+(\d+)", line.strip())
            if header:
                if current_vlan is not None and current_data:
                    groups.append({
                        "vlan": current_vlan,
                        "group": current_group,
                        **current_data,
                    })
                current_vlan = int(header.group(1))
                current_group = int(header.group(2))
                current_data = {}
                continue

            if current_vlan is None:
                continue

            state_match = re.match(r"State is (\S+)", line.strip())
            if state_match:
                current_data["state"] = state_match.group(1).lower()

            vip_match = re.match(r"Virtual IPv4 address is (\S+)", line.strip())
            if vip_match:
                current_data["virtual_ip"] = vip_match.group(1)

        # Flush last group
        if current_vlan is not None and current_data:
            groups.append({
                "vlan": current_vlan,
                "group": current_group,
                **current_data,
            })

        device.disconnect()
        return {"device": device_name, "vrrp_groups": groups}

    except Exception as exc:
        return {"error": f"Failed to query {device_name}: {str(exc)}"}
    
# ---------------------------------------------------------------------------
# Tool: get_mlag_state
# ---------------------------------------------------------------------------

@mcp.tool()
def get_mlag_state(device_name: str) -> dict:
    """
    Return live MLAG domain state and interface states for a device.

    Connects to the device, parses 'show mlag' and 'show mlag interfaces',
    disconnects. Applicable to core switches running MLAG (EOS only).

    EOS: device.execute() + regex (no Genie MLAG parser available for EOS)

    Args:
        device_name: Name of the device as defined in inventory (e.g. 'core-sw-01')
    """
    testbed = _load_testbed()

    if device_name not in testbed.devices:
        return {"error": f"Device '{device_name}' not found in testbed"}

    try:
        device = _connect_device(testbed, device_name)

        # --- Domain state ---
        domain_output = device.execute("show mlag")
        domain = {}
        patterns = {
            "state": r"^state\s*:\s*(\S+)",
            "negotiation_status": r"^negotiation status\s*:\s*(\S+)",
            "peer_link_status": r"^peer-link status\s*:\s*(\S+)",
        }
        for line in domain_output.splitlines():
            for key, pattern in patterns.items():
                match = re.match(pattern, line.strip(), re.IGNORECASE)
                if match:
                    domain[key] = match.group(1).lower()

        # --- Interface states ---
        intf_output = device.execute("show mlag interfaces")
        interfaces = []
        for line in intf_output.splitlines():
            match = re.match(r"\s+(\d+)\s+\S.*?\s{2,}(\S+)\s+\S+\s+\S+\s+\S+", line)
            if match:
                interfaces.append({
                    "mlag_id": int(match.group(1)),
                    "state": match.group(2).lower(),
                })

        device.disconnect()
        return {
            "device": device_name,
            "mlag_domain": domain,
            "mlag_interfaces": interfaces,
        }

    except Exception as exc:
        return {"error": f"Failed to query {device_name}: {str(exc)}"}

# ---------------------------------------------------------------------------
# Tool: get_interface_status
# ---------------------------------------------------------------------------

@mcp.tool()
def get_interface_status(device_name: str) -> dict:
    """
    Return interface up/down state and description for all interfaces on a device.

    Connects to the device, parses interface state, disconnects.
    Applicable to all devices (IOS XE and EOS).

    IOS XE: Genie parser for 'show interfaces'
    EOS:    Genie parser for 'show interfaces', falls back to
            device.execute() + regex if parser unavailable

    Args:
        device_name: Name of the device as defined in inventory (e.g. 'rtr-01')
    """
    testbed = _load_testbed()

    if device_name not in testbed.devices:
        return {"error": f"Device '{device_name}' not found in testbed"}

    try:
        device = _connect_device(testbed, device_name)
        interfaces = []

        try:
            parsed = device.parse("show interfaces")
            for intf_name, intf_data in parsed.items():
                interfaces.append({
                    "interface": intf_name,
                    "oper_status": intf_data.get("oper_status", "unknown").lower(),
                    "line_protocol": intf_data.get("line_protocol", "unknown").lower(),
                    "description": intf_data.get("description", ""),
                })

        except Exception:
            # Genie parser unavailable for this platform — fall back to regex
            output = device.execute("show interfaces")
            current_intf = None
            current_data = {}

            for line in output.splitlines():
                # Match interface header: "Ethernet1 is up, line protocol is up"
                header = re.match(
                    r"^(\S+)\s+is\s+(\S+),\s+line protocol is\s+(\S+)", line.strip()
                )
                if header:
                    if current_intf:
                        interfaces.append(current_data)
                    current_intf = header.group(1)
                    current_data = {
                        "interface": current_intf,
                        "oper_status": header.group(2).lower().rstrip(","),
                        "line_protocol": header.group(3).lower().rstrip(","),
                        "description": "",
                    }
                    continue

                if current_intf is None:
                    continue

                desc_match = re.match(r"Description:\s+(.*)", line.strip())
                if desc_match:
                    current_data["description"] = desc_match.group(1).strip()

            if current_intf:
                interfaces.append(current_data)

        device.disconnect()
        return {"device": device_name, "interfaces": interfaces}

    except Exception as exc:
        return {"error": f"Failed to query {device_name}: {str(exc)}"}

# ---------------------------------------------------------------------------
# Tool: get_routing_table
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Tool: get_routing_table
# ---------------------------------------------------------------------------

@mcp.tool()
def get_routing_table(device_name: str, prefix: str) -> dict:
    """
    Look up a specific prefix in the routing table of a device.

    Connects to the device, queries the RIB for the given prefix,
    disconnects. Applicable to all devices (IOS XE and EOS).

    IOS XE: Genie parser for 'show ip route <host>'
    EOS:    device.execute() + regex (no Genie RIB parser for EOS)

    Args:
        device_name: Name of the device as defined in inventory (e.g. 'rtr-01')
        prefix:      IP prefix to look up (e.g. '2.2.2.2/32' or '10.1.0.0/30')
    """
    testbed = _load_testbed()

    if device_name not in testbed.devices:
        return {"error": f"Device '{device_name}' not found in testbed"}

    try:
        device = _connect_device(testbed, device_name)
        routes = []

        if device.os == "iosxe":
            host = prefix.split("/")[0]
            parsed = device.parse(f"show ip route {host}")
            for route_prefix, entry in parsed.get("entry", {}).items():
                protocol = entry.get("known_via", "unknown")
                preference = entry.get("distance", "")
                metric = entry.get("metric", "")
                for path in entry.get("paths", {}).values():
                    routes.append({
                        "prefix": route_prefix,
                        "protocol": protocol,
                        "next_hop": path.get("nexthop", ""),
                        "outgoing_interface": path.get("interface", ""),
                        "metric": metric,
                        "preference": preference,
                    })
        else:
            # EOS output is two lines per route:
            # Line 1: " C        10.1.0.0/30 [110/20]"  (AD/metric optional)
            # Line 2: "           directly connected, Ethernet1"
            #      or "           via 10.0.0.1, Ethernet3"
            output = device.execute(f"show ip route {prefix}")
            current_route = None

            for line in output.splitlines():
                # Line 1 — protocol code + prefix
                header = re.match(
                    r"^\s+([A-Z][A-Z0-9 ]*?)\s{2,}(\d+\.\d+\.\d+\.\d+/\d+)"
                    r"(?:\s+\[(\d+)/(\d+)\])?",
                    line,
                )
                if header:
                    current_route = {
                        "prefix": header.group(2),
                        "protocol": header.group(1).strip(),
                        "preference": int(header.group(3)) if header.group(3) else "",
                        "metric": int(header.group(4)) if header.group(4) else "",
                        "next_hop": "",
                        "outgoing_interface": "",
                    }
                    continue

                if current_route is None:
                    continue

                # Line 2a — via next-hop
                via = re.match(r"^\s+via\s+(\S+),\s+(\S+)", line)
                if via:
                    current_route["next_hop"] = via.group(1).rstrip(",")
                    current_route["outgoing_interface"] = via.group(2)
                    routes.append(current_route)
                    current_route = None
                    continue

                # Line 2b — directly connected
                direct = re.match(r"^\s+directly connected,\s+(\S+)", line)
                if direct:
                    current_route["next_hop"] = "directly connected"
                    current_route["outgoing_interface"] = direct.group(1)
                    routes.append(current_route)
                    current_route = None

        device.disconnect()

        if not routes:
            return {
                "device": device_name,
                "prefix": prefix,
                "found": False,
                "routes": [],
            }

        return {
            "device": device_name,
            "prefix": prefix,
            "found": True,
            "routes": routes,
        }

    except Exception as exc:
        return {"error": f"Failed to query {device_name}: {str(exc)}"}

# ---------------------------------------------------------------------------
# Tool: get_ntp_status
# ---------------------------------------------------------------------------

@mcp.tool()
def get_ntp_status(device_name: str) -> dict:
    """
    Return NTP sync state and active server for a device.

    Connects to the device, parses NTP status, disconnects.
    Applicable to edge routers and core switches (IOS XE and EOS).

    IOS XE: Genie parser for 'show ntp status'
    EOS:    device.execute() + regex (no Genie NTP parser for EOS)

    Note: EOS reports 'synchronised' (British spelling). The tool
    normalizes both to 'synchronized' in the response.

    Args:
        device_name: Name of the device as defined in inventory (e.g. 'core-sw-01')
    """
    testbed = _load_testbed()

    if device_name not in testbed.devices:
        return {"error": f"Device '{device_name}' not found in testbed"}

    try:
        device = _connect_device(testbed, device_name)
        result = {}

        if device.os == "iosxe":
            parsed = device.parse("show ntp status")
            system_status = (
                parsed
                .get("clock_state", {})
                .get("system_status", {})
            )
            result = {
                "status": system_status.get("status", "unknown").lower().replace("synchronised", "synchronized"),
                "server": system_status.get("refid", ""),
            }

        else:
            # EOS output example:
            #   synchronised to NTP server (10.20.20.100) at stratum 4
            output = device.execute("show ntp status")
            for line in output.splitlines():
                match = re.match(
                    r"(synchronised|unsynchronised)\s+to\s+NTP server\s+\((\S+)\)",
                    line.strip(),
                    re.IGNORECASE,
                )
                if match:
                    result = {
                        "status": match.group(1).lower().replace("synchronised", "synchronized"),
                        "server": match.group(2),
                    }
                    break

        device.disconnect()

        if not result:
            return {
                "device": device_name,
                "ntp_status": "unknown",
                "server": "",
            }

        return {
            "device": device_name,
            "ntp_status": result.get("status", "unknown"),
            "server": result.get("server", ""),
        }

    except Exception as exc:
        return {"error": f"Failed to query {device_name}: {str(exc)}"}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8001)