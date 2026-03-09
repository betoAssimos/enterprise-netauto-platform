"""
automation/workflows/deploy_interfaces_workflow.py

Layer 3 interface deployment workflow.

Renders and pushes interface addressing, OSPF participation, and
admin state for all devices that have interface data defined.

Interface topology is defined here as the authoritative lab source,
consistent with the fixed Containerlab topology in containerlab/topology.yml.
In a production environment this data would be sourced from NetBox
(dcim.interfaces + ipam.ip-addresses) and injected via the inventory
generator.

Devices covered:
    rtr-01  GigabitEthernet2  10.0.0.1/30   eBGP peering link (OSPF area 0)
            GigabitEthernet3  10.1.1.1/30   internal / NAT inside (OSPF area 0)
            Loopback0         1.1.1.1/32    router-id / BGP update-source

    rtr-02  GigabitEthernet2  10.0.0.2/30   eBGP peering link (OSPF area 0)
            GigabitEthernet3  10.2.2.1/30   internal / NAT inside (OSPF area 0)
            Loopback0         2.2.2.2/32    router-id / BGP update-source

Usage (standalone):
    python automation/workflows/deploy_interfaces_workflow.py

Usage (via runner — after runner.py is extended):
    python automation/runner.py deploy interfaces

Design:
    - Follows the same task/workflow split as bgp_workflow.py
    - Pre-check captures interface state before push
    - Post-check verifies all target interfaces reach up/up state
    - Interface data injected into host data at runtime — hosts.yaml
      is not modified (it is a generated artifact from NetBox)
    - Portable path resolution — no hardcoded absolute paths
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pyats import results
from pyats import results

# ── Bootstrap: ensure project root is on the path ────────────────────────
BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

from nornir import InitNornir                           # noqa: E402
from nornir.core import Nornir                          # noqa: E402
from nornir.core.task import Result, Task               # noqa: E402

from automation.tasks.deploy_interfaces import deploy_interfaces  # noqa: E402
from automation.utils.logger import get_logger          # noqa: E402

log = get_logger(__name__)

# ── Interface topology data ───────────────────────────────────────────────
# Source of truth for lab interface addressing.
# Matches containerlab/configs/rtr-{01,02}-running.cfg exactly.
# Keys match Nornir host names in automation/inventory/hosts.yaml.

INTERFACE_DATA: dict[str, list[dict[str, Any]]] = {
    "rtr-01": [
        {
            "name": "Loopback0",
            "ip_address": "1.1.1.1/32",
            "description": "Router-ID / BGP update-source",
        },
        {
            "name": "GigabitEthernet2",
            "ip_address": "10.0.0.1/30",
            "description": "eBGP peering link to rtr-02",
            "ospf_area": "0",
            "ospf_process": "1",
        },
        {
            "name": "GigabitEthernet3",
            "ip_address": "10.1.1.1/30",
            "description": "Internal / NAT inside",
            "ospf_area": "0",
            "ospf_process": "1",
        },
        
    ],
    "rtr-02": [
        {
            "name": "Loopback0",
            "ip_address": "2.2.2.2/32",
            "description": "Router-ID / BGP update-source",
        },
        {
            "name": "GigabitEthernet2",
            "ip_address": "10.0.0.2/30",
            "description": "eBGP peering link to rtr-01",
            "ospf_area": "0",
            "ospf_process": "1",
        },
        {
            "name": "GigabitEthernet3",
            "ip_address": "10.2.2.1/30",
            "description": "Internal / NAT inside",
            "ospf_area": "0",
            "ospf_process": "1",
        },
    ],
}

# Interfaces that must be up/up after deployment
EXPECTED_UP: dict[str, list[str]] = {
    "rtr-01": ["Loopback0", "GigabitEthernet2", "GigabitEthernet3"],
    "rtr-02": ["Loopback0", "GigabitEthernet2", "GigabitEthernet3"],
}

# ── SNMP desired state ────────────────────────────────────────────────────
SNMP_CONFIG: dict[str, list[str]] = {
    "rtr-01": [
        "snmp-server community public RO",
        "snmp-server host 172.20.20.1 version 2c public",
    ],
    "rtr-02": [
        "snmp-server community public RO",
        "snmp-server host 172.20.20.1 version 2c public",
    ],
}


# ── Pre-check ─────────────────────────────────────────────────────────────

def interface_pre_check(task: Task) -> Result:
    """
    Capture interface state before deployment.
    Non-blocking — missing or down interfaces are expected pre-deploy.
    """
    device = task.host.name
    log.info("Interface pre-check: capturing baseline", device=device)

    conn = task.host.get_connection("scrapli", task.nornir.config)
    response = conn.send_command("show ip interface brief")

    if response.failed:
        log.warning("Pre-check command failed", device=device)
        return Result(host=task.host, result={"raw": ""})

    log.debug("Pre-check baseline captured", device=device)
    return Result(host=task.host, result={"raw": response.result})


# ── Post-check ────────────────────────────────────────────────────────────

def interface_post_check(task: Task) -> Result:
    """
    Verify all expected interfaces are up/up after deployment.
    Raises RuntimeError on any interface not in up/up state.
    """
    device = task.host.name
    expected = EXPECTED_UP.get(device, [])

    if not expected:
        log.debug("No expected interfaces defined — skipping post-check", device=device)
        return Result(host=task.host, result={"interfaces_up": []})

    log.info("Interface post-check: verifying state", device=device)

    # Allow brief convergence time for interface negotiation
    time.sleep(10)

    conn = task.host.get_connection("scrapli", task.nornir.config)
    response = conn.send_command("show ip interface brief")

    if response.failed:
        raise RuntimeError(f"Post-check command failed on {device}")

    output = response.result
    issues: list[str] = []

    for iface in expected:
        matching = [l for l in output.splitlines() if l.startswith(iface)]
        if not matching:
            issues.append(f"{iface}: not present in output")
            continue

        columns = matching[0].split()
        # show ip interface brief: Interface IP-Address OK? Method Status Protocol
        if len(columns) >= 6:
            status = columns[-2].lower()
            protocol = columns[-1].lower()
            if status != "up" or protocol != "up":
                issues.append(f"{iface}: status={status} protocol={protocol}")
        else:
            issues.append(f"{iface}: could not parse — '{matching[0]}'")

    if issues:
        log.error("Interface post-check failed", device=device, issues=issues)
        raise RuntimeError(
            f"Interface post-check failed on {device}: {issues}"
        )

    log.info(
        "Interface post-check passed",
        device=device,
        interfaces=expected,
    )
    return Result(host=task.host, result={"interfaces_up": expected})

# ── SNMP restore ───────────────────────────────────────────────────

def restore_snmp(task: Task) -> Result:
    """Push SNMP server config — idempotent, safe to re-run."""
    device = task.host.name
    lines = SNMP_CONFIG.get(device)
    if not lines:
        return Result(host=task.host, skipped=True)
    log.info("Restoring SNMP config", device=device)
    conn = task.host.get_connection("scrapli", task.nornir.config)
    response = conn.send_configs(lines)
    if response.failed:
        raise RuntimeError(f"SNMP restore failed on {device}: {response.result}")
    log.info("SNMP config restored", device=device)
    return Result(host=task.host, result={"snmp": "ok"})

# ── Full lifecycle task ───────────────────────────────────────────────────

def deploy_interfaces_task(task: Task) -> Result:
    """
    Full interface deployment lifecycle for one device:
        1. Inject interface data into host.data at runtime
        2. Pre-check  — capture current interface state
        3. Deploy     — render template and push via Scrapli
        4. Post-check — verify all interfaces reach up/up
    """
    device = task.host.name
    start = time.monotonic()
    steps: dict[str, str] = {}

    if device not in INTERFACE_DATA:
        log.debug("No interface data for device — skipping", device=device)
        return Result(host=task.host, skipped=True)

    # Inject interface data into host.data so deploy_interfaces task can read it
    task.host.data["interfaces"] = INTERFACE_DATA[device]

    # 1. Pre-check
    try:
        task.run(task=interface_pre_check)
        steps["pre_check"] = "ok"
    except Exception as exc:
        log.warning("Pre-check error (non-blocking)", device=device, error=str(exc))
        steps["pre_check"] = "warning"

    # 2. Deploy
    try:
        task.run(task=deploy_interfaces)
        steps["deploy"] = "ok"
    except Exception as exc:
        log.error("Interface deploy failed", device=device, error=str(exc))
        steps["deploy"] = "failed"
        return Result(
            host=task.host,
            failed=True,
            exception=exc,
            result={"device": device, "steps": steps},
        )

    # 3. Post-check
    try:
        task.run(task=interface_post_check)
        steps["post_check"] = "ok"
    except Exception as exc:
        log.error("Interface post-check failed", device=device, error=str(exc))
        steps["post_check"] = "failed"
        return Result(
            host=task.host,
            failed=True,
            exception=exc,
            result={"device": device, "steps": steps},
        )
    
    # 4. SNMP restore
    try:
        task.run(task=restore_snmp)
        steps["snmp"] = "ok"
    except Exception as exc:
        log.warning("SNMP restore failed (non-blocking)", device=device, error=str(exc))
        steps["snmp"] = "warning"

    duration = round(time.monotonic() - start, 2)
    log.info(
        "Interface deployment complete",
        device=device,
        duration_seconds=duration,
        steps=steps,
    )
    return Result(
        host=task.host,
        result={
            "device": device,
            "steps": steps,
            "duration_seconds": duration,
        },
    )


# ── Workflow orchestrator ─────────────────────────────────────────────────

def run_interfaces_deploy(nr: Nornir) -> dict[str, Any]:
    """
    Run interface deployment across all devices that have data defined.
    Returns summary: total, succeeded, failed, skipped.
    """
    targets = [h for h in nr.inventory.hosts if h in INTERFACE_DATA]
    log.info(
        "Interface deploy workflow starting",
        target_devices=targets,
        total=len(targets),
    )

    results = nr.run(task=deploy_interfaces_task)

    succeeded = [h for h, r in results.items() if not r.failed]
    failed = [h for h, r in results.items() if r.failed]
    skipped = []  # Nornir aggregates skipped into succeeded in this version

    summary = {
        "total": len(nr.inventory.hosts),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
    }

    log.info(
        "Interface deploy workflow complete",
        succeeded=len(succeeded),
        failed=len(failed),
        skipped=len(skipped),
    )
    return summary


# ── Standalone entrypoint ─────────────────────────────────────────────────

if __name__ == "__main__":
    config_file = BASE_DIR / "automation" / "nornir_config.yaml"

    nr = InitNornir(config_file=str(config_file))

    summary = run_interfaces_deploy(nr)
    print(summary)

    if summary["failed"]:
        sys.exit(1)