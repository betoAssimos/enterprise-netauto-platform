# tests/postcheck/test_vrrp_intent.py
#
# pyATS post-deployment VRRP intent validation test.
#
# Validates that each VRRP group on each core switch is in the expected
# state (Master/Backup) with the correct virtual IP.
#
# Devices under test: derived from inventory (role: core-switch)
# No device names are hardcoded — inventory is the single source of truth.
#
# Parser strategy:
#   EOS: no Genie VRRP parser available — device.execute() + regex
#
# Usage:
#   pyats run job tests/postcheck/test_vrrp_intent.py --testbed tests/testbed.yaml

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


def _get_vrrp_device_names(nr) -> list:
    """
    Derive VRRP device names from inventory by role.
    Only core-switches run VRRP in this topology.
    """
    hosts = nr.filter(
        filter_func=lambda h: h.data.get("role") == "core-switch"
    )
    return list(hosts.inventory.hosts.keys())


def _build_intent_from_inventory(nr) -> dict:
    """
    Derive VRRP intent for all core switches.

    Returns:
        {
            "core-sw-01": {
                "expected_vrrp_groups": [...]
            },
            ...
        }
    """
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from automation.workflows.switching.vrrp_intent_builder import build_vrrp_intent

    intent = {}
    vrrp_hosts = nr.filter(
        filter_func=lambda h: h.data.get("role") == "core-switch"
    )

    for host_name, host in vrrp_hosts.inventory.hosts.items():

        class _FakeTask:
            def __init__(self, h):
                self.host = h

        intent[host_name] = build_vrrp_intent(_FakeTask(host))

    return intent


def _get_vrrp_states(device) -> dict:
    """
    Parse VRRP group state from device via execute() + regex.

    EOS output format:
        Vlan10 - Group 10
          State is Master
          Virtual IPv4 address is 10.10.10.1

    Returns:
        {
            (vlan_id, group_id): {
                "state": "master",
                "virtual_ip": "10.10.10.1"
            },
            ...
        }

    Keys are (vlan_int, group_int) tuples. State is lowercased.
    Returns empty dict on failure.
    """
    try:
        output = device.execute("show vrrp")
        groups = {}

        current_key = None
        for line in output.splitlines():
            # Match group header: "Vlan10 - Group 10"
            header = re.match(r"Vlan(\d+)\s+-\s+Group\s+(\d+)", line.strip())
            if header:
                current_key = (int(header.group(1)), int(header.group(2)))
                groups[current_key] = {}
                continue

            if current_key is None:
                continue

            state_match = re.match(r"State is (\S+)", line.strip())
            if state_match:
                groups[current_key]["state"] = state_match.group(1).lower()

            vip_match = re.match(r"Virtual IPv4 address is (\S+)", line.strip())
            if vip_match:
                groups[current_key]["virtual_ip"] = vip_match.group(1)

        return groups

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
        self.parent.parameters["vrrp_device_names"] = _get_vrrp_device_names(nr)

    @aetest.subsection
    def connect_to_devices(self, testbed, vrrp_device_names):
        for device_name in vrrp_device_names:
            device = testbed.devices[device_name]
            device.credentials.default.username = os.environ.get("DEVICE_USERNAME")
            device.credentials.default.password = os.environ.get("DEVICE_PASSWORD")
            device.connect(log_stdout=False, timeout=60)


# ---------------------------------------------------------------------------
# Test — VRRP Group State
# ---------------------------------------------------------------------------

class TestVRRPIntent(aetest.Testcase):

    @aetest.setup
    def setup(self, testbed, intent):
        self.testbed = testbed
        self.intent = intent

    @aetest.test
    def test_vrrp_group_state(self):
        """
        Assert that each VRRP group is in the expected state (Master/Backup)
        with the correct virtual IP.

        Fails if:
          - A VRRP group is missing from the device output
          - A group is present but in the wrong state
          - A group has the wrong virtual IP
        """
        failures = []

        for device_name, device_intent in self.intent.items():
            device = self.testbed.devices[device_name]
            observed = _get_vrrp_states(device)

            for group in device_intent["expected_vrrp_groups"]:
                vlan = group["vlan"]
                grp_id = group["group"]
                expected_state = group["expected_state"].lower()
                expected_vip = group["virtual_ip"]

                key = (vlan, grp_id)

                if key not in observed:
                    failures.append(
                        f"{device_name}: VRRP group {grp_id} on Vlan{vlan} not found"
                    )
                    continue

                actual_state = observed[key].get("state", "")
                actual_vip = observed[key].get("virtual_ip", "")

                if actual_state != expected_state:
                    failures.append(
                        f"{device_name}: Vlan{vlan} group {grp_id} state is "
                        f"'{actual_state}', expected '{expected_state}'"
                    )

                if actual_vip != expected_vip:
                    failures.append(
                        f"{device_name}: Vlan{vlan} group {grp_id} virtual IP is "
                        f"'{actual_vip}', expected '{expected_vip}'"
                    )

        if failures:
            self.failed("\n".join(failures))


# ---------------------------------------------------------------------------
# Common Cleanup
# ---------------------------------------------------------------------------

class CommonCleanup(aetest.CommonCleanup):

    @aetest.subsection
    def disconnect_from_devices(self, testbed, vrrp_device_names):
        for device_name in vrrp_device_names:
            device = testbed.devices[device_name]
            if device.is_connected():
                device.disconnect()