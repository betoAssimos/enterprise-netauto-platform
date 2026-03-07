"""
automation/inventory/runner.py

Nornir factory module.

Every task execution in this platform goes through get_nornir().
Never instantiate Nornir directly in any other module.

Design:
- Single, tested initialization path
- Runner plugin and worker count driven by PlatformSettings
- Credentials injected from environment variables
- Optional Nautobot-side filters reduce API payload
- Optional Nornir-side filter for post-load precision targeting
"""

from __future__ import annotations

import os
from typing import Any

from nornir import InitNornir
from nornir.core import Nornir
from nornir.core.filter import F

from automation.config import get_settings
from automation.utils.logger import get_logger

import sys
print("DEBUG: script started", file=sys.stderr)
print("DEBUG: Nautobot URL =", os.getenv("NAUTOBOT_URL"), file=sys.stderr)
print("DEBUG: Nautobot token present =", bool(os.getenv("NAUTOBOT_TOKEN")), file=sys.stderr)

log = get_logger(__name__)


def get_nornir(
    filter_parameters: dict[str, Any] | None = None,
    *,
    username: str | None = None,
    password: str | None = None,
    filter_func: Any | None = None,
) -> Nornir:
    """
    Build and return a fully configured Nornir instance.

    Parameters
    ----------
    filter_parameters : dict[str, Any], optional
        Nautobot-side filters applied during inventory fetch.
        Reduces API response size for large environments.
        Examples:
            {"site": "lab-dc01"}
            {"role": "core-router"}
            {"site": "lab-dc01", "role": "core-router"}

    username : str, optional
        Device SSH username.
        Falls back to DEVICE_USERNAME environment variable.

    password : str, optional
        Device SSH password.
        Falls back to DEVICE_PASSWORD environment variable.

    filter_func : nornir.core.filter.F, optional
        Nornir filter applied after inventory is loaded.
        Use for targeting specific hosts within an already-filtered set.
        Example: filter_func=F(name__contains="rtr")

    Returns
    -------
    Nornir
        Configured instance ready for task execution.
    """
    cfg = get_settings()

    resolved_username = username or os.getenv("DEVICE_USERNAME", "admin")
    resolved_password = password or os.getenv("DEVICE_PASSWORD", "")

    log.info(
        "Initializing Nornir",
        runner=cfg.nornir.runner_plugin,
        workers=cfg.nornir.num_workers,
        environment=cfg.environment,
        filters=filter_parameters or {},
    )

    nr = InitNornir(
        runner={
            "plugin": cfg.nornir.runner_plugin,
            "options": {"num_workers": cfg.nornir.num_workers},
        },
        inventory={
            "plugin": "automation.inventory.nautobot_inventory.NautobotInventory",
            "options": {
                "filter_parameters": filter_parameters or {},
                "username": resolved_username,
                "password": resolved_password,
            },
        },
        logging={"enabled": False},
    )

    if filter_func is not None:
        nr = nr.filter(filter_func)
        log.debug(
            "Nornir filter applied",
            remaining_hosts=len(nr.inventory.hosts),
        )

    log.info("Nornir ready", host_count=len(nr.inventory.hosts))
    return nr


def get_nornir_for_devices(
    device_names: list[str],
    **kwargs: Any,
) -> Nornir:
    """
    Return a Nornir instance scoped to a specific list of device names.

    Useful for targeted deploys, rollbacks, and re-checks after failure.

    Parameters
    ----------
    device_names : list[str]
        Exact device names as they appear in Nautobot.

    Example
    -------
        nr = get_nornir_for_devices(["rtr-01", "rtr-02"])
    """
    log.info("Building targeted Nornir instance", devices=device_names)
    filter_func = F(name__in=device_names)
    return get_nornir(filter_func=filter_func, **kwargs)
