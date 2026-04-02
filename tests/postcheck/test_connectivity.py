# tests/postcheck/test_connectivity.py
#
# pyATS post-deployment connectivity validation.
#
# Verifies end-to-end data plane reachability across VLANs and toward
# the internet simulation host. Runs after every deployment and as part
# of the remediation pipeline.
#
# Tests:
#   - VLAN 10 → VLAN 20 (inter-VLAN routing via core switches)
#   - VLAN 20 → VLAN 10
#   - VLAN 10 → inet-host (NAT + routing)
#   - VLAN 10 → VLAN 20 (cross-access-switch)
#
# Uses docker exec ping from containerlab host containers.
# Requires the GitLab runner to have access to the Docker socket.
#
# Usage:
#   pyats run job tests/postcheck/test_connectivity.py --testbed tests/testbed.yaml

import subprocess
from pyats import aetest
from pyats.easypy import run


# ---------------------------------------------------------------------------
# Jobfile entry point
# ---------------------------------------------------------------------------

def main(runtime):
    run(testscript=__file__, runtime=runtime)


# ---------------------------------------------------------------------------
# Test parameters
# ---------------------------------------------------------------------------

PING_TESTS = [
    {
        "name": "host01_to_host02",
        "description": "VLAN10 → VLAN20 inter-VLAN routing",
        "container": "clab-enterprise-netauto-lab-host-01",
        "target": "10.20.20.10",
    },
    {
        "name": "host02_to_host01",
        "description": "VLAN20 → VLAN10 inter-VLAN routing",
        "container": "clab-enterprise-netauto-lab-host-02",
        "target": "10.10.10.10",
    },
    {
        "name": "host01_to_inet",
        "description": "VLAN10 → inet-host via NAT",
        "container": "clab-enterprise-netauto-lab-host-01",
        "target": "203.0.113.1",
    },
    {
        "name": "host03_to_host04",
        "description": "VLAN10 → VLAN20 cross-access-switch",
        "container": "clab-enterprise-netauto-lab-host-03",
        "target": "10.20.20.20",
    },
]


# ---------------------------------------------------------------------------
# Common Setup
# ---------------------------------------------------------------------------

class CommonSetup(aetest.CommonSetup):

    @aetest.subsection
    def verify_docker_available(self):
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.failed(
                "Docker is not available — connectivity tests require "
                "Docker socket access on the runner"
            )


# ---------------------------------------------------------------------------
# Connectivity Tests
# ---------------------------------------------------------------------------

class TestConnectivity(aetest.Testcase):

    @aetest.test
    def test_host01_to_host02(self):
        """VLAN10 → VLAN20 inter-VLAN routing via core switches."""
        _ping_assert(
            self,
            container="clab-enterprise-netauto-lab-host-01",
            target="10.20.20.10",
            description="host-01 (VLAN10) → host-02 (VLAN20)",
        )

    @aetest.test
    def test_host02_to_host01(self):
        """VLAN20 → VLAN10 inter-VLAN routing via core switches."""
        _ping_assert(
            self,
            container="clab-enterprise-netauto-lab-host-02",
            target="10.10.10.10",
            description="host-02 (VLAN20) → host-01 (VLAN10)",
        )

    @aetest.test
    def test_host01_to_inet(self):
        """VLAN10 → inet-host via NAT on edge routers."""
        _ping_assert(
            self,
            container="clab-enterprise-netauto-lab-host-01",
            target="203.0.113.1",
            description="host-01 (VLAN10) → inet-host (203.0.113.1)",
        )

    @aetest.test
    def test_host03_to_host04(self):
        """Cross-access-switch VLAN10 → VLAN20 reachability."""
        _ping_assert(
            self,
            container="clab-enterprise-netauto-lab-host-03",
            target="10.20.20.20",
            description="host-03 (VLAN10) → host-04 (VLAN20)",
        )


# ---------------------------------------------------------------------------
# Common Cleanup
# ---------------------------------------------------------------------------

class CommonCleanup(aetest.CommonCleanup):

    @aetest.subsection
    def done(self):
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ping_assert(testcase, container: str, target: str, description: str):
    """
    Run ping from a containerlab host container via docker exec.
    Fails the testcase with a clear message if ping returns non-zero.
    """
    result = subprocess.run(
        [
            "docker", "exec", container,
            "ping", "-c", "3", "-W", "2", target,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        testcase.failed(
            f"CONNECTIVITY FAIL: {description}\n"
            f"Container: {container}\n"
            f"Target: {target}\n"
            f"Output: {result.stdout}"
        )