#!/usr/bin/env python3
"""
automation/inventory/netbox_inventory.py

Generates automation/inventory/hosts.yaml dynamically from NetBox.

Pulls:
    - Device name, management IP, platform
    - Site, role, model, manufacturer
    - BGP custom fields: bgp_asn, bgp_router_id, bgp_neighbors

Credentials are read from environment variables — never hardcoded.

Usage:
    python3 automation/inventory/netbox_inventory.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pynetbox
import yaml
from dotenv import load_dotenv

from automation.utils.logger import get_logger

load_dotenv(override=True)
log = get_logger(__name__)

NETBOX_URL = os.getenv("NETBOX_URL")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN")
DEVICE_USERNAME = os.getenv("DEVICE_USERNAME")
DEVICE_PASSWORD = os.getenv("DEVICE_PASSWORD")

if not NETBOX_URL or not NETBOX_TOKEN:
    log.error("NETBOX_URL and NETBOX_TOKEN must be set in .env")
    sys.exit(1)

if not DEVICE_USERNAME or not DEVICE_PASSWORD:
    log.error("DEVICE_USERNAME and DEVICE_PASSWORD must be set in .env")
    sys.exit(1)

OUTPUT_PATH = Path(__file__).parent / "hosts.yaml"

nb = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)


def get_platform(manufacturer: str) -> str:
    manufacturer = manufacturer.lower()
    if "cisco" in manufacturer:
        return "cisco"
    if "arista" in manufacturer:
        return "arista"
    return "linux"


def build_inventory() -> dict:
    hosts = {}
    for device in nb.dcim.devices.filter(status="active"):
        if not device.primary_ip4:
            log.warning("Skipping device without primary IPv4", device=device.name)
            continue

        mgmt_ip = str(device.primary_ip4.address).split("/")[0]
        manufacturer = device.device_type.manufacturer.name
        platform = get_platform(manufacturer)

        host: dict = {
            "hostname": mgmt_ip,
            "groups": [platform],
            "data": {
                "site": device.site.slug if device.site else None,
                "role": device.role.slug if device.role else None,
                "model": device.device_type.model,
                "manufacturer": manufacturer,
                "custom_fields": {},
            },
        }

        cf = dict(device.custom_fields)
        if cf.get("bgp_asn"):
            host["data"]["custom_fields"]["bgp_asn"] = cf["bgp_asn"]
        if cf.get("bgp_router_id"):
            host["data"]["custom_fields"]["bgp_router_id"] = cf["bgp_router_id"]
        if cf.get("bgp_neighbors"):
            host["data"]["custom_fields"]["bgp_neighbors"] = cf["bgp_neighbors"]

        hosts[device.name] = host
        log.debug("Device added to inventory", device=device.name, ip=mgmt_ip)

    return hosts


if __name__ == "__main__":
    log.info("Building inventory from NetBox", url=NETBOX_URL)
    hosts = build_inventory()
    with open(OUTPUT_PATH, "w") as f:
        yaml.dump(hosts, f, default_flow_style=False)
    log.info("Inventory written", path=str(OUTPUT_PATH), device_count=len(hosts))