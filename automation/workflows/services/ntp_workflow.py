"""
automation/workflows/services/ntp_workflow.py

NTP client deployment workflow — all managed devices.

Configures NTP server on all 6 devices pointing to svc-01 (10.20.20.100).
No MD5 authentication — BusyBox ntpd on svc-01 does not support
authenticated server mode.

Platform split:
    Cisco IOS XE (rtr-01, rtr-02)        : services/ntp_cisco.j2
    Arista EOS (core + access switches)  : services/ntp_eos.j2
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

CISCO_NTP_TEMPLATE = "services/ntp_cisco.j2"
EOS_NTP_TEMPLATE = "services/ntp_eos.j2"


def _ntp_context(task: Task) -> dict[str, Any]:
    device = task.host.name
    custom_fields = task.host.data.get("custom_fields", {})

    ntp = custom_fields.get("ntp")
    if not ntp:
        log.debug("Skipping device without NTP config", device=device)
        return {}

    context: dict[str, Any] = {
        "ntp_server": ntp["server"],
    }

    log.debug(
        "NTP context built",
        device=device,
        server=ntp["server"],
    )
    return context


def run_ntp_deploy(nr: Nornir) -> dict[str, Any]:
    """
    Deploy NTP client config on all managed devices.
    Run 1: Cisco edge routers
    Run 2: Arista switches (core + access)
    """
    log.info("NTP deploy workflow starting", host_count=len(nr.inventory.hosts))

    succeeded: list[str] = []
    failed: list[str] = []

    # Run 1 — Cisco edge routers
    cisco_nr = nr.filter(
        filter_func=lambda h: h.data.get("role") == "edge-router"
    )
    if cisco_nr.inventory.hosts:
        log.info(
            "Deploying Cisco NTP",
            devices=list(cisco_nr.inventory.hosts.keys()),
        )
        cisco_results = cisco_nr.run(
            task=deploy_config,
            template_path=CISCO_NTP_TEMPLATE,
            context_builder=_ntp_context,
            pre_check=pre_check,
            post_check=post_check,
            rollback=rollback_config,
        )
        succeeded += [
            h for h, r in cisco_results.items()
            if not r.failed and not getattr(r[0], 'skipped', False)
        ]
        failed += [h for h, r in cisco_results.items() if r.failed]

    # Run 2 — Arista switches
    arista_nr = nr.filter(
        filter_func=lambda h: h.data.get("manufacturer") == "Arista"
    )
    if arista_nr.inventory.hosts:
        log.info(
            "Deploying Arista NTP",
            devices=list(arista_nr.inventory.hosts.keys()),
        )
        arista_results = arista_nr.run(
            task=deploy_config,
            template_path=EOS_NTP_TEMPLATE,
            context_builder=_ntp_context,
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
        "NTP deploy workflow complete",
        total=summary["total"],
        succeeded=len(succeeded),
        failed=len(failed),
        skipped=len(skipped),
    )
    return summary