"""
automation/workflows/switching/portchannels_workflow.py

Port-channel deployment workflow — all Arista switches.

Run 1 — Core switches (core-sw-01, core-sw-02):
    - MLAG peer-link (Port-Channel1) with member interfaces
    - MLAG member port-channels toward access switches
    - Access port toward svc-01

Run 2 — Access switches (arista-01, arista-02):
    - Uplink port-channel toward core MLAG pair
    - Access ports toward end hosts

VLANs must be deployed before running this workflow.
"""
from __future__ import annotations

from typing import Any

from nornir.core import Nornir
from nornir.core.task import Task

from automation.tasks.deploy_config import deploy_config
from automation.utils.logger import get_logger
from automation.validators.checks import post_check, pre_check
from automation.rollback.rollback import rollback_config

log = get_logger(__name__)

CORE_PC_TEMPLATE = "switching/portchannels_core.j2"
ACCESS_PC_TEMPLATE = "switching/portchannels_access.j2"


def _core_portchannel_context(task: Task) -> dict[str, Any]:
    device = task.host.name
    custom_fields = task.host.data.get("custom_fields", {})

    mlag_peer_link = custom_fields.get("mlag_peer_link")
    mlag_peer_link_members = custom_fields.get("mlag_peer_link_members", [])
    mlag_portchannels = custom_fields.get("mlag_portchannels", [])

    if not mlag_peer_link or not mlag_portchannels:
        log.debug("Skipping device without core port-channel config", device=device)
        return {}

    context: dict[str, Any] = {
        "mlag_peer_link": mlag_peer_link,
        "mlag_peer_link_members": mlag_peer_link_members,
        "mlag_portchannels": mlag_portchannels,
    }

    access_ports = custom_fields.get("access_ports")
    if access_ports:
        context["access_ports"] = access_ports

    log.debug(
        "Core port-channel context built",
        device=device,
        mlag_portchannels=len(mlag_portchannels),
    )
    return context


def _access_portchannel_context(task: Task) -> dict[str, Any]:
    device = task.host.name
    custom_fields = task.host.data.get("custom_fields", {})

    uplink = custom_fields.get("uplink_portchannel")
    access_ports = custom_fields.get("access_ports", [])

    if not uplink:
        log.debug("Skipping device without access port-channel config", device=device)
        return {}

    log.debug("Access port-channel context built", device=device)
    return {
        "uplink_portchannel": uplink,
        "access_ports": access_ports,
    }


def run_portchannels_deploy(nr: Nornir) -> dict[str, Any]:
    """
    Deploy port-channels across all Arista switches.
    Run 1: core switches — MLAG peer-link + member port-channels
    Run 2: access switches — uplink port-channel + access ports
    """
    log.info(
        "Port-channel deploy workflow starting",
        host_count=len(nr.inventory.hosts),
    )

    succeeded: list[str] = []
    failed: list[str] = []

    # Run 1 — Core switches
    core_nr = nr.filter(
        filter_func=lambda h: h.data.get("role") == "core-switch"
    )
    if core_nr.inventory.hosts:
        log.info(
            "Deploying core port-channels",
            devices=list(core_nr.inventory.hosts.keys()),
        )
        core_results = core_nr.run(
            task=deploy_config,
            template_path=CORE_PC_TEMPLATE,
            context_builder=_core_portchannel_context,
            pre_check=pre_check,
            post_check=post_check,
            rollback=rollback_config,
        )
        succeeded += [
            h for h, r in core_results.items()
            if not r.failed and not getattr(r[0], 'skipped', False)
        ]
        failed += [h for h, r in core_results.items() if r.failed]

    # Run 2 — Access switches
    access_nr = nr.filter(
        filter_func=lambda h: h.data.get("role") == "access-switch"
    )
    if access_nr.inventory.hosts:
        log.info(
            "Deploying access port-channels",
            devices=list(access_nr.inventory.hosts.keys()),
        )
        access_results = access_nr.run(
            task=deploy_config,
            template_path=ACCESS_PC_TEMPLATE,
            context_builder=_access_portchannel_context,
            pre_check=pre_check,
            post_check=post_check,
            rollback=rollback_config,
        )
        succeeded += [
            h for h, r in access_results.items()
            if not r.failed and not getattr(r[0], 'skipped', False)
        ]
        failed += [h for h, r in access_results.items() if r.failed]

    skipped = [
        h for h in nr.inventory.hosts
        if h not in succeeded and h not in failed
    ]

    summary = {
        "total": len(nr.inventory.hosts),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
    }

    log.info(
        "Port-channel deploy workflow complete",
        total=summary["total"],
        succeeded=len(succeeded),
        failed=len(failed),
        skipped=len(skipped),
    )
    return summary