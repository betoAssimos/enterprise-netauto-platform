"""
automation/tasks/deploy_interfaces.py

Nornir task: render and push interface configuration.

Renders a Jinja2 interface template using data supplied by the workflow
via task.host.data["interfaces"], then pushes the rendered config to
the device via Scrapli.

The template path is passed by the workflow to support multiple platforms:
    interfaces/layer3.j2     — Cisco IOS XE
    interfaces/layer3_eos.j2 — Arista EOS

Called by:
    automation/workflows/deploy_interfaces_workflow.py
"""
from __future__ import annotations

from nornir.core.task import Result, Task

from automation.templates.renderer import renderer
from automation.utils.logger import get_logger

log = get_logger(__name__)


def deploy_interfaces(
    task: Task,
    template_path: str = "interfaces/layer3.j2",
) -> Result:
    """
    Render interface config and push to device via Scrapli.

    Expects task.host.data["interfaces"] to be a list of dicts.
    The required keys depend on the template being used.

    Parameters
    ----------
    task : Task
        Nornir task object.
    template_path : str
        Relative path to the Jinja2 template.
        Default: interfaces/layer3.j2 (Cisco IOS XE)
    """
    device = task.host.name
    interfaces = task.host.data.get("interfaces")

    if not interfaces:
        log.debug("No interface data defined — skipping", device=device)
        return Result(host=task.host, skipped=True)

    # ── Render ─────────────────────────────────────────────────────────────
    log.debug(
        "Rendering interface config",
        device=device,
        template=template_path,
        interface_count=len(interfaces),
    )

    rendered_config = renderer.render(
        template_path,
        context={"interfaces": interfaces},
    )

    log.debug(
        "Interface config rendered",
        device=device,
        lines=rendered_config.count("\n") + 1,
    )

    # ── Push via Scrapli ───────────────────────────────────────────────────
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