# tests/chaos/injectors/ospf.py
#
# Scenario 3: OSPF Process Removal
#
# Inject: Removes OSPF process from device
# Detect: pyATS OSPF intent test fails (no neighbors)
# Auto-remediate: YES (deploy ospf workflow)
#
# Target: core-sw-01 (Arista EOS) - primary core switch
# Platform: arista_eos (no Genie parsers - uses CLI regex)

from __future__ import annotations

import sys
from pathlib import Path
from time import time

# Add project root for imports
BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from tests.chaos.base import ChaosScenario, PhaseResult
from tests.chaos.registry import register_scenario


class OspfProcessRemoval(ChaosScenario):
    """
    Scenario 3: OSPF process removal fault injection.
    
    Simulates operator accidentally removing OSPF process.
    Expected impact: OSPF neighbors drop, routing table loses OSPF routes.
    """
    
    def __init__(self):
        super().__init__(
            name="OSPF Process Removal",
            scenario_id=3,
            phase="1"
        )
        self.target_device = "core-sw-01"
        self.platform = "arista_eos"  # EOS uses CLI commands, no Genie
        self.ospf_process_id = "1"
        self._pre_snapshot: dict = {}
    
    def _get_ospf_state(self) -> dict:
        """Capture pre-fault OSPF state for comparison."""
        conn = self._connect(self.target_device, self.platform)
        
        # EOS: show ip ospf neighbor - no Genie parser available
        result = conn.send_command("show ip ospf neighbor")
        
        # Parse neighbor count (simplified regex approach)
        # Example EOS output:
        # Neighbor ID  Instance  VRF      Pri State    Dead Time  Address      Interface
        # 1.1.1.1      1         default  0   FULL     00:00:35   10.1.0.1     Ethernet1
        lines = result.result.splitlines()
        neighbors = []
        
        for line in lines:
            if "FULL" in line or "INIT" in line or "2WAY" in line:
                parts = line.split()
                if len(parts) >= 7:
                    neighbors.append({
                        "neighbor_id": parts[0],
                        "state": parts[4] if len(parts) > 4 else "unknown",
                        "interface": parts[-1] if parts else "unknown"
                    })
        
        return {
            "neighbor_count": len(neighbors),
            "neighbors": neighbors,
            "raw_output": result.result[:500]
        }
    
    def inject(self) -> PhaseResult:
        """
        Inject fault: Remove OSPF process from target device.
        Uses configure private session on EOS.
        """
        start_time = __import__('datetime').datetime.utcnow()
        
        try:
            conn = self._connect(self.target_device, self.platform)
            
            # Capture pre-fault state
            self._pre_snapshot = self._get_ospf_state()
                   
            config_commands = [
                f"no router ospf {self.ospf_process_id}",
            ]
            
            result = conn.send_configs(config_commands)
            
            duration = int((__import__('datetime').datetime.utcnow() - start_time).total_seconds() * 1000)
            
            return PhaseResult(
                name="inject",
                status="passed",
                duration_ms=duration,
                message=f"Removed OSPF process {self.ospf_process_id} from {self.target_device}",
                data={
                    "device": self.target_device,
                    "process_id": self.ospf_process_id,
                    "config_output": result.result[:200] if hasattr(result, 'result') else "N/A",
                    "pre_neighbor_count": self._pre_snapshot.get("neighbor_count", 0)
                }
            )
            
        except Exception as e:
            duration = int((__import__('datetime').datetime.utcnow() - start_time).total_seconds() * 1000)
            return PhaseResult(
                name="inject",
                status="failed",
                duration_ms=duration,
                message=f"Failed to inject OSPF fault: {str(e)}",
                data={"error": str(e)}
            )
    
    def detect(self) -> PhaseResult:
        """
        Detect fault: Verify OSPF neighbors are gone.
        Uses pyATS test - SUCCESS when pyATS FAILS (fault detected).
        """
        start_time = __import__('datetime').datetime.utcnow()
        
        # Run pyATS OSPF intent test
        pyats_passed, pyats_output = self._run_pyats("tests/postcheck/test_ospf_intent.py")
        
        duration = int((__import__('datetime').datetime.utcnow() - start_time).total_seconds() * 1000)
        
        # Detection logic: We WANT pyATS to FAIL (that means fault is present)
        if not pyats_passed:
            # pyATS failed = fault detected = detection PASSED
            return PhaseResult(
                name="detect",
                status="passed",  # Detection succeeded
                duration_ms=duration,
                message=f"Fault detected: OSPF check failed on {self.target_device}",
                data={
                    "pyats_passed": False,
                    "pyats_summary": pyats_output[:300],
                    "fault_verified": True
                }
            )
        else:
            # pyATS passed = no fault detected = detection FAILED
            return PhaseResult(
                name="detect",
                status="failed",  # Detection failed to find fault
                duration_ms=duration,
                message="Fault not detected: OSPF check still passing (process may still exist)",
                data={
                    "pyats_passed": True,
                    "pyats_summary": pyats_output[:300],
                    "fault_verified": False
                }
            )
    
    def remediate(self) -> PhaseResult:
        """
        Auto-remediate: Restore OSPF process via runner workflow.
        Idempotent deploy ospf workflow handles recreation.
        """
        start_time = __import__('datetime').datetime.utcnow()
        
        try:
            success = self._remediate_via_runner("ospf")
            duration = int((__import__('datetime').datetime.utcnow() - start_time).total_seconds() * 1000)
            
            if success:
                return PhaseResult(
                    name="remediate",
                    status="passed",
                    duration_ms=duration,
                    message=f"Auto-remediation successful: deploy ospf completed",
                    data={"method": "runner_deploy_ospf"}
                )
            else:
                return PhaseResult(
                    name="remediate",
                    status="failed",
                    duration_ms=duration,
                    message="Auto-remediation failed: deploy ospf returned error",
                    data={"method": "runner_deploy_ospf"}
                )
                
        except Exception as e:
            duration = int((__import__('datetime').datetime.utcnow() - start_time).total_seconds() * 1000)
            return PhaseResult(
                name="remediate",
                status="failed",
                duration_ms=duration,
                message=f"Auto-remediation exception: {str(e)}",
                data={"error": str(e)}
            )
    
    def restore(self) -> PhaseResult:
        """
        Manual restore: Only needed if auto-remediation skipped.
        Same logic as remediate() for this scenario.
        """
        start_time = __import__('datetime').datetime.utcnow()
        
        try:
            # Check current state first
            current_state = self._get_ospf_state()
            
            if current_state["neighbor_count"] > 0:
                return PhaseResult(
                    name="restore",
                    status="passed",
                    duration_ms=0,
                    message="Manual restore not needed - OSPF already restored",
                    data={"neighbor_count": current_state["neighbor_count"]}
                )
            
            # Restore via runner
            success = self._remediate_via_runner("ospf")
            duration = int((__import__('datetime').datetime.utcnow() - start_time).total_seconds() * 1000)
            
            if success:
                return PhaseResult(
                    name="restore",
                    status="passed",
                    duration_ms=duration,
                    message="Manual restore successful: OSPF process recreated",
                    data={"method": "runner_deploy_ospf"}
                )
            else:
                return PhaseResult(
                    name="restore",
                    status="failed",
                    duration_ms=duration,
                    message="Manual restore failed",
                    data={}
                )
                
        except Exception as e:
            duration = int((__import__('datetime').datetime.utcnow() - start_time).total_seconds() * 1000)
            return PhaseResult(
                name="restore",
                status="failed",
                duration_ms=duration,
                message=f"Restore exception: {str(e)}",
                data={"error": str(e)}
            )
    
    def verify(self) -> PhaseResult:
        """
        Verify recovery: Check OSPF neighbors restored.
        """
        import time
        start_time = __import__('datetime').datetime.utcnow()
        
        print("      Waiting 45s for OSPF convergence...")
        time.sleep(45)

        try:
            state = self._get_ospf_state()
            duration = int((__import__('datetime').datetime.utcnow() - start_time).total_seconds() * 1000)
            
            # Check we have neighbors back (should have 2: rtr-01 and rtr-02)
            if state["neighbor_count"] >= 2:
                return PhaseResult(
                    name="verify",
                    status="passed",
                    duration_ms=duration,
                    message=f"Verification passed: {state['neighbor_count']} OSPF neighbors restored",
                    data={"neighbors": state["neighbors"]}
                )
            else:
                return PhaseResult(
                    name="verify",
                    status="failed",
                    duration_ms=duration,
                    message=f"Verification failed: Only {state['neighbor_count']} neighbors (expected 2)",
                    data={"neighbors": state["neighbors"]}
                )
                
        except Exception as e:
            duration = int((__import__('datetime').datetime.utcnow() - start_time).total_seconds() * 1000)
            return PhaseResult(
                name="verify",
                status="failed",
                duration_ms=duration,
                message=f"Verification exception: {str(e)}",
                data={"error": str(e)}
            )


# Register scenario in global registry
# Auto-remediate: True (deploy ospf is idempotent and safe)
register_scenario(
    scenario_id=3,
    scenario_class=OspfProcessRemoval,
    phase="1",
    auto_remediate_default=True
)