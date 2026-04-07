# automation/inventory/netbox_inventory.py
#
# Nornir inventory plugin — builds host inventory live from NetBox.
#
# Replaces SimpleInventory + hosts.yaml. NetBox is the authoritative SoT.
# Groups and defaults are still loaded from yaml files (groups.yaml,
# defaults.yaml) so connection parameters remain in version control.
#
# Registration:
#   Import this module before InitNornir — the InventoryPluginRegister
#   call at the bottom registers "NetBoxInventory" as a valid plugin name.
#
# nornir_config.yaml:
#   inventory:
#     plugin: NetBoxInventory
#     options:
#       group_file: automation/inventory/groups.yaml
#       defaults_file: automation/inventory/defaults.yaml
#
# Data model produced per host:
#   hostname    : management IP (from primary_ip4, prefix stripped)
#   groups      : ["cisco"] or ["arista"] derived from manufacturer
#   data:
#     role       : device role slug (edge-router, core-switch, access-switch)
#     site       : site slug
#     model      : device type model string
#     manufacturer: manufacturer name
#     custom_fields: dict of all non-None custom field values from NetBox

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import pynetbox
import yaml
from dotenv import load_dotenv
from nornir.core.inventory import (
    ConnectionOptions,
    Defaults,
    Group,
    Groups,
    Host,
    Hosts,
    Inventory,
)
from nornir.core.plugins.inventory import InventoryPluginRegister

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Manufacturer → Nornir group name mapping
# Must match keys in groups.yaml
# ---------------------------------------------------------------------------

MANUFACTURER_GROUP_MAP = {
    "cisco":  "cisco",
    "arista": "arista",
}


def _manufacturer_to_group(manufacturer_name: str) -> str:
    """Map NetBox manufacturer name to Nornir group name."""
    return MANUFACTURER_GROUP_MAP.get(manufacturer_name.lower(), "cisco")


def _load_yaml(path: str) -> dict:
    """Load a yaml file. Return empty dict if file not found."""
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


from nornir.core.inventory import (
    ConnectionOptions,
    Defaults,
    Group,
    Groups,
    Host,
    Hosts,
    Inventory,
)


def _build_connection_options(raw: dict) -> dict:
    """Convert raw connection_options dict to ConnectionOptions objects."""
    return {
        conn_name: ConnectionOptions(
            hostname=opts.get("hostname"),
            port=opts.get("port"),
            username=opts.get("username"),
            password=opts.get("password"),
            platform=opts.get("platform"),
            extras=opts.get("extras", {}),
        )
        for conn_name, opts in raw.items()
    }


def _build_groups(group_file: Optional[str]) -> Groups:
    """
    Build Nornir Groups from groups.yaml.
    Converts raw connection_options dicts to ConnectionOptions objects —
    Nornir requires typed objects, not raw dicts.
    """
    groups: Groups = {}
    if not group_file:
        return groups

    raw = _load_yaml(group_file)
    for group_name, group_data in raw.items():
        group_data = group_data or {}
        raw_conn_opts = group_data.get("connection_options", {})
        groups[group_name] = Group(
            name=group_name,
            hostname=group_data.get("hostname"),
            username=group_data.get("username"),
            password=group_data.get("password"),
            platform=group_data.get("platform"),
            data=group_data.get("data"),
            groups=group_data.get("groups", []),
            connection_options=_build_connection_options(raw_conn_opts),
        )
    return groups


def _build_defaults(defaults_file: Optional[str]) -> Defaults:
    """Build Nornir Defaults from defaults.yaml."""
    if not defaults_file:
        return Defaults()

    raw = _load_yaml(defaults_file)
    if not raw:
        return Defaults()

    return Defaults(
        hostname=raw.get("hostname"),
        username=raw.get("username"),
        password=raw.get("password"),
        platform=raw.get("platform"),
        data=raw.get("data"),
        connection_options=raw.get("connection_options", {}),
    )


def _strip_none(d: dict) -> dict:
    """Remove keys with None values from a dict (shallow)."""
    return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------

class NetBoxInventory:
    """
    Nornir inventory plugin backed by NetBox.

    Options (set in nornir_config.yaml under inventory.options):
        group_file    : path to groups.yaml (optional, recommended)
        defaults_file : path to defaults.yaml (optional)
    """

    def __init__(
        self,
        group_file: Optional[str] = None,
        defaults_file: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        self.group_file = group_file
        self.defaults_file = defaults_file

        netbox_url = os.environ.get("NETBOX_URL")
        netbox_token = os.environ.get("NETBOX_TOKEN")

        if not netbox_url or not netbox_token:
            raise RuntimeError(
                "NETBOX_URL and NETBOX_TOKEN must be set in environment or .env"
            )

        self.nb = pynetbox.api(netbox_url, token=netbox_token)
        self.nb.http_session.verify = False

    def load(self) -> Inventory:
        groups = _build_groups(self.group_file)
        defaults = _build_defaults(self.defaults_file)
        hosts: Hosts = {}

        for device in self.nb.dcim.devices.filter(status="active"):

            # Skip devices without a management IP — cannot automate them
            if not device.primary_ip4:
                continue

            mgmt_ip = str(device.primary_ip4.address).split("/")[0]
            manufacturer_name = device.device_type.manufacturer.name
            group_name = _manufacturer_to_group(manufacturer_name)

            # Resolve group reference — create minimal group if not in groups.yaml
            if group_name not in groups:
                groups[group_name] = Group(name=group_name)
            host_groups = [groups[group_name]]

            # Custom fields — strip None values so the dict matches
            # what hosts.yaml contains (fields not applicable to a device
            # are simply absent, not None)
            raw_cf = dict(device.custom_fields) if device.custom_fields else {}
            custom_fields = _strip_none(raw_cf)

            host_data: Dict[str, Any] = {
                "role":          device.role.slug if device.role else None,
                "site":          device.site.slug if device.site else None,
                "model":         device.device_type.model,
                "manufacturer":  manufacturer_name,
                "custom_fields": custom_fields,
            }

            hosts[device.name] = Host(
                name=device.name,
                hostname=mgmt_ip,
                groups=host_groups,
                data=host_data,
                defaults=defaults,
            )

        return Inventory(hosts=hosts, groups=groups, defaults=defaults)


# ---------------------------------------------------------------------------
# Plugin registration
# Must execute at import time — before InitNornir is called
# ---------------------------------------------------------------------------

InventoryPluginRegister.register("NetBoxInventory", NetBoxInventory)