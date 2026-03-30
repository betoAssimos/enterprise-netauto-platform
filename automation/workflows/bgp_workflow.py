"""
automation/workflows/bgp_workflow.py

BGP workflow module.
"""
from __future__ import annotations

from typing import Any

from nornir.core import Nornir
from nornir.core.task import Result, Task

from automation.drift.detector import detect_drift, summarize_drift
from automation.tasks.deploy_config import deploy_config
from automation.utils.logger import get_logger
from automation.validators.checks import post_check, pre_check
from automation.rollback.rollback import rollback_config

log = get_logger(__name__)

BGP_TEMPLATE = "bgp/neighbors.j2"


def bgp_context_builder(task: Task) -> dict[str, Any]:
    device = task.host.name
    custom_fields: dict[str, Any] = task.host.data.get("custom_fields", {})

    bgp_asn = custom_fields.get("bgp_asn")
    if bgp_asn is None:
        log.debug("Skipping device without BGP ASN", device=device)
        return {}

    bgp_neighbors = custom_fields.get("bgp_neighbors", [])
    if not isinstance(bgp_neighbors, list):
        raise ValueError(
            f"Device {device}: bgp_neighbors must be a list, "
            f"got {type(bgp_neighbors).__name__}"
        )

    context: dict[str, Any] = {
        "bgp_asn": int(bgp_asn),
        "neighbors": bgp_neighbors,
    }

    bgp_router_id = custom_fields.get("bgp_router_id")
    if bgp_router_id:
        context["bgp_router_id"] = bgp_router_id
    bgp_networks = custom_fields.get("bgp_networks", [])
    if bgp_networks:
        context["bgp_networks"] = bgp_networks
    context["redistribute_ospf"] = bool(
        custom_fields.get("bgp_redistribute_ospf", False)
    )
    context["redistribute_connected"] = bool(
        custom_fields.get("bgp_redistribute_connected", False)
    )

    log.debug(
        "BGP context built",
        device=device,
        asn=bgp_asn,
        neighbor_count=len(bgp_neighbors),
    )
    return context


def bgp_actual_state(task: Task) -> dict[str, Any]:
    from automation.drift.detector import _config_to_structured

    device = task.host.name
    conn = task.host.get_connection("scrapli", task.nornir.config)

    log.debug("Retrieving actual BGP config", device=device)
    response = conn.send_command("show running-config | section router bgp")

    if response.failed or not response.result.strip():
        log.warning("No BGP config section found on device", device=device)
        return {}

    return _config_to_structured(response.result)


def run_bgp_deploy(nr: Nornir) -> dict[str, Any]:
    log.info("BGP deploy workflow starting", host_count=len(nr.inventory.hosts))

    results = nr.run(
        task=deploy_config,
        template_path=BGP_TEMPLATE,
        context_builder=bgp_context_builder,
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
        "BGP deploy workflow complete",
        total=summary["total"],
        succeeded=len(succeeded),
        failed=len(failed),
        skipped=len(skipped),
    )
    return summary


def run_bgp_drift_check(nr: Nornir) -> dict[str, Any]:
    log.info("BGP drift check starting", host_count=len(nr.inventory.hosts))

    results = nr.run(
        task=detect_drift,
        template_path=BGP_TEMPLATE,
        context_builder=bgp_context_builder,
        actual_state_getter=bgp_actual_state,
    )

    summary = summarize_drift(results)

    log.info(
        "BGP drift check complete",
        total=summary["total_devices"],
        drifted=summary["drifted_devices"],
        critical=summary["critical"],
        major=summary["major"],
        minor=summary["minor"],
    )
    return summary