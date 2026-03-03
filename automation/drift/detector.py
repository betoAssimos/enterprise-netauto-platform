"""
automation/drift/detector.py

Drift Detection Engine.

Compares desired state (rendered from Nautobot via Jinja2) against
actual state (parsed from live device via Genie) and reports divergence.

Design:
- Desired state = rendered Jinja2 config parsed into structured dict
- Actual state  = Genie-parsed running config from device
- Drift computed with DeepDiff for structured, deterministic comparison
- Results classified by severity: NONE / MINOR / MAJOR / CRITICAL
- Detection is read-only — no changes are made to any device
- Remediation is a separate decision gate, never automatic from here
- Results published as structured log events and returned for metrics
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from deepdiff import DeepDiff
from nornir.core.task import Result, Task

from automation.templates.renderer import renderer
from automation.utils.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------


class DriftSeverity(str, Enum):
    NONE = "none"
    MINOR = "minor"       # Values changed, structure intact
    MAJOR = "major"       # Keys added or removed
    CRITICAL = "critical" # Entire config section missing


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class DriftResult:
    """Structured drift finding for one device."""

    device: str
    severity: DriftSeverity = DriftSeverity.NONE
    diffs: dict[str, Any] = field(default_factory=dict)
    desired_config: str = ""
    actual_config: str = ""
    remediation_required: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "severity": self.severity.value,
            "diffs": self.diffs,
            "remediation_required": self.remediation_required,
        }

    def is_clean(self) -> bool:
        return self.severity == DriftSeverity.NONE


# ---------------------------------------------------------------------------
# Nornir task: detect drift for one device
# ---------------------------------------------------------------------------


def detect_drift(
    task: Task,
    template_path: str,
    context_builder: Any,
    actual_state_getter: Any,
) -> Result:
    """
    Nornir task: detect configuration drift for one device.

    Parameters
    ----------
    task : Task
        Nornir task object injected by the runner.
    template_path : str
        Jinja2 template defining desired state.
        Example: "bgp/neighbors.j2"
    context_builder : Callable[[Task], dict]
        Builds template variables from Nautobot data in task.host.data.
        Provided by workflow modules.
    actual_state_getter : Callable[[Task], dict]
        Retrieves parsed running state from the live device.
        Must return the same structure as the desired state dict.

    Returns
    -------
    Result
        result["drift"] = DriftResult instance
    """
    device = task.host.name
    log.info("Drift detection starting", device=device, template=template_path)

    # ── Desired state ─────────────────────────────────────────────────────
    try:
        context = context_builder(task)
        desired_config = renderer.render(template_path, context)
        desired_state = _config_to_structured(desired_config)
        log.debug(
            "Desired state built",
            device=device,
            sections=len(desired_state),
        )
    except Exception as exc:
        log.error("Failed to build desired state", device=device, error=str(exc))
        return Result(host=task.host, failed=True, exception=exc)

    # ── Actual state ──────────────────────────────────────────────────────
    try:
        actual_state = actual_state_getter(task)
        log.debug(
            "Actual state retrieved",
            device=device,
            sections=len(actual_state),
        )
    except Exception as exc:
        log.error("Failed to retrieve actual state", device=device, error=str(exc))
        return Result(host=task.host, failed=True, exception=exc)

    # ── Compute drift ─────────────────────────────────────────────────────
    drift = _compute_drift(device, desired_state, actual_state, desired_config)

    if drift.is_clean():
        log.info("No drift detected", device=device)
    else:
        log.warning(
            "Drift detected",
            device=device,
            severity=drift.severity.value,
            diff_count=len(drift.diffs),
            remediation_required=drift.remediation_required,
        )

    return Result(host=task.host, result={"drift": drift})


# ---------------------------------------------------------------------------
# Drift computation
# ---------------------------------------------------------------------------


def _compute_drift(
    device: str,
    desired: dict[str, Any],
    actual: dict[str, Any],
    desired_config: str,
) -> DriftResult:
    """Run DeepDiff and classify severity."""
    diff = DeepDiff(
        desired,
        actual,
        ignore_order=True,
        report_repetition=False,
        verbose_level=1,
    )

    if not diff:
        return DriftResult(
            device=device,
            severity=DriftSeverity.NONE,
            desired_config=desired_config,
        )

    diff_dict = diff.to_dict()
    severity = _classify_severity(diff_dict)

    return DriftResult(
        device=device,
        severity=severity,
        diffs=diff_dict,
        desired_config=desired_config,
        remediation_required=severity in (
            DriftSeverity.MAJOR,
            DriftSeverity.CRITICAL,
        ),
    )


def _classify_severity(diff_dict: dict[str, Any]) -> DriftSeverity:
    """
    Map DeepDiff output categories to DriftSeverity.

    DeepDiff categories used:
        type_changes                          → CRITICAL
        dictionary_item_added/removed         → MAJOR
        iterable_item_added/removed           → MAJOR
        values_changed                        → MINOR
    """
    if "type_changes" in diff_dict:
        return DriftSeverity.CRITICAL
    if (
        "dictionary_item_added" in diff_dict
        or "dictionary_item_removed" in diff_dict
    ):
        return DriftSeverity.MAJOR
    if (
        "iterable_item_added" in diff_dict
        or "iterable_item_removed" in diff_dict
    ):
        return DriftSeverity.MAJOR
    if "values_changed" in diff_dict:
        return DriftSeverity.MINOR
    return DriftSeverity.NONE


def _config_to_structured(raw_config: str) -> dict[str, list[str]]:
    """
    Convert rendered IOS-XE config text into a structured dict
    for deterministic comparison.

    Sections are top-level stanzas (lines with no leading whitespace).
    Lines within a section are stored as a sorted list.

    Example:
        "router bgp 65001\\n neighbor 1.1.1.1 remote-as 65002"
        → {"router bgp 65001": ["neighbor 1.1.1.1 remote-as 65002"]}
    """
    structured: dict[str, list[str]] = {}
    current_section: str | None = None

    for raw_line in raw_config.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("!"):
            continue

        if not raw_line.startswith(" "):
            current_section = line
            structured[current_section] = []
        else:
            if current_section is not None:
                structured[current_section].append(line)

    return {
        section: sorted(lines)
        for section, lines in structured.items()
    }


# ---------------------------------------------------------------------------
# Aggregate drift results across all devices
# ---------------------------------------------------------------------------


def summarize_drift(nornir_results: Any) -> dict[str, Any]:
    """
    Aggregate DriftResult objects from a Nornir AggregatedResult.

    Returns a summary dict suitable for:
    - Prometheus gauge updates
    - CI exit code decisions
    - Grafana dashboard ingestion
    - Structured log output

    Parameters
    ----------
    nornir_results : AggregatedResult
        The return value of nr.run(task=detect_drift, ...)

    Returns
    -------
    dict with keys:
        total_devices, drifted_devices, no_drift,
        minor, major, critical, failed, devices
    """
    summary: dict[str, Any] = {
        "total_devices": 0,
        "drifted_devices": 0,
        "no_drift": 0,
        "minor": 0,
        "major": 0,
        "critical": 0,
        "failed": 0,
        "devices": {},
    }

    for device_name, multi_result in nornir_results.items():
        summary["total_devices"] += 1
        host_result = multi_result[0]

        if host_result.failed or not host_result.result:
            summary["failed"] += 1
            summary["devices"][device_name] = {"severity": "error"}
            continue

        drift: DriftResult = host_result.result.get("drift")
        if drift is None:
            summary["failed"] += 1
            summary["devices"][device_name] = {"severity": "error"}
            continue

        summary["devices"][device_name] = drift.as_dict()

        if drift.severity == DriftSeverity.NONE:
            summary["no_drift"] += 1
        elif drift.severity == DriftSeverity.MINOR:
            summary["minor"] += 1
            summary["drifted_devices"] += 1
        elif drift.severity == DriftSeverity.MAJOR:
            summary["major"] += 1
            summary["drifted_devices"] += 1
        elif drift.severity == DriftSeverity.CRITICAL:
            summary["critical"] += 1
            summary["drifted_devices"] += 1

    return summary