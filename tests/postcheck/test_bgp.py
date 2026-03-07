# tests/postcheck/test_bgp.py
#
# pyATS post-deployment BGP validation test.
#
# Verifies that BGP neighbors are Established after a BGP deploy.
# Targets rtr-01 and rtr-02 only (Arista devices have no BGP configured).
#
# Usage:
#   pyats run job tests/postcheck/test_bgp.py --testbed tests/testbed.yaml
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
# BGP Neighbor State Test
# ---------------------------------------------------------------------------

class TestBGPNeighborState(aetest.Testcase):

    @aetest.setup
    def setup(self, testbed):
        self.testbed = testbed

    @aetest.test
    def test_bgp_neighbors_established(self):
        """Assert all expected BGP neighbors are in Established state."""
        failures = []
        for device_name, expected in BGP_EXPECTED.items():
            device = self.testbed.devices[device_name]
            parsed = device.parse("show bgp all summary")
            neighbors = _extract_neighbors(parsed)

            for neighbor_ip in expected["neighbors"]:
                if neighbor_ip not in neighbors:
                    failures.append(
                        f"{device_name}: neighbor {neighbor_ip} not found in BGP table"
                    )
                    continue
                state = neighbors[neighbor_ip].get("session_state", "unknown")
                if state.lower() != "established":
                    failures.append(
                        f"{device_name}: neighbor {neighbor_ip} state is '{state}', "
                        f"expected 'established'"
                    )

        if failures:
            self.failed("\n".join(failures))

    @aetest.test
    def test_bgp_remote_as(self):
        """Assert all expected BGP neighbors have the correct remote AS."""
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
                        f"expected '{neighbor_cfg['remote_as']}'"
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
    a simple {neighbor_ip: {as, session_state}} dict across all VRFs.

    Genie nests neighbor data under address_family. We take the first
    address family found per neighbor. session_state is derived from
    state_pfxrcd: a numeric value means Established, a string means not.
    """
    neighbors = {}
    try:
        for vrf_data in parsed.get("vrf", {}).values():
            for peer_ip, peer_data in vrf_data.get("neighbor", {}).items():
                af_data = next(iter(peer_data.get("address_family", {}).values()), {})
                state_pfxrcd = str(af_data.get("state_pfxrcd", "unknown"))
                session_state = "established" if state_pfxrcd.isdigit() else state_pfxrcd.lower()
                neighbors[peer_ip] = {
                    "as": af_data.get("as"),
                    "session_state": session_state,
                }
    except Exception:
        pass
    return neighbors