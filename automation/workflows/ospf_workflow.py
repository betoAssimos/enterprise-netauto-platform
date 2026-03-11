"""
automation/workflows/ospf_workflow.py

OSPF deployment workflow.
Reads ospf_* custom fields from inventory and pushes OSPF process config.
"""
from __future__ import annotations
from typing import Any

from nornir.core import Nornir
from nornir.core.task import Result, Task

from automation.tasks.deploy_config import deploy_config
from automation.utils.logger import get_logger
from automation.validators.checks import post_check, pre_check
from automation.rollback.rollback import rollback_config

log = get_logger(__name__)

OSPF_TEMPLATE = "ospf/process.j2"


def ospf_context_builder(task: Task) -> dict[str, Any]:
    device = task.host.name
    custom_fields: dict[str, Any] = task.host.data.get("custom_fields", {})

    ospf_process = custom_fields.get("ospf_process")
    if ospf_process is None:
        log.debug("Skipping device without OSPF process", device=device)
        return {}

    ospf_networks = custom_fields.get("ospf_networks", [])
    if not ospf_networks:
        log.debug("Skipping device without OSPF networks", device=device)
        return {}

    context: dict[str, Any] = {
        "ospf_process": int(ospf_process),
        "ospf_router_id": custom_fields.get("ospf_router_id"),
        "ospf_networks": ospf_networks,
    }

    ospf_redistribute_bgp = custom_fields.get("ospf_redistribute_bgp")
    if ospf_redistribute_bgp:
        context["ospf_redistribute_bgp"] = int(ospf_redistribute_bgp)

    log.debug(
        "OSPF context built",
        device=device,
        process=ospf_process,
        network_count=len(ospf_networks),
    )
    return context


def run_ospf_deploy(nr: Nornir) -> dict[str, Any]:
    log.info("OSPF deploy workflow starting", host_count=len(nr.inventory.hosts))

    results = nr.run(
        task=deploy_config,
        template_path=OSPF_TEMPLATE,
        context_builder=ospf_context_builder,
        pre_check=pre_check,
        post_check=post_check,
        rollback=rollback_config,
    )

    succeeded = [h for h, r in results.items() if not r.failed]
    failed = [h for h, r in results.items() if r.failed]

    summary = {
        "total": len(nr.inventory.hosts),
        "succeeded": succeeded,
        "failed": failed,
    }

    log.info(
        "OSPF deploy workflow complete",
        total=summary["total"],
        succeeded=len(succeeded),
        failed=len(failed),
    )
    return summary