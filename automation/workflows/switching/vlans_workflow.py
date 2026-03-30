"""
automation/workflows/switching/vlans_workflow.py

VLAN provisioning workflow — all Arista switches.

Deploys VLAN database on core and access switches.
VLANs must exist before port-channels can trunk them.

Devices:
    core-sw-01, core-sw-02 — VLANs 10, 20, 99, 4094 (MLAG peer)
    arista-01, arista-02   — VLANs 10, 20, 99
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

VLAN_TEMPLATE = "switching/vlans.j2"


def _vlan_context(task: Task) -> dict[str, Any]:
    device = task.host.name
    custom_fields = task.host.data.get("custom_fields", {})

    vlans = custom_fields.get("vlans")
    if not vlans:
        log.debug("Skipping device without VLAN config", device=device)
        return {}

    log.debug("VLAN context built", device=device, vlan_count=len(vlans))
    return {"vlans": vlans}


def run_vlans_deploy(nr: Nornir) -> dict[str, Any]:
    """Deploy VLANs on all Arista switches (core and access)."""
    log.info("VLAN deploy workflow starting", host_count=len(nr.inventory.hosts))

    arista_nr = nr.filter(
        filter_func=lambda h: h.data.get("manufacturer") == "Arista"
    )

    if not arista_nr.inventory.hosts:
        log.warning("No Arista devices found in inventory")
        return {"total": 0, "succeeded": [], "failed": [], "skipped": []}

    log.info(
        "Deploying VLANs",
        devices=list(arista_nr.inventory.hosts.keys()),
    )

    results = arista_nr.run(
        task=deploy_config,
        template_path=VLAN_TEMPLATE,
        context_builder=_vlan_context,
        pre_check=pre_check,
        post_check=post_check,
        rollback=rollback_config,
    )

    succeeded = [
        h for h, r in results.items()
        if not r.failed and not getattr(r[0], 'skipped', False)
    ]
    failed = [h for h, r in results.items() if r.failed]
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
        "VLAN deploy workflow complete",
        total=summary["total"],
        succeeded=len(succeeded),
        failed=len(failed),
        skipped=len(skipped),
    )
    return summary