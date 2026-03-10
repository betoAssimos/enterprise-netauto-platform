#!/usr/bin/env python3
"""
automation/inventory/netbox_seed.py

Seeds NetBox with BGP custom field definitions and populates
device-level BGP data for rtr-01 and rtr-02.

Custom fields created:
    bgp_asn       (integer) : Local BGP AS number
    bgp_router_id (text)    : BGP router-id
    bgp_neighbors (json)    : List of neighbor dicts

BGP topology:
    rtr-01 AS 65001 peers with rtr-02 AS 65002 via 10.0.0.0/30

Usage:
    python3 automation/inventory/netbox_seed.py
"""

from __future__ import annotations

import os
import sys

import pynetbox
from dotenv import load_dotenv

from automation.utils.logger import get_logger

load_dotenv(override=True)
log = get_logger(__name__)

NETBOX_URL = os.getenv("NETBOX_URL")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN")

if not NETBOX_URL or not NETBOX_TOKEN:
    log.error("NETBOX_URL and NETBOX_TOKEN must be set in .env")
    sys.exit(1)

nb = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)

# ---------------------------------------------------------------------------
# Custom field definitions
# ---------------------------------------------------------------------------

CUSTOM_FIELDS = [
    {
        "name": "bgp_asn",
        "label": "BGP ASN",
        "type": "integer",
        "object_types": ["dcim.device"],
        "required": False,
        "description": "Local BGP Autonomous System Number",
    },
    {
        "name": "bgp_router_id",
        "label": "BGP Router ID",
        "type": "text",
        "object_types": ["dcim.device"],
        "required": False,
        "description": "BGP Router ID (IPv4 address)",
    },
    {
        "name": "bgp_neighbors",
        "label": "BGP Neighbors",
        "type": "json",
        "object_types": ["dcim.device"],
        "required": False,
        "description": "List of BGP neighbor dicts: [{ip, remote_as, description}]",
    },
    {
        "name": "bgp_redistribute_ospf",
        "label": "BGP Redistribute OSPF",
        "type": "boolean",
        "object_types": ["dcim.device"],
        "required": False,
        "description": "Redistribute OSPF routes into BGP",
    },
    {
        "name": "bgp_redistribute_connected",
        "label": "BGP Redistribute Connected",
        "type": "boolean",
        "object_types": ["dcim.device"],
        "required": False,
        "description": "Redistribute connected routes into BGP",
    },
]

# ---------------------------------------------------------------------------
# BGP data matching actual lab topology
# ---------------------------------------------------------------------------

BGP_DATA = {
    "rtr-01": {
        "bgp_asn": 65001,
        "bgp_router_id": "1.1.1.1",
        "bgp_neighbors": [
            {
                "ip": "10.0.0.2",
                "remote_as": 65002,
                "description": "rtr02",
                "update_source": "Loopback0",
            },
        ],
        "bgp_redistribute_ospf": True,
        "bgp_redistribute_connected": True,
    },
    "rtr-02": {
        "bgp_asn": 65002,
        "bgp_router_id": "2.2.2.2",
        "bgp_neighbors": [
            {
                "ip": "10.0.0.1",
                "remote_as": 65001,
                "description": "rtr01",
                "update_source": "Loopback0",
            },
        ],
        "bgp_redistribute_ospf": True,
        "bgp_redistribute_connected": True,
    },
    
}


def create_custom_fields() -> None:
    log.info("Creating BGP custom fields in NetBox")
    for cf_data in CUSTOM_FIELDS:
        existing = nb.extras.custom_fields.get(name=cf_data["name"])
        if existing:
            log.info("Custom field already exists, skipping", field=cf_data["name"])
        else:
            nb.extras.custom_fields.create(cf_data)
            log.info("Custom field created", field=cf_data["name"])


def populate_bgp_data() -> None:
    log.info("Populating BGP custom fields on devices")
    for device_name, bgp_cfg in BGP_DATA.items():
        device = nb.dcim.devices.get(name=device_name)
        if not device:
            log.warning("Device not found in NetBox, skipping", device=device_name)
            continue
        for field_name, field_value in bgp_cfg.items():
            device.custom_fields[field_name] = field_value
        device.save()
        log.info(
            "Device BGP data updated",
            device=device_name,
            asn=bgp_cfg["bgp_asn"],
            router_id=bgp_cfg["bgp_router_id"],
            neighbor_count=len(bgp_cfg["bgp_neighbors"]),
            redistribute_ospf=bgp_cfg.get("bgp_redistribute_ospf"),
            redistribute_connected=bgp_cfg.get("bgp_redistribute_connected"),
        )


if __name__ == "__main__":
    create_custom_fields()
    populate_bgp_data()
    log.info("NetBox BGP seed complete")