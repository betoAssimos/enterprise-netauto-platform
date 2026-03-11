"""
automation/workflows/nat_workflow.py

NAT overload (PAT) deployment workflow.
Reads nat_* custom fields from inventory and pushes NAT ACL + overload config.
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

NAT_TEMPLATE = "nat/nat_overload.j2"


def nat_context_builder(task: Task) -> dict[str, Any]:
    device = task.host.name
    custom_fields: dict[str, Any] = task.host.data.get("custom_fields", {})

    nat_outside = custom_fields.get("nat_outside_interface")
    nat_acl_entries = custom_fields.get("nat_acl_entries", [])

    if not nat_outside or not nat_acl_entries:
        log.debug("Skipping device without NAT config", device=device)
        return {}

    context: dict[str, Any] = {
        "nat_outside_interface": nat_outside,
        "nat_inside_interface": custom_fields.get("nat_inside_interface"),
        "nat_acl_entries": nat_acl_entries,
    }

    log.debug(
        "NAT context built",
        device=device,
        outside=nat_outside,
        acl_entries=len(nat_acl_entries),
    )
    return context


def run_nat_deploy(nr: Nornir) -> dict[str, Any]:
    log.info("NAT deploy workflow starting", host_count=len(nr.inventory.hosts))

    results = nr.run(
        task=deploy_config,
        template_path=NAT_TEMPLATE,
        context_builder=nat_context_builder,
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
        "NAT deploy workflow complete",
        total=summary["total"],
        succeeded=len(succeeded),
        failed=len(failed),
    )
    return summary