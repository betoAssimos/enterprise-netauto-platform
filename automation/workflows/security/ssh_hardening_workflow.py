"""
automation/workflows/security/ssh_hardening_workflow.py

SSH hardening workflow — deploys SSH and VTY line configuration.
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

SSH_CISCO_TEMPLATE = "security/ssh_cisco.j2"


def ssh_context_builder(task: Task) -> dict[str, Any]:
    device = task.host.name
    custom_fields: dict[str, Any] = task.host.data.get("custom_fields", {})

    ssh = custom_fields.get("ssh")
    if not ssh:
        log.debug("Skipping device without SSH config", device=device)
        return {}

    context: dict[str, Any] = {
        "ssh_version": ssh["version"],
        "vty_lines": ssh["vty_lines"],
        "transport_input": ssh["transport_input"],
    }

    log.debug(
        "SSH context built",
        device=device,
        ssh_version=ssh["version"],
        transport_input=ssh["transport_input"],
    )
    return context


def run_ssh_deploy(nr: Nornir) -> dict[str, Any]:
    log.info("SSH hardening deploy workflow starting", host_count=len(nr.inventory.hosts))

    results = nr.run(
        task=deploy_config,
        template_path=SSH_CISCO_TEMPLATE,
        context_builder=ssh_context_builder,
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
        "SSH hardening deploy workflow complete",
        total=summary["total"],
        succeeded=len(succeeded),
        failed=len(failed),
        skipped=len(skipped),
    )
    return summary