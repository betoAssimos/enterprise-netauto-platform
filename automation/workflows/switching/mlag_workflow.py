"""
automation/workflows/switching/mlag_workflow.py

MLAG domain deployment workflow — core switches only.

Configures:
    - VLAN 4094 SVI as MLAG peer-link L3 interface
    - MLAG domain (domain-id, local-interface, peer-address, peer-link)
    - Spanning tree exclusion for VLAN 4094

Prerequisites:
    - VLANs deployed (vlans_workflow)
    - Port-channels deployed (portchannels_workflow)
    - Port-Channel1 (peer-link) must be up before MLAG converges
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

MLAG_TEMPLATE = "switching/mlag.j2"


def _mlag_context(task: Task) -> dict[str, Any]:
    device = task.host.name
    custom_fields = task.host.data.get("custom_fields", {})

    mlag_domain_id = custom_fields.get("mlag_domain_id")
    mlag_peer_link = custom_fields.get("mlag_peer_link")
    mlag_local_ip = custom_fields.get("mlag_local_ip")
    mlag_peer_ip = custom_fields.get("mlag_peer_ip")

    if not all([mlag_domain_id, mlag_peer_link, mlag_local_ip, mlag_peer_ip]):
        log.debug("Skipping device without MLAG config", device=device)
        return {}

    log.debug(
        "MLAG context built",
        device=device,
        domain_id=mlag_domain_id,
        role=custom_fields.get("mlag_role"),
    )
    return {
        "mlag_domain_id": mlag_domain_id,
        "mlag_peer_link": mlag_peer_link,
        "mlag_local_ip": mlag_local_ip,
        "mlag_peer_ip": mlag_peer_ip,
    }


def run_mlag_deploy(nr: Nornir) -> dict[str, Any]:
    """Deploy MLAG domain configuration on core switches only."""
    log.info("MLAG deploy workflow starting", host_count=len(nr.inventory.hosts))

    core_nr = nr.filter(
        filter_func=lambda h: h.data.get("role") == "core-switch"
    )

    if not core_nr.inventory.hosts:
        log.warning("No core switches found in inventory")
        return {"total": 0, "succeeded": [], "failed": [], "skipped": []}

    log.info(
        "Deploying MLAG",
        devices=list(core_nr.inventory.hosts.keys()),
    )

    results = core_nr.run(
        task=deploy_config,
        template_path=MLAG_TEMPLATE,
        context_builder=_mlag_context,
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
        "MLAG deploy workflow complete",
        total=summary["total"],
        succeeded=len(succeeded),
        failed=len(failed),
        skipped=len(skipped),
    )
    return summary