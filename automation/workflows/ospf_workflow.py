"""
automation/workflows/ospf_workflow.py

OSPF deployment workflow — multi-platform.

Platform split:
    Cisco IOS XE (rtr-01, rtr-02):
        Template: ospf/process.j2
        Uses network statements for OSPF participation.

    Arista EOS core switches (core-sw-01, core-sw-02):
        Template: ospf/process_eos.j2
        Interface OSPF participation already configured in layer3_eos.j2.
        This workflow only pushes the OSPF process and router-id.

    Access switches (arista-01, arista-02):
        Skipped — no OSPF on access layer.
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

CISCO_OSPF_TEMPLATE = "ospf/process.j2"
EOS_OSPF_TEMPLATE = "ospf/process_eos.j2"


def _cisco_ospf_context(task: Task) -> dict[str, Any]:
    """
    Build OSPF context for Cisco IOS XE devices.
    Requires ospf_process and ospf_networks in custom_fields.
    """
    device = task.host.name
    custom_fields = task.host.data.get("custom_fields", {})

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


def _eos_ospf_context(task: Task) -> dict[str, Any]:
    """
    Build OSPF context for Arista EOS core switches.
    Only requires ospf_process and ospf_router_id.
    Interface-level OSPF is already configured via layer3_eos.j2.
    """
    device = task.host.name
    custom_fields = task.host.data.get("custom_fields", {})

    ospf_process = custom_fields.get("ospf_process")
    if ospf_process is None:
        log.debug("Skipping device without OSPF process", device=device)
        return {}

    context: dict[str, Any] = {
        "ospf_process": int(ospf_process),
        "ospf_router_id": custom_fields.get("ospf_router_id"),
    }

    log.debug(
        "OSPF context built",
        device=device,
        process=ospf_process,
    )
    return context


def run_ospf_deploy(nr: Nornir) -> dict[str, Any]:
    """
    Deploy OSPF across edge routers and core switches.
    Access switches skipped — no OSPF on access layer.
    """
    log.info("OSPF deploy workflow starting", host_count=len(nr.inventory.hosts))

    succeeded: list[str] = []
    failed: list[str] = []

    # Run 1 — Cisco edge routers
    cisco_nr = nr.filter(
        filter_func=lambda h: h.data.get("role") == "edge-router"
    )
    if cisco_nr.inventory.hosts:
        log.info(
            "Deploying Cisco OSPF",
            devices=list(cisco_nr.inventory.hosts.keys()),
        )
        cisco_results = cisco_nr.run(
            task=deploy_config,
            template_path=CISCO_OSPF_TEMPLATE,
            context_builder=_cisco_ospf_context,
            pre_check=pre_check,
            post_check=post_check,
            rollback=rollback_config,
        )
        succeeded += [
            h for h, r in cisco_results.items()
            if not r.failed and not getattr(r[0], 'skipped', False)
        ]
        failed += [h for h, r in cisco_results.items() if r.failed]

    # Run 2 — Arista core switches
    core_nr = nr.filter(
        filter_func=lambda h: h.data.get("role") == "core-switch"
    )
    if core_nr.inventory.hosts:
        log.info(
            "Deploying Arista core OSPF",
            devices=list(core_nr.inventory.hosts.keys()),
        )
        core_results = core_nr.run(
            task=deploy_config,
            template_path=EOS_OSPF_TEMPLATE,
            context_builder=_eos_ospf_context,
            pre_check=pre_check,
            post_check=post_check,
            rollback=rollback_config,
        )
        succeeded += [
            h for h, r in core_results.items()
            if not r.failed and not getattr(r[0], 'skipped', False)
        ]
        failed += [h for h, r in core_results.items() if r.failed]

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
        "OSPF deploy workflow complete",
        total=summary["total"],
        succeeded=len(succeeded),
        failed=len(failed),
        skipped=len(skipped),
    )
    return summary