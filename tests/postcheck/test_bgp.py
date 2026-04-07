# tests/precheck/test_bgp.py
#
# pyATS pre-deployment BGP baseline test.
#
# Captures and validates BGP state BEFORE any automation change is applied.
# If this test fails, the deploy should not proceed — the network is already
# unhealthy and automation would be making a bad situation worse.
#
# Checks:
#   - BGP neighbors are present and Established
#   - Remote AS matches expected topology
#   - Prefix count is non-zero (routing table is populated)
#
# Devices under test: derived from inventory (role: edge-router)
# No device names hardcoded — inventory is the single source of truth.
#
# Usage:
#   pyats run job tests/precheck/test_bgp.py --testbed tests/testbed.yaml

from pyats import aetest
from pyats.easypy import run
from pathlib import Path
from dotenv import load_dotenv
from nornir import InitNornir
import os

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=BASE_DIR / ".env")


# ---------------------------------------------------------------------------
# Jobfile entry point
# ---------------------------------------------------------------------------

def main(runtime):
    run(testscript=__file__, runtime=runtime)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_nornir() -> object:
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


def _get_bgp_device_names(nr) -> list:
    """Derive edge router names from inventory by role."""
    edge_routers = nr.filter(
        filter_func=lambda h: h.data.get("role") == "edge-router"
    )
    return list(edge_routers.inventory.hosts.keys())


def _build_bgp_expected(nr) -> dict:
    """
    Derive BGP neighbor expectations from inventory.

    Returns:
        {
            "rtr-01": {
                "neighbors": {
                    "10.0.0.2": {"remote_as": 65002}
                }
            },
            ...
        }
    """
    expected = {}
    edge_routers = nr.filter(
        filter_func=lambda h: h.data.get("role") == "edge-router"
    )
    for host_name, host in edge_routers.inventory.hosts.items():
        cf = host.data.get("custom_fields", {})
        neighbors = {}
        for neighbor in cf.get("bgp_neighbors", []):
            ip = neighbor.get("ip")
            remote_as = neighbor.get("remote_as")
            if ip and remote_as:
                neighbors[ip] = {"remote_as": remote_as}
        expected[host_name] = {"neighbors": neighbors}

    return expected


def _extract_neighbors(parsed: dict) -> dict:
    """
    Flatten Genie parsed output of 'show bgp all summary' into
    a simple {neighbor_ip: {as, session_state, prefix_count}} dict.

    session_state is derived from state_pfxrcd:
        numeric value  -> established (value is the prefix count)
        string value   -> not established (value is the state name)
    """
    neighbors = {}
    try:
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
                neighbors[peer_ip] = {
                    "as": af_data.get("as"),
                    "session_state": session_state,
                    "prefix_count": prefix_count,
                }
    except Exception:
        pass
    return neighbors


# ---------------------------------------------------------------------------
# Common Setup
# ---------------------------------------------------------------------------

class CommonSetup(aetest.CommonSetup):

    @aetest.subsection
    def build_expected(self):
        nr = _init_nornir()
        self.parent.parameters["bgp_expected"] = _build_bgp_expected(nr)
        self.parent.parameters["bgp_device_names"] = _get_bgp_device_names(nr)

    @aetest.subsection
    def connect_to_devices(self, testbed, bgp_device_names):
        for device_name in bgp_device_names:
            device = testbed.devices[device_name]
            device.credentials.default.username = os.environ.get("DEVICE_USERNAME")
            device.credentials.default.password = os.environ.get("DEVICE_PASSWORD")
            device.connect(log_stdout=False, timeout=60)


# ---------------------------------------------------------------------------
# BGP Baseline State Test
# ---------------------------------------------------------------------------

class TestBGPBaseline(aetest.Testcase):

    @aetest.setup
    def setup(self, testbed, bgp_expected):
        self.testbed = testbed
        self.bgp_expected = bgp_expected

    @aetest.test
    def test_bgp_neighbors_present(self):
        """Assert all expected BGP neighbors exist in the BGP table."""
        failures = []
        for device_name, expected in self.bgp_expected.items():
            device = self.testbed.devices[device_name]
            parsed = device.parse("show bgp all summary")
            neighbors = _extract_neighbors(parsed)

            for neighbor_ip in expected["neighbors"]:
                if neighbor_ip not in neighbors:
                    failures.append(
                        f"{device_name}: neighbor {neighbor_ip} not found — "
                        f"network may not be ready for deployment"
                    )

        if failures:
            self.failed("\n".join(failures))

    @aetest.test
    def test_bgp_neighbors_established(self):
        """Assert all expected BGP neighbors are Established before deployment."""
        failures = []
        for device_name, expected in self.bgp_expected.items():
            device = self.testbed.devices[device_name]
            parsed = device.parse("show bgp all summary")
            neighbors = _extract_neighbors(parsed)

            for neighbor_ip in expected["neighbors"]:
                if neighbor_ip not in neighbors:
                    failures.append(
                        f"{device_name}: neighbor {neighbor_ip} missing"
                    )
                    continue
                state = neighbors[neighbor_ip].get("session_state", "unknown")
                if state.lower() != "established":
                    failures.append(
                        f"{device_name}: neighbor {neighbor_ip} state is '{state}' "
                        f"— deployment blocked, fix BGP first"
                    )

        if failures:
            self.failed("\n".join(failures))

    @aetest.test
    def test_bgp_remote_as(self):
        """Assert remote AS matches expected topology before deployment."""
        failures = []
        for device_name, expected in self.bgp_expected.items():
            device = self.testbed.devices[device_name]
            parsed = device.parse("show bgp all summary")
            neighbors = _extract_neighbors(parsed)

            for neighbor_ip, neighbor_cfg in expected["neighbors"].items():
                if neighbor_ip not in neighbors:
                    self.skipped(
                        f"{device_name}: neighbor {neighbor_ip} not found, skipping AS check"
                    )
                    continue
                actual_as = neighbors[neighbor_ip].get("as", None)
                if str(actual_as) != str(neighbor_cfg["remote_as"]):
                    failures.append(
                        f"{device_name}: neighbor {neighbor_ip} remote AS is '{actual_as}', "
                        f"expected '{neighbor_cfg['remote_as']}' — topology mismatch"
                    )

        if failures:
            self.failed("\n".join(failures))

    @aetest.test
    def test_bgp_prefix_count(self):
        """Assert BGP prefix count is non-zero — routing table must be populated."""
        failures = []
        for device_name, expected in self.bgp_expected.items():
            device = self.testbed.devices[device_name]
            parsed = device.parse("show bgp all summary")
            neighbors = _extract_neighbors(parsed)

            for neighbor_ip in expected["neighbors"]:
                if neighbor_ip not in neighbors:
                    continue
                prefix_count = neighbors[neighbor_ip].get("prefix_count", 0)
                if prefix_count == 0:
                    failures.append(
                        f"{device_name}: neighbor {neighbor_ip} has 0 prefixes "
                        f"— routing table may be empty"
                    )

        if failures:
            self.failed("\n".join(failures))


# ---------------------------------------------------------------------------
# Common Cleanup
# ---------------------------------------------------------------------------

class CommonCleanup(aetest.CommonCleanup):

    @aetest.subsection
    def disconnect_from_devices(self, testbed, bgp_device_names):
        for device_name in bgp_device_names:
            device = testbed.devices[device_name]
            if device.is_connected():
                device.disconnect()