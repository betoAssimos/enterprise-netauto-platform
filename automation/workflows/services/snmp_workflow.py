"""
automation/workflows/services/snmp_workflow.py

SNMP deployment workflow — all managed devices.

Configures SNMP community and trap source on all 6 devices.

Platform split:
    Cisco IOS XE (rtr-01, rtr-02)              : services/snmp_cisco.j2
    Arista EOS (core + access switches)        : services/snmp_eos.j2
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

CISCO_SNMP_TEMPLATE = "services/snmp_cisco.j2"
EOS_SNMP_TEMPLATE = "services/snmp_eos.j2"


def _snmp_context(task: Task) -> dict[str, Any]:
    device = task.host.name
    custom_fields = task.host.data.get("custom_fields", {})

    snmp = custom_fields.get("snmp")
    if not snmp:
        log.debug("Skipping device without SNMP config", device=device)
        return {}

    context: dict[str, Any] = {
        "snmp_community": snmp["community"],
        "snmp_trap_source": snmp["trap_source"],
    }

    log.debug(
        "SNMP context built",
        device=device,
        community=snmp["community"],
        trap_source=snmp["trap_source"],
    )
    return context


def run_snmp_deploy(nr: Nornir) -> dict[str, Any]:
    """
    Deploy SNMP config on all managed devices.
    Run 1: Cisco edge routers
    Run 2: Arista switches (core + access)
    """
    log.info("SNMP deploy workflow starting", host_count=len(nr.inventory.hosts))

    succeeded: list[str] = []
    failed: list[str] = []

    # Run 1 — Cisco edge routers
    cisco_nr = nr.filter(
        filter_func=lambda h: h.data.get("role") == "edge-router"
    )
    if cisco_nr.inventory.hosts:
        log.info(
            "Deploying Cisco SNMP",
            devices=list(cisco_nr.inventory.hosts.keys()),
        )
        cisco_results = cisco_nr.run(
            task=deploy_config,
            template_path=CISCO_SNMP_TEMPLATE,
            context_builder=_snmp_context,
            pre_check=pre_check,
            post_check=post_check,
            rollback=rollback_config,
        )
        succeeded += [
            h for h, r in cisco_results.items()
            if not r.failed and not getattr(r[0], 'skipped', False)
        ]
        failed += [h for h, r in cisco_results.items() if r.failed]

    # Run 2 — Arista switches (core + access)
    arista_nr = nr.filter(
        filter_func=lambda h: h.data.get("manufacturer") == "Arista"
    )
    if arista_nr.inventory.hosts:
        log.info(
            "Deploying Arista SNMP",
            devices=list(arista_nr.inventory.hosts.keys()),
        )
        arista_results = arista_nr.run(
            task=deploy_config,
            template_path=EOS_SNMP_TEMPLATE,
            context_builder=_snmp_context,
            pre_check=pre_check,
            post_check=post_check,
            rollback=rollback_config,
        )
        succeeded += [
            h for h, r in arista_results.items()
            if not r.failed and not getattr(r[0], 'skipped', False)
        ]
        failed += [h for h, r in arista_results.items() if r.failed]

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
        "SNMP deploy workflow complete",
        total=summary["total"],
        succeeded=len(succeeded),
        failed=len(failed),
        skipped=len(skipped),
    )
    return summary