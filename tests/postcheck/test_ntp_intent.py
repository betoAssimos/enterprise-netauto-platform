# tests/postcheck/test_ntp_intent.py
#
# pyATS post-deployment NTP intent validation test.
#
# Validates that each device is synchronized to the NTP server defined
# in inventory.
#
# Devices under test: derived from inventory — any device with ntp.server
# configured (edge-routers and core-switches in this topology).
# No device names are hardcoded — inventory is the single source of truth.
#
# Parser strategy:
#   IOS XE — Genie parser for 'show ntp status'
#   EOS     — device.execute() + regex (no Genie NTP parser for EOS)
#
# Usage:
#   pyats run job tests/postcheck/test_ntp_intent.py --testbed tests/testbed.yaml

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


def _get_ntp_device_names(nr) -> list:
    """
    Derive NTP device names from inventory.
    Any device with ntp.server configured is included.
    """
    hosts = nr.filter(
        filter_func=lambda h: bool(
            h.data.get("custom_fields", {}).get("ntp", {}).get("server")
        )
    )
    return list(hosts.inventory.hosts.keys())


def _build_intent_from_inventory(nr) -> dict:
    """
    Derive NTP intent for all devices with NTP configured.

    Returns:
        {
            "rtr-01": {"expected_server": "10.20.20.100", "expected_status": "synchronized"},
            ...
        }
    """
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from automation.workflows.services.ntp_intent_builder import build_ntp_intent

    intent = {}
    ntp_hosts = nr.filter(
        filter_func=lambda h: bool(
            h.data.get("custom_fields", {}).get("ntp", {}).get("server")
        )
    )

    for host_name, host in ntp_hosts.inventory.hosts.items():

        class _FakeTask:
            def __init__(self, h):
                self.host = h

        intent[host_name] = build_ntp_intent(_FakeTask(host))

    return intent


def _get_ntp_status(device) -> dict:
    """
    Parse NTP sync status from device.

    IOS XE: Genie parser for 'show ntp status'
    EOS:    device.execute() + regex

    Returns:
        {
            "status": "synchronized",
            "server": "10.20.20.100"
        }

    All values lowercased. Returns empty dict on failure.
    """
    try:
        if device.os == "iosxe":
            parsed = device.parse("show ntp status")
            system_status = (
                parsed
                .get("clock_state", {})
                .get("system_status", {})
            )
            return {
                "status": system_status.get("status", "").lower(),
                "server": system_status.get("refid", ""),
            }

        else:
            # EOS output example:
            #   synchronised to NTP server (10.20.20.100) at stratum 4
            output = device.execute("show ntp status")
            result = {}
            for line in output.splitlines():
                sync_match = re.match(
                    r"(synchronised|unsynchronised)\s+to\s+NTP server\s+\((\S+)\)",
                    line.strip(),
                    re.IGNORECASE,
                )
                if sync_match:
                    result["status"] = sync_match.group(1).lower()
                    result["server"] = sync_match.group(2)
            return result

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
        self.parent.parameters["ntp_device_names"] = _get_ntp_device_names(nr)

    @aetest.subsection
    def connect_to_devices(self, testbed, ntp_device_names):
        for device_name in ntp_device_names:
            device = testbed.devices[device_name]
            device.credentials.default.username = os.environ.get("DEVICE_USERNAME")
            device.credentials.default.password = os.environ.get("DEVICE_PASSWORD")
            device.connect(log_stdout=False, timeout=60)


# ---------------------------------------------------------------------------
# Test — NTP Sync State
# ---------------------------------------------------------------------------

class TestNTPIntent(aetest.Testcase):

    @aetest.setup
    def setup(self, testbed, intent):
        self.testbed = testbed
        self.intent = intent

    @aetest.test
    def test_ntp_synchronized(self):
        """
        Assert that each device is synchronized to the NTP server
        defined in inventory.

        Fails if:
          - Device is not in synchronized state
          - Device is synchronized but to a different server than intended
        """
        failures = []

        for device_name, device_intent in self.intent.items():
            expected_server = device_intent.get("expected_server")
            expected_status = device_intent.get("expected_status", "synchronized")

            if not expected_server:
                continue

            device = self.testbed.devices[device_name]
            observed = _get_ntp_status(device)

            actual_status = observed.get("status", "")
            actual_server = observed.get("server", "")

            # Normalize British/American spelling difference (EOS: synchronised, IOS XE: synchronized)
            def _normalize_sync(s: str) -> str:
                return s.replace("synchronised", "synchronized")

            if _normalize_sync(actual_status) != _normalize_sync(expected_status.lower()):
                failures.append(
                    f"{device_name}: NTP status is '{actual_status}', "
                    f"expected '{expected_status}'"
                )

            if actual_server != expected_server:
                failures.append(
                    f"{device_name}: NTP server is '{actual_server}', "
                    f"expected '{expected_server}'"
                )

        if failures:
            self.failed("\n".join(failures))


# ---------------------------------------------------------------------------
# Common Cleanup
# ---------------------------------------------------------------------------

class CommonCleanup(aetest.CommonCleanup):

    @aetest.subsection
    def disconnect_from_devices(self, testbed, ntp_device_names):
        for device_name in ntp_device_names:
            device = testbed.devices[device_name]
            if device.is_connected():
                device.disconnect()