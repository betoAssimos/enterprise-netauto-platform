# tests/precheck/test_ospf.py
#
# pyATS pre-deployment OSPF baseline test.
#
# Captures OSPF neighbor state BEFORE any automation change is applied.
# If neighbors are not FULL, routing is already broken — deploy should not proceed.
#
# Check:
#   - All expected OSPF neighbors are in FULL state
#
# Devices under test: derived from inventory (roles: edge-router, core-switch)
# No device names hardcoded — inventory is the single source of truth.
#
# Parser strategy:
#   IOS XE — Genie parser for 'show ip ospf neighbor'
#   EOS     — device.execute() + regex (no Genie OSPF parser for EOS)
#
# Usage:
#   pyats run job tests/precheck/test_ospf.py --testbed tests/testbed.yaml

from pyats import aetest
from pyats.easypy import run
from pathlib import Path
from dotenv import load_dotenv
from nornir import InitNornir
import os
import re

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


def _get_ospf_device_names(nr) -> list:
    """Derive OSPF-participating device names from inventory by role."""
    ospf_hosts = nr.filter(
        filter_func=lambda h: h.data.get("role") in ("edge-router", "core-switch")
    )
    return list(ospf_hosts.inventory.hosts.keys())


def _build_intent_from_inventory(nr) -> dict:
    """
    Derive expected OSPF neighbors from inventory.
    Reuses ospf_intent_builder — same data, subset of checks.
    """
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from automation.workflows.routing.ospf_intent_builder import build_ospf_intent

    intent = {}
    ospf_hosts = nr.filter(
        filter_func=lambda h: h.data.get("role") in ("edge-router", "core-switch")
    )
    for host_name, host in ospf_hosts.inventory.hosts.items():

        class _FakeTask:
            def __init__(self, h):
                self.host = h

        intent[host_name] = build_ospf_intent(_FakeTask(host))

    return intent


def _get_neighbor_states(device) -> dict:
    """
    Return OSPF neighbor states keyed by neighbor router-ID.
    IOS XE: Genie. EOS: execute() + regex.
    """
    try:
        if device.os == "iosxe":
            parsed = device.parse("show ip ospf neighbor")
            neighbors = {}
            for intf_data in parsed.get("interfaces", {}).values():
                for neighbor_id, neighbor_data in intf_data.get("neighbors", {}).items():
                    state = neighbor_data.get("state", "")
                    neighbors[neighbor_id] = state.lower()
            return neighbors
        else:
            output = device.execute("show ip ospf neighbor")
            neighbors = {}
            for line in output.splitlines():
                match = re.match(
                    r"(\d+\.\d+\.\d+\.\d+)\s+\S+\s+\S+\s+\d+\s+(\S+)", line
                )
                if match:
                    neighbors[match.group(1)] = match.group(2).lower()
            return neighbors
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Common Setup
# ---------------------------------------------------------------------------

class CommonSetup(aetest.CommonSetup):

    @aetest.subsection
    def build_intent(self):
        nr = _init_nornir()
        self.parent.parameters["intent"] = _build_intent_from_inventory(nr)
        self.parent.parameters["ospf_device_names"] = _get_ospf_device_names(nr)

    @aetest.subsection
    def connect_to_devices(self, testbed, ospf_device_names):
        for device_name in ospf_device_names:
            device = testbed.devices[device_name]
            device.credentials.default.username = os.environ.get("DEVICE_USERNAME")
            device.credentials.default.password = os.environ.get("DEVICE_PASSWORD")
            device.connect(log_stdout=False, timeout=60)


# ---------------------------------------------------------------------------
# OSPF Baseline Test
# ---------------------------------------------------------------------------

class TestOSPFBaseline(aetest.Testcase):

    @aetest.setup
    def setup(self, testbed, intent):
        self.testbed = testbed
        self.intent = intent

    @aetest.test
    def test_ospf_neighbors_full(self):
        """
        Assert all expected OSPF neighbors are in FULL state before deployment.
        If any neighbor is not FULL, routing is already broken.
        """
        failures = []

        for device_name, device_intent in self.intent.items():
            device = self.testbed.devices[device_name]
            observed = _get_neighbor_states(device)

            for expected in device_intent["expected_neighbors"]:
                neighbor_id = expected["neighbor_id"]
                expected_state = expected["expected_state"].lower()

                if neighbor_id not in observed:
                    failures.append(
                        f"{device_name}: neighbor {neighbor_id} not found "
                        f"— OSPF may not be running"
                    )
                    continue

                actual_state = observed[neighbor_id]
                if expected_state not in actual_state:
                    failures.append(
                        f"{device_name}: neighbor {neighbor_id} state is "
                        f"'{actual_state}', expected '{expected_state}' "
                        f"— deploy blocked, fix OSPF first"
                    )

        if failures:
            self.failed("\n".join(failures))


# ---------------------------------------------------------------------------
# Common Cleanup
# ---------------------------------------------------------------------------

class CommonCleanup(aetest.CommonCleanup):

    @aetest.subsection
    def disconnect_from_devices(self, testbed, ospf_device_names):
        for device_name in ospf_device_names:
            device = testbed.devices[device_name]
            if device.is_connected():
                device.disconnect()