"""
automation/validators/checks.py

pyATS / Genie pre-check and post-check Nornir tasks.

pre_check  — captures device state baseline before any change.
post_check — re-captures state after change, diffs against baseline,
             raises CheckFailure on any regression.

Design:
- Captures BGP session states and interface oper-status
- Diff is structured, not line-by-line string comparison
- Only regressions raise — improvements are logged and ignored
- Genie parsers used for structured output
- All captured state returned in Result for archival
"""

from __future__ import annotations

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
    interface_states: dict[str, str] = field(default_factory=dict)
    running_config: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "bgp_peers": self.bgp_peers,
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


def _compare_states(before: DeviceState, after: DeviceState) -> dict[str, Any]:
    """Compare before/after and return only regressions."""
    issues: dict[str, Any] = {}

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

    for iface, before_oper in before.interface_states.items():
        after_oper = after.interface_states.get(iface)
        if before_oper == "up" and after_oper != "up":
            issues[f"interface_down_{iface}"] = {
                "before": before_oper, "after": after_oper
            }

    return issues


def _is_bgp_regression(before: str, after: str) -> bool:
    healthy = {"established"}
    return before.lower() in healthy and after.lower() not in healthy


def _get_bgp_peer_states(conn: Any, device: str) -> dict[str, str]:
    response = conn.send_command("show bgp all summary")
    if response.failed or not response.result.strip():
        return {}
    try:
        from genie.libs.parser.iosxe.show_bgp import ShowBgpAllSummary  # type: ignore
        parser = ShowBgpAllSummary(device=_genie_stub(device))
        parsed = parser.cli(output=response.result)
        return _extract_bgp_peers(parsed)
    except Exception as exc:
        log.debug("Genie BGP parse failed", device=device, error=str(exc))
        return {}


def _get_interface_states(conn: Any, device: str) -> dict[str, str]:
    response = conn.send_command("show interfaces")
    if response.failed or not response.result.strip():
        return {}
    try:
        from genie.libs.parser.iosxe.show_interface import ShowInterfaces  # type: ignore
        parser = ShowInterfaces(device=_genie_stub(device))
        parsed = parser.cli(output=response.result)
        return _extract_interface_states(parsed)
    except Exception as exc:
        log.debug("Genie interface parse failed", device=device, error=str(exc))
        return {}


def _get_running_config(conn: Any) -> str:
    response = conn.send_command("show running-config")
    return response.result if not response.failed else ""


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


def _extract_interface_states(parsed: dict[str, Any]) -> dict[str, str]:
    ifaces: dict[str, str] = {}
    try:
        for iface_name, iface_data in parsed.items():
            oper = iface_data.get("oper_status", "unknown")
            ifaces[iface_name] = str(oper).lower()
    except Exception:
        pass
    return ifaces


def _genie_stub(hostname: str) -> Any:
    """Minimal Genie device stub for offline CLI parsing."""
    from pyats.topology import loader  # type: ignore
    testbed_yaml = f"""
devices:
  {hostname}:
    os: iosxe
    type: router
    connections: {{}}
"""
    testbed = loader.load(testbed_yaml)
    return testbed.devices[hostname]