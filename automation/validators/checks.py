"""
automation/validators/checks.py

pyATS / Genie pre-check and post-check Nornir tasks.

pre_check  — captures device state baseline before any change.
post_check — re-captures state after change, diffs against baseline,
             raises CheckFailure on any regression.

Design:
- Captures BGP, OSPF, VRRP, MLAG, and interface state per device
- Diff is structured, not line-by-line string comparison
- Only regressions raise — improvements are logged and ignored
- Genie parsers used where available; device.execute() + regex for EOS
- Platform detection is implicit — functions return empty on non-applicable devices
- All captured state returned in Result for archival

Parser strategy per domain:
    BGP          : IOS XE only — Genie (show bgp all summary)
    OSPF         : IOS XE — Genie; EOS — regex (no Genie OSPF parser for EOS)
    VRRP         : EOS only — regex (no Genie VRRP parser for EOS)
    MLAG         : EOS only — regex (no Genie MLAG parser for EOS)
    Interfaces   : IOS XE — Genie; EOS — Genie with regex fallback
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from nornir.core.task import Result, Task

from automation.utils.logger import get_logger

log = get_logger(__name__)


class CheckFailure(Exception):
    """Raised when post-check detects a regression against baseline."""

    def __init__(self, device: str, issues: dict[str, Any]) -> None:
        self.device = device
        self.issues = issues
        super().__init__(
            f"Post-check regression on {device}: {list(issues.keys())}"
        )


@dataclass
class DeviceState:
    """Structured snapshot of device operational state."""

    device: str
    bgp_peers: dict[str, str] = field(default_factory=dict)
    ospf_neighbors: dict[str, str] = field(default_factory=dict)
    vrrp_groups: dict[tuple, str] = field(default_factory=dict)
    mlag_state: dict[str, str] = field(default_factory=dict)
    interface_states: dict[str, str] = field(default_factory=dict)
    running_config: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "bgp_peers": self.bgp_peers,
            "ospf_neighbors": self.ospf_neighbors,
            "vrrp_groups": {str(k): v for k, v in self.vrrp_groups.items()},
            "mlag_state": self.mlag_state,
            "interface_states": self.interface_states,
        }


def pre_check(task: Task) -> Result:
    """
    Capture device state baseline before a change.

    Returns Result with:
        result["state"]          : DeviceState instance
        result["running_config"] : Raw running-config string
    """
    device = task.host.name
    log.info("Pre-check: capturing baseline", device=device)

    conn = task.host.get_connection("scrapli", task.nornir.config)
    state = DeviceState(device=device)

    try:
        state.bgp_peers = _get_bgp_peer_states(conn, device)
        log.debug("BGP peers captured", device=device, count=len(state.bgp_peers))
    except Exception as exc:
        log.warning("BGP capture failed during pre-check", device=device, error=str(exc))

    try:
        state.ospf_neighbors = _get_ospf_neighbor_states(conn, device)
        log.debug("OSPF neighbors captured", device=device, count=len(state.ospf_neighbors))
    except Exception as exc:
        log.warning("OSPF capture failed during pre-check", device=device, error=str(exc))

    try:
        state.vrrp_groups = _get_vrrp_states(conn, device)
        log.debug("VRRP groups captured", device=device, count=len(state.vrrp_groups))
    except Exception as exc:
        log.warning("VRRP capture failed during pre-check", device=device, error=str(exc))

    try:
        state.mlag_state = _get_mlag_domain_state(conn, device)
        log.debug("MLAG state captured", device=device, fields=len(state.mlag_state))
    except Exception as exc:
        log.warning("MLAG capture failed during pre-check", device=device, error=str(exc))

    try:
        state.interface_states = _get_interface_states(conn, device)
        log.debug("Interface states captured", device=device, count=len(state.interface_states))
    except Exception as exc:
        log.warning("Interface capture failed during pre-check", device=device, error=str(exc))

    try:
        state.running_config = _get_running_config(conn)
        log.debug("Running config captured", device=device, lines=state.running_config.count("\n"))
    except Exception as exc:
        log.warning("Running config capture failed", device=device, error=str(exc))

    log.info(
        "Pre-check complete",
        device=device,
        bgp_peers=len(state.bgp_peers),
        ospf_neighbors=len(state.ospf_neighbors),
        vrrp_groups=len(state.vrrp_groups),
        mlag_fields=len(state.mlag_state),
        interfaces=len(state.interface_states),
    )

    return Result(
        host=task.host,
        result={"state": state, "running_config": state.running_config},
    )


def post_check(task: Task, baseline: DeviceState | None = None) -> Result:
    """
    Capture post-change state and diff against baseline.

    Raises CheckFailure if any monitored state has regressed.
    """
    device = task.host.name
    log.info("Post-check: capturing post-change state", device=device)

    conn = task.host.get_connection("scrapli", task.nornir.config)
    post_state = DeviceState(device=device)

    try:
        post_state.bgp_peers = _get_bgp_peer_states(conn, device)
    except Exception as exc:
        log.warning("BGP capture failed during post-check", device=device, error=str(exc))

    try:
        post_state.ospf_neighbors = _get_ospf_neighbor_states(conn, device)
    except Exception as exc:
        log.warning("OSPF capture failed during post-check", device=device, error=str(exc))

    try:
        post_state.vrrp_groups = _get_vrrp_states(conn, device)
    except Exception as exc:
        log.warning("VRRP capture failed during post-check", device=device, error=str(exc))

    try:
        post_state.mlag_state = _get_mlag_domain_state(conn, device)
    except Exception as exc:
        log.warning("MLAG capture failed during post-check", device=device, error=str(exc))

    try:
        post_state.interface_states = _get_interface_states(conn, device)
    except Exception as exc:
        log.warning("Interface capture failed during post-check", device=device, error=str(exc))

    if baseline is None:
        log.info("Post-check complete — no baseline to compare", device=device)
        return Result(host=task.host, result={"state": post_state, "issues": {}})

    issues = _compare_states(baseline, post_state)

    if issues:
        log.error("Post-check regression detected", device=device, issues=issues)
        raise CheckFailure(device=device, issues=issues)

    log.info("Post-check passed — no regressions detected", device=device)
    return Result(host=task.host, result={"state": post_state, "issues": {}})


# ---------------------------------------------------------------------------
# State comparison
# ---------------------------------------------------------------------------

def _compare_states(before: DeviceState, after: DeviceState) -> dict[str, Any]:
    """Compare before/after snapshots and return only regressions."""
    issues: dict[str, Any] = {}

    # BGP — session must not drop from established
    for peer_ip, before_state in before.bgp_peers.items():
        after_state = after.bgp_peers.get(peer_ip)
        if after_state is None:
            issues[f"bgp_peer_missing_{peer_ip}"] = {
                "before": before_state, "after": "not_found"
            }
        elif _is_bgp_regression(before_state, after_state):
            issues[f"bgp_peer_down_{peer_ip}"] = {
                "before": before_state, "after": after_state
            }

    # OSPF — neighbor must not drop from full
    for neighbor_id, before_state in before.ospf_neighbors.items():
        after_state = after.ospf_neighbors.get(neighbor_id)
        if after_state is None:
            issues[f"ospf_neighbor_missing_{neighbor_id}"] = {
                "before": before_state, "after": "not_found"
            }
        elif _is_ospf_regression(before_state, after_state):
            issues[f"ospf_neighbor_down_{neighbor_id}"] = {
                "before": before_state, "after": after_state
            }

    # VRRP — group must not change state (master must stay master, backup must stay backup)
    for group_key, before_state in before.vrrp_groups.items():
        after_state = after.vrrp_groups.get(group_key)
        if after_state is None:
            vlan, grp = group_key
            issues[f"vrrp_group_missing_vlan{vlan}_grp{grp}"] = {
                "before": before_state, "after": "not_found"
            }
        elif before_state != after_state:
            vlan, grp = group_key
            issues[f"vrrp_state_changed_vlan{vlan}_grp{grp}"] = {
                "before": before_state, "after": after_state
            }

    # MLAG — domain must not degrade
    for field_name, before_val in before.mlag_state.items():
        after_val = after.mlag_state.get(field_name)
        if _is_mlag_regression(field_name, before_val, after_val):
            issues[f"mlag_{field_name}_regression"] = {
                "before": before_val, "after": after_val
            }

    # Interfaces — must not go from up to not-up
    for iface, before_oper in before.interface_states.items():
        after_oper = after.interface_states.get(iface)
        if before_oper == "up" and after_oper != "up":
            issues[f"interface_down_{iface}"] = {
                "before": before_oper, "after": after_oper
            }

    return issues


def _is_bgp_regression(before: str, after: str) -> bool:
    return before.lower() == "established" and after.lower() != "established"


def _is_ospf_regression(before: str, after: str) -> bool:
    # OSPF full state strings vary slightly by platform — check for 'full' substring
    return "full" in before.lower() and "full" not in after.lower()


def _is_mlag_regression(field: str, before: str | None, after: str | None) -> bool:
    """
    MLAG regression rules:
      state              : must stay 'active'
      negotiation_status : must stay 'connected'
      peer_link_status   : must stay 'up'
    """
    if before is None or after is None:
        return False
    healthy = {
        "state": "active",
        "negotiation_status": "connected",
        "peer_link_status": "up",
    }
    expected = healthy.get(field)
    if expected is None:
        return False
    return before.lower() == expected and after.lower() != expected


# ---------------------------------------------------------------------------
# State capture — BGP
# ---------------------------------------------------------------------------

def _get_bgp_peer_states(conn: Any, device: str) -> dict[str, str]:
    """
    IOS XE only — Genie parser for 'show bgp all summary'.
    Returns empty dict on EOS or parse failure.
    """
    response = conn.send_command("show bgp all summary")
    if response.failed or not response.result.strip():
        return {}
    try:
        from genie.libs.parser.iosxe.show_bgp import ShowBgpAllSummary  # type: ignore
        parser = ShowBgpAllSummary(device=_genie_stub(device, "iosxe"))
        parsed = parser.cli(output=response.result)
        return _extract_bgp_peers(parsed)
    except Exception as exc:
        log.debug("Genie BGP parse failed", device=device, error=str(exc))
        return {}


def _extract_bgp_peers(parsed: dict[str, Any]) -> dict[str, str]:
    peers: dict[str, str] = {}
    try:
        for vrf_data in parsed.get("vrf", {}).values():
            for peer_ip, peer_data in vrf_data.get("neighbor", {}).items():
                state = peer_data.get("session_state", "unknown")
                peers[peer_ip] = str(state).lower()
    except Exception:
        pass
    return peers


# ---------------------------------------------------------------------------
# State capture — OSPF
# ---------------------------------------------------------------------------

def _get_ospf_neighbor_states(conn: Any, device: str) -> dict[str, str]:
    """
    IOS XE: Genie parser for 'show ip ospf neighbor'.
    EOS:    device.execute() + regex (no Genie OSPF parser for EOS).

    Returns {neighbor_id: state} with state lowercased.
    Returns empty dict on failure or non-OSPF device.
    """
    response = conn.send_command("show ip ospf neighbor")
    if response.failed or not response.result.strip():
        return {}

    # Detect platform from output — EOS output contains "Instance" column header
    if "Instance" in response.result or "VRF" in response.result:
        # EOS regex: Neighbor ID  Instance  VRF  Pri  State  Dead Time  Address  Interface
        neighbors = {}
        for line in response.result.splitlines():
            match = re.match(
                r"(\d+\.\d+\.\d+\.\d+)\s+\S+\s+\S+\s+\d+\s+(\S+)", line.strip()
            )
            if match:
                neighbors[match.group(1)] = match.group(2).lower()
        return neighbors

    # IOS XE — Genie
    try:
        from genie.libs.parser.iosxe.show_ospf import ShowIpOspfNeighbor  # type: ignore
        parser = ShowIpOspfNeighbor(device=_genie_stub(device, "iosxe"))
        parsed = parser.cli(output=response.result)
        neighbors = {}
        for intf_data in parsed.get("interfaces", {}).values():
            for neighbor_id, neighbor_data in intf_data.get("neighbors", {}).items():
                state = neighbor_data.get("state", "unknown")
                neighbors[neighbor_id] = state.lower()
        return neighbors
    except Exception as exc:
        log.debug("Genie OSPF parse failed", device=device, error=str(exc))
        return {}


# ---------------------------------------------------------------------------
# State capture — VRRP
# ---------------------------------------------------------------------------

def _get_vrrp_states(conn: Any, device: str) -> dict[tuple, str]:
    """
    EOS only — device.execute() + regex for 'show vrrp'.
    Returns {(vlan_id, group_id): state} with state lowercased.
    Returns empty dict on IOS XE or failure.

    EOS output format:
        Vlan10 - Group 10
          State is Master
    """
    response = conn.send_command("show vrrp")
    if response.failed or not response.result.strip():
        return {}

    # IOS XE does not support 'show vrrp' — return empty
    if "Invalid" in response.result or "%" in response.result[:10]:
        return {}

    groups: dict[tuple, str] = {}
    current_key = None

    for line in response.result.splitlines():
        header = re.match(r"Vlan(\d+)\s+-\s+Group\s+(\d+)", line.strip())
        if header:
            current_key = (int(header.group(1)), int(header.group(2)))
            continue

        if current_key is None:
            continue

        state_match = re.match(r"State is (\S+)", line.strip())
        if state_match:
            groups[current_key] = state_match.group(1).lower()
            current_key = None  # each group has one state line — move on

    return groups


# ---------------------------------------------------------------------------
# State capture — MLAG
# ---------------------------------------------------------------------------

def _get_mlag_domain_state(conn: Any, device: str) -> dict[str, str]:
    """
    EOS only — device.execute() + regex for 'show mlag'.
    Returns {state, negotiation_status, peer_link_status} lowercased.
    Returns empty dict on IOS XE or failure.
    """
    response = conn.send_command("show mlag")
    if response.failed or not response.result.strip():
        return {}

    # IOS XE does not support 'show mlag'
    if "Invalid" in response.result or "%" in response.result[:10]:
        return {}

    result = {}
    patterns = {
        "state":              r"^state\s*:\s*(\S+)",
        "negotiation_status": r"^negotiation status\s*:\s*(\S+)",
        "peer_link_status":   r"^peer-link status\s*:\s*(\S+)",
    }
    for line in response.result.splitlines():
        for key, pattern in patterns.items():
            match = re.match(pattern, line.strip(), re.IGNORECASE)
            if match:
                result[key] = match.group(1).lower()

    return result


# ---------------------------------------------------------------------------
# State capture — Interfaces
# ---------------------------------------------------------------------------

def _get_interface_states(conn: Any, device: str) -> dict[str, str]:
    """
    IOS XE: Genie parser for 'show interfaces'.
    EOS:    Genie parser with regex fallback.
    """
    response = conn.send_command("show interfaces")
    if response.failed or not response.result.strip():
        return {}

    # Try Genie first (works on both platforms when parser is available)
    try:
        from genie.libs.parser.iosxe.show_interface import ShowInterfaces  # type: ignore
        parser = ShowInterfaces(device=_genie_stub(device, "iosxe"))
        parsed = parser.cli(output=response.result)
        return _extract_interface_states(parsed)
    except Exception:
        pass

    # Regex fallback — covers EOS and any Genie parse failure
    ifaces: dict[str, str] = {}
    for line in response.result.splitlines():
        match = re.match(
            r"^(\S+)\s+is\s+(up|down|administratively down)", line.strip()
        )
        if match:
            ifaces[match.group(1)] = match.group(2).lower()
    return ifaces


def _extract_interface_states(parsed: dict[str, Any]) -> dict[str, str]:
    ifaces: dict[str, str] = {}
    try:
        for iface_name, iface_data in parsed.items():
            oper = iface_data.get("oper_status", "unknown")
            ifaces[iface_name] = str(oper).lower()
    except Exception:
        pass
    return ifaces


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_running_config(conn: Any) -> str:
    response = conn.send_command("show running-config")
    return response.result if not response.failed else ""


def _genie_stub(hostname: str, os: str = "iosxe") -> Any:
    """Minimal Genie device stub for offline CLI parsing."""
    from pyats.topology import loader  # type: ignore
    testbed_yaml = f"""
devices:
  {hostname}:
    os: {os}
    type: router
    connections: {{}}
"""
    testbed = loader.load(testbed_yaml)
    return testbed.devices[hostname]