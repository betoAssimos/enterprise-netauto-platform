"""
automation/workflows/deploy_interfaces_workflow.py

Interface deployment workflow — multi-platform.

Deploys Layer 3 interface addressing across all devices that have
interface data defined in custom_fields.

Platform split:
    Cisco IOS XE (rtr-01, rtr-02):
        Reads: custom_fields.interfaces
        Template: interfaces/layer3.j2

    Arista EOS core switches (core-sw-01, core-sw-02):
        Reads: custom_fields.routed_interfaces + custom_fields.svis
        Template: interfaces/layer3_eos.j2

    Arista EOS access switches (arista-01, arista-02):
        Skipped — L2 only, no L3 interfaces to deploy here.

SNMP:
    Restored after interface deploy on Cisco devices only.
    Arista SNMP configured in hardening workflow.
    Reads: custom_fields.snmp
"""
from __future__ import annotations

import time
from typing import Any

from nornir.core import Nornir
from nornir.core.task import Result, Task

from automation.tasks.deploy_interfaces import deploy_interfaces
from automation.utils.logger import get_logger

log = get_logger(__name__)

CISCO_TEMPLATE = "interfaces/layer3.j2"
EOS_TEMPLATE = "interfaces/layer3_eos.j2"

# ── Helpers for Arista ───────────────────────────────────────────────────────────

def _matches_eos_short(full_name: str, short_name: str) -> bool:
    """
    Match Arista short interface names to full names.
    e.g. Loopback0 matches Lo0, Ethernet1 matches Et1, Vlan10 matches Vl10
    """
    mappings = {
        "Loopback": "Lo",
        "Ethernet": "Et",
        "Vlan": "Vl",
        "Management": "Ma",
        "Port-Channel": "Po",
    }
    for full_prefix, short_prefix in mappings.items():
        if full_name.startswith(full_prefix):
            suffix = full_name[len(full_prefix):]
            if short_name == f"{short_prefix}{suffix}":
                return True
    return False


def _parse_status_protocol(columns: list[str]) -> tuple[str, str]:
    """
    Parse status and protocol from show ip interface brief output.

    Cisco format: Interface IP OK? Method Status Protocol
    Arista format: Interface IP Status Protocol MTU Neg

    Detection: if last column is numeric (MTU) or 'N/A' → Arista format.
    """
    if not columns or len(columns) < 4:
        return "unknown", "unknown"

    last = columns[-1]
    # Arista: last column is Neg (N/A or Yes/No), second-to-last is MTU (numeric)
    if last.isdigit() or last in ("N/A", "Yes", "No"):
        # Arista: Status=columns[2], Protocol=columns[3]
        status = columns[2].lower()
        protocol = columns[3].lower()
    else:
        # Cisco: Status=columns[-2], Protocol=columns[-1]
        status = columns[-2].lower()
        protocol = columns[-1].lower()

    return status, protocol


# ── Context builders ───────────────────────────────────────────────────────────

def _cisco_context(task: Task) -> list[dict[str, Any]] | None:
    """
    Read interface list from custom_fields.interfaces for Cisco devices.
    Returns None if no interface data is defined — device will be skipped.
    """
    device = task.host.name
    custom_fields = task.host.data.get("custom_fields", {})
    interfaces = custom_fields.get("interfaces")
    if not interfaces:
        log.debug("No interface data defined — skipping", device=device)
        return None
    return interfaces


def _eos_context(task: Task) -> list[dict[str, Any]] | None:
    """
    Build unified interface list for Arista core switches.

    Combines routed_interfaces and svis into a single list with a
    type field so the EOS template can render each correctly:
        type=routed  → physical/loopback interface with ip address
        type=svi     → interface VlanX with ip address
    Returns None if no routed_interface data — device will be skipped.
    """
    device = task.host.name
    custom_fields = task.host.data.get("custom_fields", {})
    routed = custom_fields.get("routed_interfaces")
    svis = custom_fields.get("svis", [])

    if not routed:
        log.debug("No routed interface data — skipping", device=device)
        return None

    interfaces: list[dict[str, Any]] = []

    for iface in routed:
        interfaces.append({**iface, "type": "routed"})

    for svi in svis:
        svi_entry: dict[str, Any] = {
            "name": f"Vlan{svi['vlan']}",
            "type": "svi",
            "ip_address": svi["ip_address"],
            "description": svi.get("description", f"VLAN {svi['vlan']}"),
        }
        if "ospf_area" in svi:
            svi_entry["ospf_area"] = svi["ospf_area"]
        interfaces.append(svi_entry)

    return interfaces


# ── Pre-check ──────────────────────────────────────────────────────────────────

def _pre_check(task: Task) -> Result:
    device = task.host.name
    log.info("Interface pre-check: capturing baseline", device=device)
    conn = task.host.get_connection("scrapli", task.nornir.config)
    response = conn.send_command("show ip interface brief")
    if response.failed:
        log.warning("Pre-check command failed", device=device)
        return Result(host=task.host, result={"raw": ""})
    log.debug("Pre-check baseline captured", device=device)
    return Result(host=task.host, result={"raw": response.result})


# ── Post-check ─────────────────────────────────────────────────────────────────

def _post_check(task: Task, expected: list[str]) -> Result:
    """
    Verify expected interfaces are up after deployment.
    Handles both Cisco IOS XE and Arista EOS column formats.
    Skips VLAN SVIs — these depend on MLAG/port config, checked later.
    """
    device = task.host.name

    # Skip SVIs from post-check — they depend on MLAG and port config
    check_interfaces = [i for i in expected if not i.startswith("Vlan")]

    if not check_interfaces:
        return Result(host=task.host, result={"interfaces_up": []})

    log.info("Interface post-check: verifying state", device=device)
    time.sleep(15)

    conn = task.host.get_connection("scrapli", task.nornir.config)
    response = conn.send_command("show ip interface brief")
    if response.failed:
        raise RuntimeError(f"Post-check command failed on {device}")

    output = response.result
    issues: list[str] = []

    for iface in check_interfaces:
        # Match interface name at start of line — use short form for Arista
        matching = [
            line for line in output.splitlines()
            if line.split()
            and (
                line.startswith(iface)
                or _matches_eos_short(iface, line.split()[0])
            )
        ]
        if not matching:
            issues.append(f"{iface}: not present in output")
            continue

        columns = matching[0].split()
        status, protocol = _parse_status_protocol(columns)

        if status != "up" or protocol not in ("up", "connected"):
            issues.append(
                f"{iface}: status={status} protocol={protocol}"
            )

    if issues:
        log.error("Interface post-check failed", device=device, issues=issues)
        raise RuntimeError(
            f"Interface post-check failed on {device}: {issues}"
        )

    log.info(
        "Interface post-check passed",
        device=device,
        interfaces=check_interfaces,
    )
    return Result(
        host=task.host, result={"interfaces_up": check_interfaces}
    )


# ── SNMP restore (Cisco only) ──────────────────────────────────────────────────

def _restore_snmp_cisco(task: Task) -> Result:
    """
    Push SNMP server config to Cisco devices.
    Reads community and trap_source from custom_fields.snmp.
    Arista SNMP is handled in the hardening workflow.
    """
    device = task.host.name
    custom_fields = task.host.data.get("custom_fields", {})
    snmp = custom_fields.get("snmp")
    if not snmp:
        log.debug("No SNMP config defined — skipping", device=device)
        return Result(host=task.host, skipped=True)

    community = snmp.get("community", "public")
    trap_source = snmp.get("trap_source", "Loopback0")

    lines = [
        f"snmp-server community {community} RO",
        "snmp-server ifindex persist",
        f"snmp-server trap-source {trap_source}",
    ]

    log.info("Restoring SNMP config", device=device)
    conn = task.host.get_connection("scrapli", task.nornir.config)
    response = conn.send_configs(lines)
    if response.failed:
        raise RuntimeError(
            f"SNMP restore failed on {device}: {response.result}"
        )
    log.info("SNMP config restored", device=device)
    return Result(host=task.host, result={"snmp": "ok"})


# ── Per-device deployment tasks ────────────────────────────────────────────────

def _deploy_cisco_task(task: Task) -> Result:
    """
    Full interface deployment lifecycle for a Cisco IOS XE device.
    Steps: pre-check → deploy → post-check → SNMP restore.
    """
    device = task.host.name
    start = time.monotonic()
    steps: dict[str, str] = {}

    interfaces = _cisco_context(task)
    if interfaces is None:
        return Result(host=task.host, skipped=True)

    task.host.data["interfaces"] = interfaces
    log.info(
        "Interface deploy workflow starting",
        device=device,
        interface_count=len(interfaces),
    )

    # Pre-check
    try:
        task.run(task=_pre_check)
        steps["pre_check"] = "ok"
    except Exception as exc:
        log.warning("Pre-check error (non-blocking)", device=device, error=str(exc))
        steps["pre_check"] = "warning"

    # Deploy
    try:
        task.run(task=deploy_interfaces, template_path=CISCO_TEMPLATE)
        steps["deploy"] = "ok"
    except Exception as exc:
        log.error("Interface deploy failed", device=device, error=str(exc))
        steps["deploy"] = "failed"
        return Result(
            host=task.host, failed=True, exception=exc,
            result={"device": device, "steps": steps},
        )

    # Post-check — verify all interfaces are up/up
    expected = [i["name"] for i in interfaces]
    try:
        task.run(task=_post_check, expected=expected)
        steps["post_check"] = "ok"
    except Exception as exc:
        log.error("Post-check failed", device=device, error=str(exc))
        steps["post_check"] = "failed"
        return Result(
            host=task.host, failed=True, exception=exc,
            result={"device": device, "steps": steps},
        )

    # SNMP restore
    try:
        task.run(task=_restore_snmp_cisco)
        steps["snmp"] = "ok"
    except Exception as exc:
        log.warning(
            "SNMP restore failed (non-blocking)", device=device, error=str(exc)
        )
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
        result={"device": device, "steps": steps, "duration_seconds": duration},
    )


def _deploy_eos_task(task: Task) -> Result:
    """
    Full interface deployment lifecycle for an Arista EOS core switch.
    Steps: pre-check → deploy → post-check.
    Covers routed interfaces (Loopback, Ethernet) and SVIs (VlanX).
    """
    device = task.host.name
    start = time.monotonic()
    steps: dict[str, str] = {}

    interfaces = _eos_context(task)
    if interfaces is None:
        return Result(host=task.host, skipped=True)

    task.host.data["interfaces"] = interfaces
    log.info(
        "Interface deploy workflow starting",
        device=device,
        interface_count=len(interfaces),
    )

    # Pre-check
    try:
        task.run(task=_pre_check)
        steps["pre_check"] = "ok"
    except Exception as exc:
        log.warning("Pre-check error (non-blocking)", device=device, error=str(exc))
        steps["pre_check"] = "warning"

    # Deploy
    try:
        task.run(task=deploy_interfaces, template_path=EOS_TEMPLATE)
        steps["deploy"] = "ok"
    except Exception as exc:
        log.error("Interface deploy failed", device=device, error=str(exc))
        steps["deploy"] = "failed"
        return Result(
            host=task.host, failed=True, exception=exc,
            result={"device": device, "steps": steps},
        )

    # Post-check — verify all routed interfaces and SVIs are up/up
    expected = [i["name"] for i in interfaces]
    try:
        task.run(task=_post_check, expected=expected)
        steps["post_check"] = "ok"
    except Exception as exc:
        log.error("Post-check failed", device=device, error=str(exc))
        steps["post_check"] = "failed"
        return Result(
            host=task.host, failed=True, exception=exc,
            result={"device": device, "steps": steps},
        )

    duration = round(time.monotonic() - start, 2)
    log.info(
        "Interface deployment complete",
        device=device,
        duration_seconds=duration,
        steps=steps,
    )
    return Result(
        host=task.host,
        result={"device": device, "steps": steps, "duration_seconds": duration},
    )


# ── Workflow orchestrator ──────────────────────────────────────────────────────

def run_interfaces_deploy(nr: Nornir) -> dict[str, Any]:
    """
    Deploy Layer 3 interfaces across the lab.

    Run 1: Cisco edge routers — layer3.j2
    Run 2: Arista core switches — layer3_eos.j2
    Access switches skipped — L2 only, no L3 interfaces.
    """
    log.info(
        "Interface deploy workflow starting",
        host_count=len(nr.inventory.hosts),
    )

    succeeded: list[str] = []
    failed: list[str] = []

    # Run 1 — Cisco edge routers
    cisco_nr = nr.filter(
        filter_func=lambda h: h.data.get("role") == "edge-router"
    )
    if cisco_nr.inventory.hosts:
        log.info(
            "Deploying Cisco interfaces",
            devices=list(cisco_nr.inventory.hosts.keys()),
        )
        cisco_results = cisco_nr.run(task=_deploy_cisco_task)
        succeeded += [h for h, r in cisco_results.items() if not r.failed]
        failed += [h for h, r in cisco_results.items() if r.failed]

    # Run 2 — Arista core switches
    core_nr = nr.filter(
        filter_func=lambda h: h.data.get("role") == "core-switch"
    )
    if core_nr.inventory.hosts:
        log.info(
            "Deploying Arista core interfaces",
            devices=list(core_nr.inventory.hosts.keys()),
        )
        core_results = core_nr.run(task=_deploy_eos_task)
        succeeded += [h for h, r in core_results.items() if not r.failed]
        failed += [h for h, r in core_results.items() if r.failed]

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
        "Interface deploy workflow complete",
        succeeded=len(succeeded),
        failed=len(failed),
        skipped=len(skipped),
    )
    return summary