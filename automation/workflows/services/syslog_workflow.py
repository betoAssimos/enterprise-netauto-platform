"""
automation/workflows/services/syslog_workflow.py

Syslog client deployment workflow — routers and core switches.

Configures syslog on 4 devices pointing to svc-01 (10.20.20.100).
Access switches excluded — no data plane routing to reach svc-01.

Platform split:
    Cisco IOS XE (rtr-01, rtr-02)              : services/syslog_cisco.j2
    Arista EOS (core-sw-01, core-sw-02)        : services/syslog_eos.j2
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

CISCO_SYSLOG_TEMPLATE = "services/syslog_cisco.j2"
EOS_SYSLOG_TEMPLATE = "services/syslog_eos.j2"


def _syslog_context(task: Task) -> dict[str, Any]:
    device = task.host.name
    custom_fields = task.host.data.get("custom_fields", {})

    syslog = custom_fields.get("syslog")
    if not syslog:
        log.debug("Skipping device without syslog config", device=device)
        return {}

    context: dict[str, Any] = {
        "syslog_server": syslog["server"],
        "syslog_trap": syslog["trap"],
        "syslog_source": syslog["source_interface"],
    }

    log.debug(
        "Syslog context built",
        device=device,
        server=syslog["server"],
        trap=syslog["trap"],
    )
    return context


def run_syslog_deploy(nr: Nornir) -> dict[str, Any]:
    """
    Deploy syslog client config on routers and core switches.
    Run 1: Cisco edge routers
    Run 2: Arista core switches
    """
    log.info("Syslog deploy workflow starting", host_count=len(nr.inventory.hosts))

    succeeded: list[str] = []
    failed: list[str] = []

    # Run 1 — Cisco edge routers
    cisco_nr = nr.filter(
        filter_func=lambda h: h.data.get("role") == "edge-router"
    )
    if cisco_nr.inventory.hosts:
        log.info(
            "Deploying Cisco syslog",
            devices=list(cisco_nr.inventory.hosts.keys()),
        )
        cisco_results = cisco_nr.run(
            task=deploy_config,
            template_path=CISCO_SYSLOG_TEMPLATE,
            context_builder=_syslog_context,
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
            "Deploying Arista syslog",
            devices=list(core_nr.inventory.hosts.keys()),
        )
        arista_results = core_nr.run(
            task=deploy_config,
            template_path=EOS_SYSLOG_TEMPLATE,
            context_builder=_syslog_context,
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
        "Syslog deploy workflow complete",
        total=summary["total"],
        succeeded=len(succeeded),
        failed=len(failed),
        skipped=len(skipped),
    )
    return summary