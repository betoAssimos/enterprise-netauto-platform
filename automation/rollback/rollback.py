"""
automation/rollback/rollback.py

Configuration rollback engine.

Triggered automatically by deploy_config when post-check fails,
or manually by operators via the CLI entrypoint.

Design:
- Restores from pre-check running-config snapshot
- Archives original config locally before every rollback attempt
- Never silently swallows errors — logs then re-raises
- Archive path configurable via ROLLBACK_ARCHIVE_DIR env variable
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from nornir.core.task import Result, Task

from automation.utils.logger import get_logger

log = get_logger(__name__)

_ARCHIVE_DIR = Path(os.getenv("ROLLBACK_ARCHIVE_DIR", "/tmp/rollback_archive"))


def rollback_config(task: Task, original_config: str) -> Result:
    """
    Nornir task: restore a device to its pre-change configuration.

    Parameters
    ----------
    original_config : str
        Raw running-config string captured during pre-check.

    Raises
    ------
    ValueError
        If original_config is empty.
    RuntimeError
        If the Scrapli config push reports failure.
    """
    device = task.host.name

    if not original_config.strip():
        raise ValueError(
            f"Rollback aborted for {device}: original_config is empty."
        )

    log.warning("Rollback initiated", device=device)

    _archive_config(device, original_config)

    try:
        task.run(
            task=_push_rollback_config,
            original_config=original_config,
        )
        log.info("Rollback completed successfully", device=device)
        return Result(host=task.host, result={"rollback": "ok", "device": device})
    except Exception as exc:
        log.critical(
            "ROLLBACK FAILED — manual intervention required",
            device=device,
            error=str(exc),
        )
        raise


def _push_rollback_config(task: Task, original_config: str) -> Result:
    """Push original config back to device via Scrapli."""
    device = task.host.name
    conn = task.host.get_connection("scrapli", task.nornir.config)

    config_lines = [
        line for line in original_config.splitlines()
        if line.strip() and not line.strip().startswith("!")
    ]

    log.debug("Pushing rollback config", device=device, line_count=len(config_lines))
    response = conn.send_configs(config_lines)

    if response.failed:
        raise RuntimeError(
            f"Scrapli rollback push failed on {device}: {response.result}"
        )

    return Result(host=task.host, result=response.result)


def _archive_config(device: str, config: str) -> None:
    """
    Write pre-rollback config to local archive for audit trail.
    Archive failure is logged but never blocks the rollback itself.
    In production replace with S3 or network share push.
    """
    try:
        _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        config_hash = hashlib.sha256(config.encode()).hexdigest()[:8]
        filename = f"{device}__{timestamp}__{config_hash}.cfg"
        archive_path = _ARCHIVE_DIR / filename
        archive_path.write_text(config, encoding="utf-8")
        log.info("Config archived", device=device, path=str(archive_path))
    except Exception as exc:
        log.warning(
            "Config archive failed — rollback will still proceed",
            device=device,
            error=str(exc),
        )