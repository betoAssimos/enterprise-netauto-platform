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
# Usage:
#   pyats run job tests/precheck/test_bgp.py --testbed tests/testbed.yaml
#
# Expected BGP topology:
#   rtr-01 (AS 65001) <-> rtr-02 (AS 65002)

from pyats import aetest
from pyats.easypy import run


# ---------------------------------------------------------------------------
# Jobfile entry point — required by pyats run job
# ---------------------------------------------------------------------------

def main(runtime):
    run(testscript=__file__, runtime=runtime)


# ---------------------------------------------------------------------------
# Test parameters — matches hosts.yaml and testbed.yaml
# ---------------------------------------------------------------------------

BGP_EXPECTED = {
    "rtr-01": {
        "local_as": 65001,
        "neighbors": {
            "10.0.0.2": {"remote_as": 65002, "description": "rtr02"},
        },
    },
    "rtr-02": {
        "local_as": 65002,
        "neighbors": {
            "10.0.0.1": {"remote_as": 65001, "description": "rtr01"},
        },
    },
}


# ---------------------------------------------------------------------------
# Common Setup — connect to devices
# ---------------------------------------------------------------------------

class CommonSetup(aetest.CommonSetup):

    @aetest.subsection
    def connect_to_devices(self, testbed):
        for device_name in BGP_EXPECTED:
            device = testbed.devices[device_name]
            device.connect(log_stdout=False)


# ---------------------------------------------------------------------------
# BGP Baseline State Test
# ---------------------------------------------------------------------------

class TestBGPBaseline(aetest.Testcase):

    @aetest.setup
    def setup(self, testbed):
        self.testbed = testbed

    @aetest.test
    def test_bgp_neighbors_present(self):
        """Assert all expected BGP neighbors exist in the BGP table."""
        failures = []
        for device_name, expected in BGP_EXPECTED.items():
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
        for device_name, expected in BGP_EXPECTED.items():
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
        for device_name, expected in BGP_EXPECTED.items():
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
        for device_name, expected in BGP_EXPECTED.items():
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
# Common Cleanup — disconnect from devices
# ---------------------------------------------------------------------------

class CommonCleanup(aetest.CommonCleanup):

    @aetest.subsection
    def disconnect_from_devices(self, testbed):
        for device_name in BGP_EXPECTED:
            device = testbed.devices[device_name]
            if device.is_connected():
                device.disconnect()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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