# tests/postcheck/test_bgp_intent.py
#
# pyATS post-deployment BGP intent validation test.
#
# Verifies that prefixes actually advertised to each eBGP neighbor match
# the intent derived from inventory policy (route-map → prefix-list chain).
#
# This is an intent-based check, not a state check. It answers:
#   "Is the network advertising exactly what it is supposed to advertise?"
#
# Devices under test: rtr-01, rtr-02 (edge routers only)
#
# Usage:
#   pyats run job tests/postcheck/test_bgp_intent.py --testbed tests/testbed.yaml

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
    """Initialize Nornir using the platform inventory (hosts.yaml)."""
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


def _build_intent_from_inventory(nr) -> dict:
    """
    Derive BGP advertised prefix intent for all edge routers.

    Imports the intent builder inside the function to keep pyATS
    test collection independent of the automation package structure.

    Returns:
        {
            "rtr-01": {"advertised_prefixes": [{"prefix": "...", "source_prefix_list": "..."}]},
            "rtr-02": {...}
        }
    """
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from automation.workflows.routing.bgp_intent_builder import build_bgp_intent

    intent = {}
    edge_routers = nr.filter(filter_func=lambda h: h.data.get("role") == "edge-router")

    for host_name, host in edge_routers.inventory.hosts.items():

        class _FakeTask:
            """Minimal Task-like object to satisfy build_bgp_intent signature."""
            def __init__(self, h):
                self.host = h

        intent[host_name] = build_bgp_intent(_FakeTask(host))

    return intent


def _get_advertised_prefixes(device, neighbor_ip: str) -> set:
    """
    Parse advertised routes to a specific neighbor via Genie.

    Returns a set of prefix strings (e.g. {"1.1.1.1/32"}).
    Returns an empty set if the neighbor has no advertised routes.
    """
    try:
        parsed = device.parse(
            f"show bgp neighbors {neighbor_ip} advertised-routes"
        )
        af_data = (
            parsed
            .get("vrf", {})
            .get("default", {})
            .get("neighbor", {})
            .get(neighbor_ip, {})
            .get("address_family", {})
            .get("", {})
        )
        return set(af_data.get("advertised", {}).keys())
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Common Setup — build intent and connect to devices
# ---------------------------------------------------------------------------

class CommonSetup(aetest.CommonSetup):

    @aetest.subsection
    def build_intent(self):
        nr = _init_nornir()
        self.parent.parameters["intent"] = _build_intent_from_inventory(nr)

    @aetest.subsection
    def connect_to_devices(self, testbed):
        for device_name in ["rtr-01", "rtr-02"]:
            device = testbed.devices[device_name]
            device.credentials.default.username = os.environ.get("DEVICE_USERNAME")
            device.credentials.default.password = os.environ.get("DEVICE_PASSWORD")
            device.connect(log_stdout=False, timeout=60)


# ---------------------------------------------------------------------------
# BGP Intent Validation Test
# ---------------------------------------------------------------------------

class TestBGPIntent(aetest.Testcase):

    @aetest.setup
    def setup(self, testbed, intent):
        self.testbed = testbed
        self.intent = intent

    @aetest.test
    def test_advertised_prefixes_match_intent(self):
        """
        Assert that each router advertises exactly the prefixes defined
        by its outbound routing policy in inventory.

        Fails if:
          - A prefix is advertised but not in intent (unexpected advertisement)
          - A prefix is in intent but not advertised (missing advertisement)
        """
        failures = []

        for device_name, device_intent in self.intent.items():
            device = self.testbed.devices[device_name]
            cf = device_intent
            intended = {entry["prefix"] for entry in cf.get("advertised_prefixes", [])}

            # Collect observed prefixes across all neighbors
            # Edge routers have one eBGP neighbor each in this topology
            nr = _init_nornir()
            host_data = nr.inventory.hosts[device_name].data.get("custom_fields", {})
            neighbors = host_data.get("bgp_neighbors", [])

            observed = set()
            for neighbor in neighbors:
                neighbor_ip = neighbor.get("ip")
                if neighbor_ip:
                    observed |= _get_advertised_prefixes(device, neighbor_ip)

            missing = intended - observed
            unexpected = observed - intended

            if missing:
                failures.append(
                    f"{device_name}: prefixes in intent but NOT advertised: {sorted(missing)}"
                )
            if unexpected:
                failures.append(
                    f"{device_name}: prefixes advertised but NOT in intent: {sorted(unexpected)}"
                )

        if failures:
            self.failed("\n".join(failures))


# ---------------------------------------------------------------------------
# Common Cleanup
# ---------------------------------------------------------------------------

class CommonCleanup(aetest.CommonCleanup):

    @aetest.subsection
    def disconnect_from_devices(self, testbed):
        for device_name in ["rtr-01", "rtr-02"]:
            device = testbed.devices[device_name]
            if device.is_connected():
                device.disconnect()