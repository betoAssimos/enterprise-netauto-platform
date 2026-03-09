"""
automation/tasks/deploy_interfaces.py

Nornir task: render and push Layer 3 interface configuration.

Renders the interfaces/layer3.j2 template using interface data
supplied by the workflow via task.host.data["interfaces"], then
pushes the rendered config block to the device via Scrapli.

Design:
- Uses the platform renderer singleton (not a bare render_template call)
- Uses Scrapli send_configs (consistent with deploy_config.py)
- Skips devices that have no interface data defined
- Raises RuntimeError on Scrapli failure so the workflow can handle it
- Never enters config mode manually — Scrapli handles that

Called by:
    automation/workflows/deploy_interfaces_workflow.py
"""

from __future__ import annotations

from nornir.core.task import Result, Task

from automation.templates.renderer import renderer
from automation.utils.logger import get_logger

log = get_logger(__name__)

INTERFACE_TEMPLATE = "interfaces/layer3.j2"


def deploy_interfaces(task: Task) -> Result:
    """
    Render Layer 3 interface config and push to device via Scrapli.

    Expects task.host.data["interfaces"] to be a list of dicts, each:
        name        (str)  : Interface name, e.g. GigabitEthernet2
        ip_address  (str)  : CIDR notation,  e.g. 10.0.0.1/30
        description (str)  : Interface description
        ospf_area   (str)  : Optional — OSPF area, e.g. "0"
        ospf_process(str)  : Optional — OSPF process ID, default "1"
        shutdown    (bool) : Optional — admin-down state, default false

    Returns
    -------
    Result
        Nornir Result with rendered config and push output.
    """
    device = task.host.name
    interfaces = task.host.data.get("interfaces")

    if not interfaces:
        log.debug(
            "No interface data defined — skipping device",
            device=device,
        )
        return Result(host=task.host, skipped=True)

    # ── Render ────────────────────────────────────────────────────────────
    log.debug(
        "Rendering interface config",
        device=device,
        interface_count=len(interfaces),
    )

    rendered_config = renderer.render(
        INTERFACE_TEMPLATE,
        context={"interfaces": interfaces},
    )

    log.debug(
        "Interface config rendered",
        device=device,
        lines=rendered_config.count("\n") + 1,
    )

    # ── Push via Scrapli ──────────────────────────────────────────────────
    log.info("Pushing interface config", device=device)
    conn = task.host.get_connection("scrapli", task.nornir.config)

    config_lines = [
        line for line in rendered_config.splitlines()
        if line.strip()
    ]

    response = conn.send_configs(config_lines)

    if response.failed:
        raise RuntimeError(
            f"Scrapli send_configs failed on {device}: {response.result}"
        )

    log.info("Interface config pushed successfully", device=device)
    return Result(
        host=task.host,
        result={
            "device": device,
            "rendered_config": rendered_config,
            "output": response.result,
        },
    )