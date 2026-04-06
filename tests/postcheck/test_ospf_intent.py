# tests/postcheck/test_ospf_intent.py
#
# pyATS post-deployment OSPF intent validation test.
#
# Two checks per device:
#   1. Neighbor state — each expected neighbor is in FULL state
#   2. Route presence — each neighbor's router-ID (/32) appears in the
#      local OSPF routing table, confirming full topology convergence
#
# Devices under test: derived from inventory (roles: edge-router, core-switch)
# No device names are hardcoded — inventory is the single source of truth.
#
# Parser strategy:
#   IOS XE — Genie parsers for both neighbor state and route table
#   EOS     — Genie has no OSPF parsers; device.execute() + regex used instead
#
# Usage:
#   pyats run job tests/postcheck/test_ospf_intent.py --testbed tests/testbed.yaml

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
    """
    Derive the list of OSPF-participating device names from inventory.
    Filters by role — no device names hardcoded.
    """
    ospf_hosts = nr.filter(
        filter_func=lambda h: h.data.get("role") in ("edge-router", "core-switch")
    )
    return list(ospf_hosts.inventory.hosts.keys())


def _build_intent_from_inventory(nr) -> dict:
    """
    Derive OSPF intent for all OSPF-participating devices.

    Returns:
        {
            "rtr-01": {"expected_neighbors": [...], "expected_routes": [...]},
            ...
        }
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

    IOS XE: Genie parser for 'show ip ospf neighbor'
    EOS:    device.execute() + regex (no Genie OSPF parser available for EOS)

    State strings are lowercased. Returns empty dict on failure.
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
            # EOS: parse raw output
            # Column layout: Neighbor ID  Instance  VRF  Pri  State  Dead Time  Address  Interface
            output = device.execute("show ip ospf neighbor")
            neighbors = {}
            for line in output.splitlines():
                # Match lines starting with an IP (neighbor ID)
                match = re.match(
                    r"(\d+\.\d+\.\d+\.\d+)\s+\S+\s+\S+\s+\d+\s+(\S+)", line
                )
                if match:
                    neighbor_id = match.group(1)
                    state = match.group(2).lower()
                    neighbors[neighbor_id] = state
            return neighbors

    except Exception:
        return {}


def _get_ospf_routes(device) -> set:
    """
    Return the set of prefixes learned via OSPF in the local RIB.

    IOS XE: Genie parser for 'show ip route ospf'
    EOS:    device.execute() + regex (no Genie OSPF route parser for EOS)

    Returns empty set on failure.
    """
    try:
        if device.os == "iosxe":
            parsed = device.parse("show ip route ospf")
            routes = (
                parsed
                .get("vrf", {})
                .get("default", {})
                .get("address_family", {})
                .get("ipv4", {})
                .get("routes", {})
            )
            return set(routes.keys())

        else:
            # EOS: parse raw output
            # OSPF routes are marked with leading ' O ' in 'show ip route ospf'
            output = device.execute("show ip route ospf")
            routes = set()
            for line in output.splitlines():
                match = re.match(r"\s+O\s+(\d+\.\d+\.\d+\.\d+/\d+)", line)
                if match:
                    routes.add(match.group(1))
            return routes

    except Exception:
        return set()


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
# Test 1 — Neighbor State
# ---------------------------------------------------------------------------

class TestOSPFNeighborState(aetest.Testcase):

    @aetest.setup
    def setup(self, testbed, intent):
        self.testbed = testbed
        self.intent = intent

    @aetest.test
    def test_neighbor_state_full(self):
        """
        Assert that every expected OSPF neighbor is in FULL state.

        Fails if:
          - An expected neighbor is missing from the neighbor table
          - An expected neighbor is present but not in FULL state
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
                        f"{device_name}: neighbor {neighbor_id} not found in neighbor table"
                    )
                    continue

                actual_state = observed[neighbor_id]
                if expected_state not in actual_state:
                    failures.append(
                        f"{device_name}: neighbor {neighbor_id} state is "
                        f"'{actual_state}', expected '{expected_state}'"
                    )

        if failures:
            self.failed("\n".join(failures))


# ---------------------------------------------------------------------------
# Test 2 — Route Presence
# ---------------------------------------------------------------------------

class TestOSPFRoutePresence(aetest.Testcase):

    @aetest.setup
    def setup(self, testbed, intent):
        self.testbed = testbed
        self.intent = intent

    @aetest.test
    def test_neighbor_loopbacks_in_ospf_rib(self):
        """
        Assert that each neighbor's router-ID (/32) appears in the local
        OSPF routing table, confirming full topology convergence.

        Neighbors with ospf_route_expected: false are excluded — their
        loopbacks arrive via a lower-AD protocol and will not appear
        in the OSPF RIB.

        Fails if any expected /32 is absent from the OSPF RIB.
        """
        failures = []

        for device_name, device_intent in self.intent.items():
            device = self.testbed.devices[device_name]
            ospf_routes = _get_ospf_routes(device)

            for prefix in device_intent["expected_routes"]:
                if prefix not in ospf_routes:
                    failures.append(
                        f"{device_name}: expected OSPF route {prefix} not in RIB"
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