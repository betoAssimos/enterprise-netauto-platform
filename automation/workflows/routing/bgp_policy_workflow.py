"""
automation/workflows/routing/bgp_policy_workflow.py

BGP routing policy workflow — deploys prefix lists and route maps.
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

BGP_POLICY_TEMPLATE = "routing/bgp/policy.j2"


def bgp_policy_context_builder(task: Task) -> dict[str, Any]:
    device = task.host.name
    custom_fields: dict[str, Any] = task.host.data.get("custom_fields", {})

    prefix_lists = custom_fields.get("bgp_prefix_lists", [])
    route_maps = custom_fields.get("bgp_route_maps", [])

    if not prefix_lists and not route_maps:
        log.debug("Skipping device without BGP policy data", device=device)
        return {}

    context: dict[str, Any] = {
        "prefix_lists": prefix_lists,
        "route_maps": route_maps,
    }

    log.debug(
        "BGP policy context built",
        device=device,
        prefix_list_count=len(prefix_lists),
        route_map_count=len(route_maps),
    )
    return context


def run_bgp_policy_deploy(nr: Nornir) -> dict[str, Any]:
    log.info("BGP policy deploy workflow starting", host_count=len(nr.inventory.hosts))

    results = nr.run(
        task=deploy_config,
        template_path=BGP_POLICY_TEMPLATE,
        context_builder=bgp_policy_context_builder,
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
        h for h, r in results.items()
        if getattr(r[0], 'skipped', False)
    ]

    summary = {
        "total": len(nr.inventory.hosts),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
    }

    log.info(
        "BGP policy deploy workflow complete",
        total=summary["total"],
        succeeded=len(succeeded),
        failed=len(failed),
        skipped=len(skipped),
    )
    return summary