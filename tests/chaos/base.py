# tests/chaos/base.py
#
# ChaosScenario base class for fault injection framework.
#
# Design decisions:
#   - Scrapli direct for SSH (no Nornir — chaos is sequential, not parallel)
#   - pynetbox for device IP lookup (SoT-consistent, no hardcoded IPs)
#   - subprocess for pyATS (same pattern as CI pipeline)
#   - Direct import for remediation (same pattern as runner.py)
#   - detect() PASSES when pyATS FAILS (fault detected = success)

from __future__ import annotations

import os
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pynetbox
from scrapli.driver.core import IOSXEDriver, EOSDriver
from scrapli.exceptions import ScrapliException


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[2]
NETBOX_URL = os.environ.get("NETBOX_URL")
NETBOX_TOKEN = os.environ.get("NETBOX_TOKEN")
DEVICE_USERNAME = os.environ.get("DEVICE_USERNAME")
DEVICE_PASSWORD = os.environ.get("DEVICE_PASSWORD")


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class PhaseResult:
    """Result of a single chaos phase."""
    name: str
    status: str  # "passed", "failed", "skipped"
    duration_ms: int
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class ScenarioResult:
    """Result of a complete chaos scenario."""
    scenario_name: str
    scenario_id: int
    phase: str  # "1", "2", "3"
    status: str  # "passed", "failed", "incomplete"
    phases: List[PhaseResult] = field(default_factory=list)
    start_time: str = ""
    end_time: str = ""
    auto_remediated: bool = False
    restore_required: bool = False
    
    def add_phase(self, result: PhaseResult) -> None:
        self.phases.append(result)
        # Update overall status if any phase fails
        if result.status == "failed":
            self.status = "failed"
    
    def finalize(self) -> None:
        self.end_time = datetime.utcnow().isoformat()
        if self.status not in ["failed"]:
            self.status = "passed"


# ---------------------------------------------------------------------------
# Base Class
# ---------------------------------------------------------------------------

class ChaosScenario(ABC):
    """
    Base class for chaos engineering scenarios.
    
    Subclasses must implement:
        - inject(): Inject the fault
        - detect(): Verify fault is present (pyATS should FAIL here)
        - restore(): Restore original state (if not auto-remediated)
    
    Optional:
        - remediate(): Auto-remediation logic (if applicable)
        - verify(): Post-remediation verification
    """
    
    def __init__(self, name: str, scenario_id: int, phase: str = "1"):
        self.name = name
        self.scenario_id = scenario_id
        self.phase = phase
        self.result = ScenarioResult(
            scenario_name=name,
            scenario_id=scenario_id,
            phase=phase,
            status="incomplete",
            start_time=datetime.utcnow().isoformat()
        )
        self._nb: Optional[pynetbox.api] = None
        self._connections: Dict[str, Union[IOSXEDriver, EOSDriver]] = {}
        if not DEVICE_USERNAME or not DEVICE_PASSWORD:
            raise RuntimeError(
                "DEVICE_USERNAME and DEVICE_PASSWORD must be set in environment"
            )
        
    def _get_netbox_client(self) -> pynetbox.api:
        """Lazy initialization of NetBox client."""
        if self._nb is None:
            if not NETBOX_URL or not NETBOX_TOKEN:
                raise RuntimeError("NETBOX_URL and NETBOX_TOKEN must be set")
            self._nb = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)
            self._nb.http_session.verify = False
        return self._nb
    
    def _get_device_ip(self, device_name: str) -> str:
        """
        Retrieve device management IP from NetBox.
        Same pattern as netbox_inventory.py.
        """
        nb = self._get_netbox_client()
        device = nb.dcim.devices.get(name=device_name)
        
        if not device:
            raise ValueError(f"Device {device_name} not found in NetBox")
        
        if not device.primary_ip4:
            raise ValueError(f"Device {device_name} has no primary_ip4")
            
        # Strip CIDR prefix
        ip = str(device.primary_ip4.address).split("/")[0]
        return ip
    
    def _connect(self, device_name: str, platform: str):
        """
        Establish Scrapli connection to device.
        Platform: 'cisco_iosxe' or 'arista_eos' (matches groups.yaml).
        """
        if device_name in self._connections:
            return self._connections[device_name]
            
        hostname = self._get_device_ip(device_name)
        
        # Map platform to driver (privilege levels pre-configured)
        driver_map = {
            "cisco_iosxe": IOSXEDriver,
            "arista_eos": EOSDriver,
        }
        
        if platform not in driver_map:
            raise ValueError(f"Unsupported platform: {platform}. Use cisco_iosxe or arista_eos")
        
        DriverClass = driver_map[platform]
        
        conn = DriverClass(
            host=hostname,
            auth_username=DEVICE_USERNAME,
            auth_password=DEVICE_PASSWORD,
            auth_strict_key=False,
            ssh_config_file=False,  # Match groups.yaml extras
        )
        
        try:
            conn.open()
        except ScrapliException as e:
            raise ConnectionError(f"Failed to connect to {device_name} ({hostname}): {e}")
            
        self._connections[device_name] = conn
        return conn
    
    def _disconnect(self, device_name: Optional[str] = None) -> None:
        """Close Scrapli connection(s)."""
        if device_name:
            if device_name in self._connections:
                self._connections[device_name].close()
                del self._connections[device_name]
        else:
            for conn in self._connections.values():
                conn.close()
            self._connections.clear()
    
    def _run_pyats(self, test_file: str, testbed: str = "tests/testbed.yaml") -> tuple:
        """
        Run pyATS test file via subprocess.
        Returns: (passed: bool, output: str)
        detect() PASSES when pyATS FAILS (fault was detected).
        """
        cmd = [
            sys.executable, "-m", "pyats", "run", "job",
            test_file,
            "--testbed", testbed
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                cwd=str(BASE_DIR)
            )
            # pyATS returns 0 on success, non-zero on failure
            passed = result.returncode == 0
            output = result.stdout + "\n" + result.stderr
            return passed, output
            
        except subprocess.TimeoutExpired:
            return False, "pyATS execution timed out after 300s"
        except Exception as e:
            return False, f"pyATS execution failed: {e}"
    
    def _remediate_via_runner(self, domain: str) -> bool:
        """
        Trigger remediation via runner.py workflow.
        Direct import pattern — same as runner.py
        """
        try:
            # Import here to avoid circular deps and heavy init at module load
            from automation.runner import main as runner_main
            import sys as sys_module
            
            # Save original argv
            original_argv = sys_module.argv[:]
            
            try:
                sys_module.argv = ["runner.py", "deploy", domain]
                runner_main()
                return True
            finally:
                sys_module.argv = original_argv
                
        except Exception as e:
            print(f"[ERROR] Remediation failed for domain '{domain}': {e}")
            return False
    
    def _wait(self, seconds: int, reason: str = "") -> PhaseResult:
        """Wait period between inject and detect."""
        import time
        start = datetime.utcnow()
        time.sleep(seconds)
        duration = int((datetime.utcnow() - start).total_seconds() * 1000)
        return PhaseResult(
            name="wait",
            status="passed",
            duration_ms=duration,
            message=f"Waited {seconds}s: {reason}" if reason else f"Waited {seconds}s"
        )
    
    @abstractmethod
    def inject(self) -> PhaseResult:
        """Inject the fault. Must be implemented by subclass."""
        pass
    
    @abstractmethod
    def detect(self) -> PhaseResult:
        """
        Detect the fault is present.
        SUCCESS = pyATS FAILS (fault detected).
        FAILURE = pyATS PASSES (fault not present).
        """
        pass
    
    def remediate(self) -> PhaseResult:
        """
        Auto-remediate the fault (optional).
        Override if scenario supports auto-remediation.
        Default: skip.
        """
        return PhaseResult(
            name="remediate",
            status="skipped",
            duration_ms=0,
            message="No auto-remediation for this scenario"
        )
    
    def verify(self) -> PhaseResult:
        """
        Verify system recovered post-remediation.
        Default: run pyATS connectivity check.
        """
        passed, output = self._run_pyats("tests/postcheck/test_connectivity.py")
        
        if passed:
            return PhaseResult(
                name="verify",
                status="passed",
                duration_ms=0,
                message="Post-remediation verification passed",
                data={"pyats_output": output[:500]}
            )
        else:
            return PhaseResult(
                name="verify",
                status="failed",
                duration_ms=0,
                message="Post-remediation verification failed",
                data={"pyats_output": output[:500]}
            )
    
    @abstractmethod
    def restore(self) -> PhaseResult:
        """
        Manual restore for non-auto-remediation scenarios.
        Must be implemented by subclass.
        """
        pass
    
    def run(self, auto_remediate: bool = True, wait_seconds: int = 5) -> ScenarioResult:
        """
        Execute full chaos scenario lifecycle:
        inject → wait → detect → [remediate] → verify → [restore]
        """
        print(f"\n{'='*60}")
        print(f"CHAOS SCENARIO {self.scenario_id}: {self.name}")
        print(f"Phase {self.phase} | Auto-remediate: {auto_remediate}")
        print(f"{'='*60}")
        
        try:
            # 1. INJECT
            print(f"[1/6] Injecting fault...")
            inject_result = self.inject()
            self.result.add_phase(inject_result)
            print(f"      Status: {inject_result.status}")
            if inject_result.status == "failed":
                raise RuntimeError("Injection failed — aborting")
            
            # 2. WAIT
            print(f"[2/6] Waiting {wait_seconds}s for fault propagation...")
            wait_result = self._wait(wait_seconds, "fault propagation")
            self.result.add_phase(wait_result)
            
            # 3. DETECT
            print(f"[3/6] Detecting fault (pyATS should FAIL)...")
            detect_result = self.detect()
            self.result.add_phase(detect_result)
            print(f"      Status: {detect_result.status}")
            
            # Detection logic: detect() PASSES when pyATS FAILS
            # So if detect_result.status == "passed", we found the fault (good)
            # If detect_result.status == "failed", we didn't find the fault (bad)
            
            # 4. REMEDIATE (if enabled)
            if auto_remediate and detect_result.status == "passed":
                print(f"[4/6] Auto-remediating...")
                remediate_result = self.remediate()
                self.result.add_phase(remediate_result)
                self.result.auto_remediated = remediate_result.status == "passed"
                print(f"      Status: {remediate_result.status}")
            else:
                print(f"[4/6] Skipping auto-remediation")
                self.result.add_phase(PhaseResult(
                    name="remediate",
                    status="skipped",
                    duration_ms=0,
                    message="Auto-remediation disabled or fault not detected"
                ))
                self.result.restore_required = True
            
            # 5. VERIFY
            print(f"[5/6] Verifying recovery...")
            verify_result = self.verify()
            self.result.add_phase(verify_result)
            print(f"      Status: {verify_result.status}")
            
            # 6. RESTORE (if not auto-remediated)
            if self.result.restore_required:
                print(f"[6/6] Manual restore required...")
                restore_result = self.restore()
                self.result.add_phase(restore_result)
                print(f"      Status: {restore_result.status}")
            else:
                print(f"[6/6] Skipping manual restore (auto-remediated)")
                self.result.add_phase(PhaseResult(
                    name="restore",
                    status="skipped",
                    duration_ms=0,
                    message="Auto-remediation performed — no manual restore needed"
                ))
            
        except Exception as e:
            error_result = PhaseResult(
                name="exception",
                status="failed",
                duration_ms=0,
                message=str(e)
            )
            self.result.add_phase(error_result)
            print(f"[ERROR] {e}")
            
        finally:
            self._disconnect()  # Cleanup connections
            self.result.finalize()
            
        print(f"\nScenario {self.scenario_id} complete: {self.result.status}")
        print(f"{'='*60}")
        return self.result