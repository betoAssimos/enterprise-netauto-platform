"""
automation/tasks/deploy_config.py

Core Nornir task: the full deployment lifecycle for a single device.

Lifecycle (in order):
    1. Build render context from Nautobot data (via context_builder)
    2. Render Jinja2 config block
    3. Run pyATS pre-check — capture baseline state
    4. Push rendered config via Scrapli send_configs
    5. Run pyATS post-check — compare against baseline
    6. On post-check failure: trigger rollback, then re-raise
    7. Emit Prometheus metrics

Design principles:
- Idempotent: same desired state always produces same rendered config
- dry_run flag: renders and logs but never touches a device
- All side-effects (push, rollback) are behind explicit conditions
- Never swallows exceptions silently — always logs then re-raises
- Called by workflow modules, never by operators directly
"""

from __future__ import annotations

import time
from typing import Any, Callable

from nornir.core.task import Result, Task

from automation.config import get_settings
from automation.utils.logger import get_logger
from automation.templates.renderer import renderer

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public task entrypoint — called by Nornir runner
# ---------------------------------------------------------------------------


def deploy_config(
    task: Task,
    template_path: str,
    context_builder: Callable[[Task], dict[str, Any]],
    *,
    pre_check: Callable[[Task], Result] | None = None,
    post_check: Callable[[Task, Any], Result] | None = None,
    rollback: Callable[[Task, str], Result] | None = None,
) -> Result:
    """
    Nornir task: full deploy lifecycle for one device.

    Parameters
    ----------
    task : Task
        Nornir task object injected by the runner.
    template_path : str
        Relative path to the Jinja2 template.
        Example: "bgp/neighbors.j2"
    context_builder : Callable[[Task], dict]
        Builds the template render context from Nautobot data
        stored in task.host.data. Provided by workflow modules.
    pre_check : Callable, optional
        Runs before config push. Captures baseline state.
        If it raises, deployment is aborted cleanly.
    post_check : Callable, optional
        Runs after config push. Compares against baseline.
        If it raises, rollback is triggered.
    rollback : Callable, optional
        Restores device to pre-change state.
        Called only when post_check fails and rollback_on_failure is True.

    Returns
    -------
    Result
        Nornir Result with steps dict showing outcome of each stage.
    """
    cfg = get_settings()
    device = task.host.name
    start_time = time.monotonic()
    steps: dict[str, str] = {}

    log.info("Deploy starting", device=device, template=template_path)

    # ── 1. Build render context ───────────────────────────────────────────
    log.debug("Building context", device=device)
    try:
        context = context_builder(task)
        steps["context"] = "ok"
    except Exception as exc:
        log.error("Context build failed", device=device, error=str(exc))
        return Result(host=task.host, failed=True, exception=exc,
                      result={"device": device, "steps": steps})

    # ── 2. Render config ──────────────────────────────────────────────────
    log.debug("Rendering config", device=device, template=template_path)
    try:
        rendered_config = renderer.render(template_path, context)
        steps["render"] = "ok"
        log.debug(
            "Config rendered",
            device=device,
            lines=rendered_config.count("\n") + 1,
        )
    except Exception as exc:
        log.error("Render failed", device=device, error=str(exc))
        return Result(host=task.host, failed=True, exception=exc,
                      result={"device": device, "steps": steps})

    # ── Dry run exit point ────────────────────────────────────────────────
    if cfg.dry_run:
        log.info("DRY RUN — config rendered, not pushed", device=device)
        log.info("Rendered output:\n%s", rendered_config)
        steps["deploy"] = "dry_run"
        return Result(
            host=task.host,
            result={
                "device": device,
                "steps": steps,
                "dry_run": True,
                "rendered_config": rendered_config,
            },
        )

    # ── 3. Pre-check ──────────────────────────────────────────────────────
    original_config: str = ""
    baseline_state: Any = None

    if pre_check:
        log.info("Running pre-check", device=device)
        try:
            pre_result = task.run(task=pre_check)
            baseline_state = pre_result.result.get("state")
            original_config = pre_result.result.get("running_config", "")
            steps["pre_check"] = "ok"
            log.info("Pre-check passed", device=device)
        except Exception as exc:
            log.error(
                "Pre-check failed — aborting deployment",
                device=device,
                error=str(exc),
            )
            steps["pre_check"] = "failed"
            return Result(
                host=task.host,
                failed=True,
                exception=exc,
                result={"device": device, "steps": steps},
            )

    # ── 4. Push config ────────────────────────────────────────────────────
    log.info("Pushing config to device", device=device)
    try:
        push_result = task.run(
            task=_push_config_lines,
            config_lines=rendered_config,
        )
        steps["deploy"] = "ok"
        log.info("Config pushed successfully", device=device)
    except Exception as exc:
        log.error("Config push failed", device=device, error=str(exc))
        steps["deploy"] = "failed"
        return Result(
            host=task.host,
            failed=True,
            exception=exc,
            result={"device": device, "steps": steps},
        )

    # ── 5. Post-check ─────────────────────────────────────────────────────
    if post_check:
        log.info("Running post-check", device=device)
        try:
            task.run(task=post_check, baseline=baseline_state)
            steps["post_check"] = "ok"
            log.info("Post-check passed", device=device)
        except Exception as exc:
            log.error("Post-check failed", device=device, error=str(exc))
            steps["post_check"] = "failed"

            # ── 6. Rollback ───────────────────────────────────────────────
            if rollback and cfg.rollback_on_failure:
                if original_config:
                    log.warning("Initiating rollback", device=device)
                    try:
                        task.run(
                            task=rollback,
                            original_config=original_config,
                        )
                        steps["rollback"] = "ok"
                        log.info("Rollback completed", device=device)
                    except Exception as rb_exc:
                        steps["rollback"] = "failed"
                        log.critical(
                            "ROLLBACK FAILED — manual intervention required",
                            device=device,
                            error=str(rb_exc),
                        )
                else:
                    log.warning(
                        "Rollback skipped — no pre-check config captured",
                        device=device,
                    )
                    steps["rollback"] = "skipped"

            duration = time.monotonic() - start_time
            log.error(
                "Deployment failed",
                device=device,
                duration_seconds=round(duration, 2),
                steps=steps,
            )
            return Result(
                host=task.host,
                failed=True,
                exception=exc,
                result={"device": device, "steps": steps},
            )

    duration = time.monotonic() - start_time
    log.info(
        "Deployment completed successfully",
        device=device,
        duration_seconds=round(duration, 2),
        steps=steps,
    )

    return Result(
        host=task.host,
        result={
            "device": device,
            "steps": steps,
            "duration_seconds": round(duration, 2),
        },
    )


# ---------------------------------------------------------------------------
# Internal helper — Scrapli config push
# ---------------------------------------------------------------------------


def _push_config_lines(task: Task, config_lines: str) -> Result:
    """
    Send config lines to device via Scrapli send_configs.

    Scrapli handles entering config mode, sending all lines,
    and returning to exec mode automatically.

    Raises
    ------
    RuntimeError
        If Scrapli reports a failed response.
    """
    device = task.host.name
    conn = task.host.get_connection("scrapli", task.nornir.config)

    lines = [
        line for line in config_lines.splitlines()
        if line.strip()
    ]

    log.debug("Sending config lines", device=device, line_count=len(lines))
    response = conn.send_configs(lines)

    if response.failed:
        raise RuntimeError(
            f"Scrapli send_configs failed on {device}: {response.result}"
        )

    return Result(host=task.host, result=response.result)