# tests/postcheck/test_bgp_received_intent.py
#
# pyATS post-deployment BGP received prefixes intent validation test.
#
# Verifies that prefixes actually received from each eBGP neighbor match
# the intent defined in inventory (received_prefixes per neighbor).
#
# This complements test_bgp_intent.py which validates advertised prefixes.
# Together they provide full BGP policy validation from both directions.
#
# Devices under test: derived from inventory (role: edge-router)
# No device names are hardcoded — inventory is the single source of truth.
#
# Usage:
#   pyats run job tests/postcheck/test_bgp_received_intent.py --testbed tests/testbed.yaml

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
    """
    Derive BGP device names from inventory by role.
    Only edge-routers run eBGP in this topology.
    """
    hosts = nr.filter(
        filter_func=lambda h: h.data.get("role") == "edge-router"
    )
    return list(hosts.inventory.hosts.keys())


def _build_intent_from_inventory(nr) -> dict:
    """
    Derive BGP received prefix intent for all edge routers.

    Returns:
        {
            "rtr-01": {
                "expected_received": [
                    {"neighbor_ip": "10.0.0.2", "prefixes": ["2.2.2.2/32"]}
                ]
            },
            ...
        }
    """
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from automation.workflows.routing.bgp_intent_builder import build_bgp_received_intent

    intent = {}
    edge_routers = nr.filter(
        filter_func=lambda h: h.data.get("role") == "edge-router"
    )

    for host_name, host in edge_routers.inventory.hosts.items():

        class _FakeTask:
            def __init__(self, h):
                self.host = h

        intent[host_name] = build_bgp_received_intent(_FakeTask(host))

    return intent


def _get_received_prefixes(device, neighbor_ip: str) -> set:
    """
    Parse prefixes received from a specific neighbor via Genie.

    Uses 'show bgp ipv4 unicast neighbors X routes' — no soft-reconfiguration
    inbound required. Returns routes accepted and installed from that neighbor.

    Returns a set of prefix strings (e.g. {"2.2.2.2/32"}).
    Returns empty set on parse failure.
    """
    try:
        parsed = device.parse(
            f"show bgp ipv4 unicast neighbors {neighbor_ip} routes"
        )
        af_data = (
            parsed
            .get("vrf", {})
            .get("default", {})
            .get("neighbor", {})
            .get(neighbor_ip, {})
            .get("address_family", {})
            .get("ipv4 unicast", {})
        )
        return set(af_data.get("routes", {}).keys())
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
        self.parent.parameters["bgp_device_names"] = _get_bgp_device_names(nr)

    @aetest.subsection
    def connect_to_devices(self, testbed, bgp_device_names):
        for device_name in bgp_device_names:
            device = testbed.devices[device_name]
            device.credentials.default.username = os.environ.get("DEVICE_USERNAME")
            device.credentials.default.password = os.environ.get("DEVICE_PASSWORD")
            device.connect(log_stdout=False, timeout=60)


# ---------------------------------------------------------------------------
# Test — BGP Received Prefixes
# ---------------------------------------------------------------------------

class TestBGPReceivedIntent(aetest.Testcase):

    @aetest.setup
    def setup(self, testbed, intent):
        self.testbed = testbed
        self.intent = intent

    @aetest.test
    def test_received_prefixes_match_intent(self):
        """
        Assert that each router receives exactly the prefixes defined
        in inventory from each eBGP neighbor.

        Fails if:
          - A prefix is in intent but not received (missing)
          - A prefix is received but not in intent (unexpected)
        """
        failures = []

        for device_name, device_intent in self.intent.items():
            device = self.testbed.devices[device_name]

            for neighbor_entry in device_intent.get("expected_received", []):
                neighbor_ip = neighbor_entry["neighbor_ip"]
                intended = set(neighbor_entry["prefixes"])
                observed = _get_received_prefixes(device, neighbor_ip)

                missing = intended - observed
                unexpected = observed - intended

                if missing:
                    failures.append(
                        f"{device_name}: prefixes expected from {neighbor_ip} "
                        f"but NOT received: {sorted(missing)}"
                    )
                if unexpected:
                    failures.append(
                        f"{device_name}: prefixes received from {neighbor_ip} "
                        f"but NOT in intent: {sorted(unexpected)}"
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