# tests/postcheck/test_mlag_intent.py
#
# pyATS post-deployment MLAG intent validation test.
#
# Two checks per device:
#   1. Domain state — Active, negotiation Connected, peer-link Up
#   2. Interface state — each MLAG port-channel in active-full state
#
# Devices under test: derived from inventory (role: core-switch)
# No device names are hardcoded — inventory is the single source of truth.
#
# Parser strategy:
#   EOS: no Genie MLAG parser available — device.execute() + regex
#
# Usage:
#   pyats run job tests/postcheck/test_mlag_intent.py --testbed tests/testbed.yaml

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


def _get_mlag_device_names(nr) -> list:
    """
    Derive MLAG device names from inventory by role.
    Only core-switches run MLAG in this topology.
    """
    hosts = nr.filter(
        filter_func=lambda h: h.data.get("role") == "core-switch"
    )
    return list(hosts.inventory.hosts.keys())


def _build_intent_from_inventory(nr) -> dict:
    """
    Derive MLAG intent for all core switches.

    Returns:
        {
            "core-sw-01": {
                "expected_domain": {...},
                "expected_mlag_interfaces": [...]
            },
            ...
        }
    """
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from automation.workflows.switching.mlag_intent_builder import build_mlag_intent

    intent = {}
    mlag_hosts = nr.filter(
        filter_func=lambda h: h.data.get("role") == "core-switch"
    )

    for host_name, host in mlag_hosts.inventory.hosts.items():

        class _FakeTask:
            def __init__(self, h):
                self.host = h

        intent[host_name] = build_mlag_intent(_FakeTask(host))

    return intent


def _get_mlag_domain_state(device) -> dict:
    """
    Parse MLAG domain state from 'show mlag' via regex.

    Returns:
        {
            "state": "active",
            "negotiation_status": "connected",
            "peer_link_status": "up"
        }

    All values lowercased. Returns empty dict on failure.
    """
    try:
        output = device.execute("show mlag")
        result = {}

        patterns = {
            "state": r"^state\s*:\s*(\S+)",
            "negotiation_status": r"^negotiation status\s*:\s*(\S+)",
            "peer_link_status": r"^peer-link status\s*:\s*(\S+)",
        }

        for line in output.splitlines():
            for key, pattern in patterns.items():
                match = re.match(pattern, line.strip(), re.IGNORECASE)
                if match:
                    result[key] = match.group(1).lower()

        return result

    except Exception:
        return {}


def _get_mlag_interface_states(device) -> dict:
    """
    Parse MLAG interface states from 'show mlag interfaces' via regex.

    Returns:
        {
            10: "active-full",
            20: "active-full"
        }

    Keyed by mlag_id (int). State is lowercased.
    Returns empty dict on failure.
    """
    try:
        output = device.execute("show mlag interfaces")
        interfaces = {}

        for line in output.splitlines():
            # Column layout: mlag_id  desc  state  local  remote  status
            # Example: "     10       MLAG to arista-01       active-full  ..."
            match = re.match(r"\s+(\d+)\s+\S.*?\s{2,}(\S+)\s+\S+\s+\S+\s+\S+", line)
            if match:
                mlag_id = int(match.group(1))
                state = match.group(2).lower()
                interfaces[mlag_id] = state

        return interfaces

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
        self.parent.parameters["mlag_device_names"] = _get_mlag_device_names(nr)

    @aetest.subsection
    def connect_to_devices(self, testbed, mlag_device_names):
        for device_name in mlag_device_names:
            device = testbed.devices[device_name]
            device.credentials.default.username = os.environ.get("DEVICE_USERNAME")
            device.credentials.default.password = os.environ.get("DEVICE_PASSWORD")
            device.connect(log_stdout=False, timeout=60)


# ---------------------------------------------------------------------------
# Test 1 — MLAG Domain State
# ---------------------------------------------------------------------------

class TestMLAGDomainState(aetest.Testcase):

    @aetest.setup
    def setup(self, testbed, intent):
        self.testbed = testbed
        self.intent = intent

    @aetest.test
    def test_mlag_domain_state(self):
        """
        Assert that the MLAG domain is Active, negotiation is Connected,
        and the peer-link is Up.

        Fails if any of the three domain state fields do not match intent.
        """
        failures = []

        for device_name, device_intent in self.intent.items():
            expected_domain = device_intent.get("expected_domain")
            if not expected_domain:
                continue

            device = self.testbed.devices[device_name]
            observed = _get_mlag_domain_state(device)

            checks = [
                ("state", expected_domain["expected_state"].lower()),
                ("negotiation_status", expected_domain["expected_negotiation_status"].lower()),
                ("peer_link_status", expected_domain["expected_peer_link_status"].lower()),
            ]

            for field, expected_value in checks:
                actual = observed.get(field, "")
                if actual != expected_value:
                    failures.append(
                        f"{device_name}: MLAG {field} is '{actual}', "
                        f"expected '{expected_value}'"
                    )

        if failures:
            self.failed("\n".join(failures))


# ---------------------------------------------------------------------------
# Test 2 — MLAG Interface State
# ---------------------------------------------------------------------------

class TestMLAGInterfaceState(aetest.Testcase):

    @aetest.setup
    def setup(self, testbed, intent):
        self.testbed = testbed
        self.intent = intent

    @aetest.test
    def test_mlag_interfaces_active_full(self):
        """
        Assert that each expected MLAG port-channel is in active-full state.

        Fails if:
          - An expected MLAG interface is missing from the device output
          - An interface is present but not in active-full state
        """
        failures = []

        for device_name, device_intent in self.intent.items():
            expected_interfaces = device_intent.get("expected_mlag_interfaces", [])
            if not expected_interfaces:
                continue

            device = self.testbed.devices[device_name]
            observed = _get_mlag_interface_states(device)

            for expected in expected_interfaces:
                mlag_id = expected["mlag_id"]
                expected_state = expected["expected_state"].lower()

                if mlag_id not in observed:
                    failures.append(
                        f"{device_name}: MLAG interface {mlag_id} not found"
                    )
                    continue

                actual_state = observed[mlag_id]
                if actual_state != expected_state:
                    failures.append(
                        f"{device_name}: MLAG interface {mlag_id} state is "
                        f"'{actual_state}', expected '{expected_state}'"
                    )

        if failures:
            self.failed("\n".join(failures))


# ---------------------------------------------------------------------------
# Common Cleanup
# ---------------------------------------------------------------------------

class CommonCleanup(aetest.CommonCleanup):

    @aetest.subsection
    def disconnect_from_devices(self, testbed, mlag_device_names):
        for device_name in mlag_device_names:
            device = testbed.devices[device_name]
            if device.is_connected():
                device.disconnect()