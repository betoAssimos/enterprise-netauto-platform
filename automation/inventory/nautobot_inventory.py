"""
automation/inventory/nautobot_inventory.py

Nornir inventory plugin backed by Nautobot API.

Nautobot is the single source of truth. This plugin fetches all device
records matching the supplied filters and maps them into Nornir Host
objects. No static inventory files exist anywhere in this platform.

Design:
- Filters are passed as Nautobot API query parameters (site, role, tag, etc.)
- Credentials are injected at runtime from PlatformSettings (never from Nautobot)
- Platform slug is mapped to Scrapli driver name
- Primary IP is preferred as hostname; device name is the fallback
- Groups are auto-created per site and per role
"""

from __future__ import annotations

from typing import Any

import pynautobot
from nornir.core.inventory import (
    ConnectionOptions,
    Defaults,
    Group,
    Groups,
    Host,
    Hosts,
    Inventory,
)

from automation.config import get_settings
from automation.utils.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Nautobot platform slug → Scrapli driver mapping
# ---------------------------------------------------------------------------

PLATFORM_MAP: dict[str, str] = {
    "cisco_ios": "cisco_iosxe",
    "cisco_iosxe": "cisco_iosxe",
    "cisco_iosxr": "cisco_iosxr",
    "cisco_nxos": "cisco_nxos",
    "arista_eos": "arista_eos",
    "juniper_junos": "juniper_junos",
}


# ---------------------------------------------------------------------------
# Inventory plugin
# ---------------------------------------------------------------------------


class NautobotInventory:
    """
    Nornir inventory plugin that builds host/group/defaults
    entirely from the Nautobot API.

    Parameters (passed via InitNornir plugin options):
        filter_parameters : dict[str, Any]
            Forwarded verbatim to pynautobot devices.filter().
            Examples:
                {"site": "lab-dc01"}
                {"role": "core-router", "tag": "managed"}
                {"name__ic": "rtr"}
        username : str
            Device SSH username. Injected from environment.
        password : str
            Device SSH password. Injected from environment.
    """

    def __init__(
        self,
        filter_parameters: dict[str, Any] | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.filter_parameters = filter_parameters or {}
        self._username = username
        self._password = password

    def load(self) -> Inventory:
        cfg = get_settings()

        nb = pynautobot.api(
            url=cfg.nautobot.url,
            token=cfg.nautobot.token.get_secret_value(),
            verify=cfg.nautobot.verify_ssl,
        )
        nb.http_session.timeout = cfg.nautobot.timeout

        log.info(
            "Fetching inventory from Nautobot",
            url=cfg.nautobot.url,
            filters=self.filter_parameters,
        )

        devices = list(nb.dcim.devices.filter(**self.filter_parameters))
        log.info("Devices fetched", count=len(devices))

        hosts = Hosts()
        groups = Groups()
        defaults = self._build_defaults(cfg)

        for device in devices:
            host = self._build_host(device, groups, cfg)
            if host:
                hosts[host.name] = host

        log.info("Inventory built", hosts=len(hosts), groups=len(groups))
        return Inventory(hosts=hosts, groups=groups, defaults=defaults)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_defaults(self, cfg: Any) -> Defaults:
        """Build Nornir Defaults with Scrapli connection options."""
        return Defaults(
            connection_options={
                "scrapli": ConnectionOptions(
                    platform=cfg.scrapli.platform,
                    extras={
                        "auth_strict_key": cfg.scrapli.auth_strict_key,
                        "timeout_socket": cfg.scrapli.timeout_socket,
                        "timeout_transport": cfg.scrapli.timeout_transport,
                        "timeout_ops": cfg.scrapli.timeout_ops,
                        "ssh_config_file": cfg.scrapli.ssh_config_file,
                    },
                )
            }
        )

    def _build_host(
        self,
        device: Any,
        groups: Groups,
        cfg: Any,
    ) -> Host | None:
        """Map a single Nautobot device record to a Nornir Host."""
        try:
            hostname = self._resolve_hostname(device)
            platform_slug = (
                str(device.platform.slug) if device.platform else "cisco_iosxe"
            )
            scrapli_platform = PLATFORM_MAP.get(platform_slug, "cisco_iosxe")

            # Build or reuse site and role groups
            site_slug = device.site.slug if device.site else "unknown"
            role_slug = device.device_role.slug if device.device_role else "unknown"
            site_group = self._ensure_group(groups, f"site__{site_slug}")
            role_group = self._ensure_group(groups, f"role__{role_slug}")

            host = Host(
                name=device.name,
                hostname=hostname,
                username=self._username,
                password=self._password,
                platform=scrapli_platform,
                groups=[site_group, role_group],
                data={
                    "nautobot_id": str(device.id),
                    "site": str(site_slug),
                    "role": str(role_slug),
                    "device_type": (
                        str(device.device_type.slug) if device.device_type else None
                    ),
                    "status": (
                        str(device.status.value) if device.status else None
                    ),
                    "custom_fields": dict(device.custom_fields or {}),
                    "tags": [str(t) for t in (device.tags or [])],
                },
                connection_options={
                    "scrapli": ConnectionOptions(
                        platform=scrapli_platform,
                        extras={
                            "auth_strict_key": cfg.scrapli.auth_strict_key,
                        },
                    )
                },
            )
            return host

        except Exception as exc:
            log.warning(
                "Skipping device — mapping error",
                device=str(device.name),
                error=str(exc),
            )
            return None

    @staticmethod
    def _resolve_hostname(device: Any) -> str:
        """Use primary IP if available, otherwise fall back to device name."""
        if device.primary_ip:
            return str(device.primary_ip.address).split("/")[0]
        return str(device.name)

    @staticmethod
    def _ensure_group(groups: Groups, name: str) -> Group:
        """Return existing group or create it."""
        if name not in groups:
            groups[name] = Group(name=name)
        return groups[name]
