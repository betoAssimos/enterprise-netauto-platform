# automation/inventory/seed_netbox.py
#
# Seed NetBox from hosts.yaml.
#
# Creates or updates:
#   - Device types (c8000v, cEOS)
#   - Platforms (iosxe, eos)
#   - Device roles (edge-router, core-switch, access-switch)
#   - Devices (all 6 network nodes)
#   - Management IPs in IPAM, assigned as primary IPv4
#   - Custom field definitions (36 fields)
#   - Custom field values per device
#
# Idempotent — safe to run multiple times.
# Uses get-or-create throughout. Never deletes anything.
#
# Usage:
#   python automation/inventory/seed_netbox.py

from __future__ import annotations

import json
import os
from pathlib import Path

import pynetbox
import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=BASE_DIR / ".env")

NETBOX_URL = os.environ["NETBOX_URL"]
NETBOX_TOKEN = os.environ["NETBOX_TOKEN"]

HOSTS_FILE = BASE_DIR / "automation/inventory/hosts.yaml"

# ---------------------------------------------------------------------------
# Static metadata — what hosts.yaml implies but doesn't explicitly state
# ---------------------------------------------------------------------------

SITE_NAME = "LAB"

MANUFACTURERS = {
    "Cisco": "cisco",
    "Arista": "arista",
}

DEVICE_TYPES = [
    {"model": "c8000v", "slug": "c8000v", "manufacturer_slug": "cisco"},
    {"model": "cEOS",   "slug": "ceos",   "manufacturer_slug": "arista"},
]

PLATFORMS = [
    {"name": "IOS XE", "slug": "iosxe", "manufacturer_slug": "cisco"},
    {"name": "EOS",    "slug": "eos",   "manufacturer_slug": "arista"},
]

DEVICE_ROLES = [
    {"name": "Edge Router",    "slug": "edge-router",    "color": "aa1409"},
    {"name": "Core Switch",    "slug": "core-switch",    "color": "2196f3"},
    {"name": "Access Switch",  "slug": "access-switch",  "color": "4caf50"},
]

# Maps hosts.yaml role string → NetBox device role slug
ROLE_MAP = {
    "edge-router":   "edge-router",
    "core-switch":   "core-switch",
    "access-switch": "access-switch",
}

# Maps hosts.yaml group → NetBox platform slug
GROUP_PLATFORM_MAP = {
    "cisco":  "iosxe",
    "arista": "eos",
}

# Maps hosts.yaml group → NetBox device type slug
GROUP_DTYPE_MAP = {
    "cisco":  "c8000v",
    "arista": "ceos",
}

# Maps hosts.yaml group → NetBox manufacturer slug
GROUP_MFR_MAP = {
    "cisco":  "cisco",
    "arista": "arista",
}

# ---------------------------------------------------------------------------
# Custom field definitions
# ---------------------------------------------------------------------------

# object_types value for NetBox v4.x (replaces content_types in v3.x)
DEVICE_OBJECT_TYPE = "dcim.device"

CUSTOM_FIELDS = [
    # BGP
    {"name": "bgp_asn",                    "type": "integer", "label": "BGP ASN"},
    {"name": "bgp_router_id",              "type": "text",    "label": "BGP Router ID"},
    {"name": "bgp_redistribute_connected", "type": "boolean", "label": "BGP Redistribute Connected"},
    {"name": "bgp_redistribute_ospf",      "type": "boolean", "label": "BGP Redistribute OSPF"},
    {"name": "bgp_neighbors",              "type": "json",    "label": "BGP Neighbors"},
    {"name": "bgp_networks",               "type": "json",    "label": "BGP Networks"},
    {"name": "bgp_prefix_lists",           "type": "json",    "label": "BGP Prefix Lists"},
    {"name": "bgp_route_maps",             "type": "json",    "label": "BGP Route Maps"},
    # OSPF
    {"name": "ospf_process",               "type": "integer", "label": "OSPF Process ID"},
    {"name": "ospf_router_id",             "type": "text",    "label": "OSPF Router ID"},
    {"name": "ospf_networks",              "type": "json",    "label": "OSPF Networks"},
    {"name": "ospf_default_originate",     "type": "boolean", "label": "OSPF Default Originate"},
    {"name": "ospf_neighbors",             "type": "json",    "label": "OSPF Neighbors"},
    # Routing
    {"name": "static_routes",              "type": "json",    "label": "Static Routes"},
    # NAT
    {"name": "nat_inside_interfaces",      "type": "json",    "label": "NAT Inside Interfaces"},
    {"name": "nat_outside_interface",      "type": "text",    "label": "NAT Outside Interface"},
    {"name": "nat_acl_entries",            "type": "json",    "label": "NAT ACL Entries"},
    # Interfaces
    {"name": "interfaces",                 "type": "json",    "label": "Interfaces"},
    {"name": "routed_interfaces",          "type": "json",    "label": "Routed Interfaces"},
    {"name": "svis",                       "type": "json",    "label": "SVIs"},
    {"name": "access_ports",              "type": "json",    "label": "Access Ports"},
    # MLAG
    {"name": "mlag_domain_id",             "type": "integer", "label": "MLAG Domain ID"},
    {"name": "mlag_role",                  "type": "text",    "label": "MLAG Role"},
    {"name": "mlag_peer_link",             "type": "text",    "label": "MLAG Peer Link"},
    {"name": "mlag_peer_link_members",     "type": "json",    "label": "MLAG Peer Link Members"},
    {"name": "mlag_local_ip",              "type": "text",    "label": "MLAG Local IP"},
    {"name": "mlag_peer_ip",               "type": "text",    "label": "MLAG Peer IP"},
    {"name": "mlag_peer_mgmt_ip",          "type": "text",    "label": "MLAG Peer Mgmt IP"},
    {"name": "mlag_portchannels",          "type": "json",    "label": "MLAG Port-Channels"},
    # Switching
    {"name": "vlans",                      "type": "json",    "label": "VLANs"},
    {"name": "uplink_portchannel",         "type": "json",    "label": "Uplink Port-Channel"},
    {"name": "vrrp_groups",               "type": "json",    "label": "VRRP Groups"},
    # Services
    {"name": "snmp",                       "type": "json",    "label": "SNMP"},
    {"name": "syslog",                     "type": "json",    "label": "Syslog"},
    {"name": "ssh",                        "type": "json",    "label": "SSH"},
    {"name": "ntp",                        "type": "json",    "label": "NTP"},
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    return name.lower().replace(" ", "-").replace("_", "-")


def get_or_create(endpoint, lookup: dict, create: dict, label: str) -> tuple:
    """
    Fetch an object matching `lookup`. Create with `create` if not found.
    Returns (object, created_bool).
    """
    obj = endpoint.get(**lookup)
    if obj:
        return obj, False
    obj = endpoint.create(**create)
    print(f"  [created] {label}")
    return obj, True


# ---------------------------------------------------------------------------
# Phase functions
# ---------------------------------------------------------------------------

def ensure_manufacturers(nb) -> dict:
    """Return {slug: manufacturer_object}."""
    result = {}
    for name, slug in MANUFACTURERS.items():
        obj, created = get_or_create(
            nb.dcim.manufacturers,
            {"slug": slug},
            {"name": name, "slug": slug},
            f"manufacturer {name}",
        )
        result[slug] = obj
    return result


def ensure_device_types(nb, manufacturers: dict) -> dict:
    """Return {slug: device_type_object}."""
    result = {}
    for dt in DEVICE_TYPES:
        mfr = manufacturers[dt["manufacturer_slug"]]
        obj, created = get_or_create(
            nb.dcim.device_types,
            {"slug": dt["slug"]},
            {"model": dt["model"], "slug": dt["slug"], "manufacturer": mfr.id},
            f"device type {dt['model']}",
        )
        result[dt["slug"]] = obj
    return result


def ensure_platforms(nb, manufacturers: dict) -> dict:
    """Return {slug: platform_object}."""
    result = {}
    for p in PLATFORMS:
        mfr = manufacturers[p["manufacturer_slug"]]
        obj, created = get_or_create(
            nb.dcim.platforms,
            {"slug": p["slug"]},
            {"name": p["name"], "slug": p["slug"], "manufacturer": mfr.id},
            f"platform {p['name']}",
        )
        result[p["slug"]] = obj
    return result


def ensure_device_roles(nb) -> dict:
    """Return {slug: device_role_object}."""
    result = {}
    for role in DEVICE_ROLES:
        obj, created = get_or_create(
            nb.dcim.device_roles,
            {"slug": role["slug"]},
            {"name": role["name"], "slug": role["slug"], "color": role["color"]},
            f"device role {role['name']}",
        )
        result[role["slug"]] = obj
    return result


def ensure_site(nb) -> object:
    slug = _slug(SITE_NAME)
    obj, _ = get_or_create(
        nb.dcim.sites,
        {"slug": slug},
        {"name": SITE_NAME, "slug": slug},
        f"site {SITE_NAME}",
    )
    return obj


def ensure_custom_fields(nb) -> None:
    """Create all custom field definitions if not already present."""
    print("\n--- Custom Fields ---")
    for cf in CUSTOM_FIELDS:
        existing = nb.extras.custom_fields.get(name=cf["name"])
        if existing:
            print(f"  [exists]  custom field {cf['name']}")
            continue
        nb.extras.custom_fields.create(
            name=cf["name"],
            label=cf["label"],
            type=cf["type"],
            object_types=[DEVICE_OBJECT_TYPE],
        )
        print(f"  [created] custom field {cf['name']}")


def ensure_device(
    nb,
    host_name: str,
    host_data: dict,
    site,
    device_types: dict,
    platforms: dict,
    device_roles: dict,
) -> object:
    """
    Get or create a device. Update role if it differs from intent.
    Returns the device object.
    """
    group = host_data["groups"][0]
    data = host_data["data"]

    role_slug = ROLE_MAP[data["role"]]
    dtype_slug = GROUP_DTYPE_MAP[group]
    platform_slug = GROUP_PLATFORM_MAP[group]

    role = device_roles[role_slug]
    dtype = device_types[dtype_slug]
    platform = platforms[platform_slug]

    existing = nb.dcim.devices.get(name=host_name)

    if existing:
        # Fix role if wrong
        if existing.role.slug != role_slug:
            existing.role = role.id
            existing.save()
            print(f"  [updated] {host_name} role → {role_slug}")
        else:
            print(f"  [exists]  device {host_name}")
        return existing

    device = nb.dcim.devices.create(
        name=host_name,
        device_type=dtype.id,
        role=role.id,
        platform=platform.id,
        site=site.id,
        status="active",
    )
    print(f"  [created] device {host_name}")
    return device


def ensure_primary_ip(nb, device, hostname: str) -> None:
    """
    Create a Management interface on the device, assign the IP to it,
    then set as primary IPv4. NetBox v4 requires IP → interface assignment
    before the IP can be designated as primary.
    """
    address = f"{hostname}/32"

    # Step 1 — ensure Management interface exists
    mgmt_intf = nb.dcim.interfaces.get(device_id=device.id, name="Management0")
    if not mgmt_intf:
        mgmt_intf = nb.dcim.interfaces.create(
            device=device.id,
            name="Management0",
            type="virtual",
        )
        print(f"  [created] interface Management0 on {device.name}")
    else:
        print(f"  [exists]  interface Management0 on {device.name}")

    # Step 2 — ensure IP exists and is assigned to the interface
    existing_ip = nb.ipam.ip_addresses.get(address=address)
    if not existing_ip:
        existing_ip = nb.ipam.ip_addresses.create(
            address=address,
            status="active",
            assigned_object_type="dcim.interface",
            assigned_object_id=mgmt_intf.id,
        )
        print(f"  [created] IP {address} → {device.name}/Management0")
    else:
        # Reassign to interface if not already assigned there
        if (
            not existing_ip.assigned_object
            or existing_ip.assigned_object_id != mgmt_intf.id
        ):
            existing_ip.assigned_object_type = "dcim.interface"
            existing_ip.assigned_object_id = mgmt_intf.id
            existing_ip.save()
            print(f"  [updated] IP {address} assigned to {device.name}/Management0")
        else:
            print(f"  [exists]  IP {address}")

    # Step 3 — set as primary IPv4
    device_fresh = nb.dcim.devices.get(device.id)
    if not device_fresh.primary_ip4 or device_fresh.primary_ip4.address != address:
        device_fresh.primary_ip4 = existing_ip.id
        device_fresh.save()
        print(f"  [updated] {device.name} primary IP → {address}")


def set_custom_fields(nb, device, custom_fields: dict) -> None:
    """
    Push all custom field values to the device.
    JSON fields are passed as Python objects — pynetbox serialises them.
    """
    device_fresh = nb.dcim.devices.get(device.id)
    device_fresh.custom_fields.update(custom_fields)
    device_fresh.save()
    print(f"  [updated] {device.name} custom fields ({len(custom_fields)} fields)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Connecting to NetBox at {NETBOX_URL} ...")
    nb = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)
    nb.http_session.verify = False  # self-signed cert common in lab

    with open(HOSTS_FILE) as f:
        hosts = yaml.safe_load(f)

    print("\n--- Infrastructure ---")
    manufacturers = ensure_manufacturers(nb)
    device_types = ensure_device_types(nb, manufacturers)
    platforms = ensure_platforms(nb, manufacturers)
    device_roles = ensure_device_roles(nb)
    site = ensure_site(nb)

    ensure_custom_fields(nb)

    print("\n--- Devices ---")
    for host_name, host_data in hosts.items():
        print(f"\n{host_name}:")
        device = ensure_device(
            nb, host_name, host_data, site, device_types, platforms, device_roles
        )
        ensure_primary_ip(nb, device, host_data["hostname"])

        cf = host_data["data"].get("custom_fields", {})
        if cf:
            set_custom_fields(nb, device, cf)

    print("\nDone.")


if __name__ == "__main__":
    main()