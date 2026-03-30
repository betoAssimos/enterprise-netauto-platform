"""
automation/workflows/switching/vrrp_workflow.py

VRRP deployment workflow — core switches only.

Configures VRRP groups on VLAN SVIs for gateway redundancy.

core-sw-01: priority 110 (active) for VLANs 10, 20, 99
core-sw-02: priority 90  (standby) for VLANs 10, 20, 99

Virtual IPs:
    VLAN 10: 10.10.10.1
    VLAN 20: 10.20.20.1
    VLAN 99: 10.99.99.1

Prerequisites:
    - VLANs deployed (vlans_workflow)
    - MLAG deployed (mlag_workflow)
    - SVIs must be up before VRRP can activate
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

VRRP_TEMPLATE = "switching/vrrp.j2"


def _vrrp_context(task: Task) -> dict[str, Any]:
    device = task.host.name
    custom_fields = task.host.data.get("custom_fields", {})

    vrrp_groups = custom_fields.get("vrrp_groups")
    if not vrrp_groups:
        log.debug("Skipping device without VRRP config", device=device)
        return {}

    log.debug(
        "VRRP context built",
        device=device,
        group_count=len(vrrp_groups),
    )
    return {"vrrp_groups": vrrp_groups}


def run_vrrp_deploy(nr: Nornir) -> dict[str, Any]:
    """Deploy VRRP on core switch SVIs."""
    log.info("VRRP deploy workflow starting", host_count=len(nr.inventory.hosts))

    core_nr = nr.filter(
        filter_func=lambda h: h.data.get("role") == "core-switch"
    )

    if not core_nr.inventory.hosts:
        log.warning("No core switches found in inventory")
        return {"total": 0, "succeeded": [], "failed": [], "skipped": []}

    log.info(
        "Deploying VRRP",
        devices=list(core_nr.inventory.hosts.keys()),
    )

    results = core_nr.run(
        task=deploy_config,
        template_path=VRRP_TEMPLATE,
        context_builder=_vrrp_context,
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
        "VRRP deploy workflow complete",
        total=summary["total"],
        succeeded=len(succeeded),
        failed=len(failed),
        skipped=len(skipped),
    )
    return summary