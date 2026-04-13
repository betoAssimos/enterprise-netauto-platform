# tests/chaos/report.py
#
# Reporting utilities for chaos framework.
#
# Responsibilities:
#   - JSON serialization of scenario results (machine parseable)
#   - Human-readable summary generation
#   - Report file persistence
#   - Batch report aggregation

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from tests.chaos.base import PhaseResult, ScenarioResult


# ---------------------------------------------------------------------------
# JSON Serialization
# ---------------------------------------------------------------------------

class ChaosJSONEncoder(json.JSONEncoder):
    """Handle datetime serialization for JSON output."""
    
    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def result_to_dict(result: Union[ScenarioResult, PhaseResult]) -> Dict[str, Any]:
    """Convert dataclass to dict for JSON serialization."""
    return asdict(result)


def results_to_json(results: Union[ScenarioResult, List[ScenarioResult]], indent: int = 2) -> str:
    """
    Serialize scenario results to JSON string.
    
    Args:
        results: Single ScenarioResult or list for batch runs
        indent: JSON formatting indent (default 2)
    """
    if isinstance(results, list):
        data = [result_to_dict(r) for r in results]
    else:
        data = result_to_dict(results)
    
    return json.dumps(data, cls=ChaosJSONEncoder, indent=indent)


# ---------------------------------------------------------------------------
# Summary Generation
# ---------------------------------------------------------------------------

def generate_summary(results: Union[ScenarioResult, List[ScenarioResult]]) -> str:
    """
    Generate human-readable text summary of chaos results.
    
    Format:
    ======== CHAOS ENGINEERING REPORT ========
    Generated: 2026-04-12T20:45:00Z
    Total Scenarios: N
    
    [Scenario ID: Name]
    Status: PASSED/FAILED
    Duration: X seconds
    Phases:
      - inject: PASSED (1200ms)
      - wait: PASSED (5000ms)
      - detect: PASSED (3500ms)  ← Note: PASSED means fault detected
      - remediate: PASSED (8000ms) [auto]
      - verify: PASSED (2200ms)
      - restore: SKIPPED
    """
    lines = []
    lines.append("=" * 60)
    lines.append("CHAOS ENGINEERING REPORT")
    lines.append("=" * 60)
    lines.append(f"Generated: {datetime.utcnow().isoformat()}Z")
    
    if isinstance(results, list):
        scenarios = results
        lines.append(f"Total Scenarios: {len(scenarios)}")
    else:
        scenarios = [results]
        lines.append(f"Total Scenarios: 1")
    
    lines.append("")
    
    total_passed = 0
    total_failed = 0
    
    for scenario in scenarios:
        status_icon = "✓" if scenario.status == "passed" else "✗"
        lines.append(f"[{status_icon}] Scenario {scenario.scenario_id}: {scenario.scenario_name}")
        lines.append(f"    Phase: {scenario.phase} | Overall: {scenario.status.upper()}")
        lines.append(f"    Auto-remediated: {'Yes' if scenario.auto_remediated else 'No'}")
        lines.append(f"    Manual restore required: {'Yes' if scenario.restore_required else 'No'}")
        
        if scenario.start_time and scenario.end_time:
            try:
                start = datetime.fromisoformat(scenario.start_time)
                end = datetime.fromisoformat(scenario.end_time)
                duration = (end - start).total_seconds()
                lines.append(f"    Duration: {duration:.2f}s")
            except (ValueError, TypeError):
                pass
        
        lines.append("    Phases:")
        
        for phase in scenario.phases:
            icon = {
                "passed": "✓",
                "failed": "✗",
                "skipped": "-"
            }.get(phase.status, "?")
            
            lines.append(f"      {icon} {phase.name}: {phase.status.upper()} ({phase.duration_ms}ms)")
            if phase.message:
                lines.append(f"          {phase.message[:80]}")
        
        lines.append("")
        
        if scenario.status == "passed":
            total_passed += 1
        else:
            total_failed += 1
    
    # Summary statistics
    lines.append("-" * 60)
    lines.append(f"SUMMARY: {total_passed} passed, {total_failed} failed")
    if total_failed == 0:
        lines.append("RESULT: All chaos scenarios completed successfully")
    else:
        lines.append("RESULT: Some scenarios failed — review logs above")
    lines.append("=" * 60)
    
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report Persistence
# ---------------------------------------------------------------------------

class ChaosReporter:
    """
    Handles saving chaos reports to disk.
    
    Directory structure:
    tests/chaos/reports/
    ├── chaos_report_20260412_204500.json
    └── chaos_report_20260412_204500.txt
    """
    
    def __init__(self, report_dir: Optional[Path] = None):
        if report_dir is None:
            # Default: tests/chaos/reports/
            self.report_dir = Path(__file__).parent / "reports"
        else:
            self.report_dir = Path(report_dir)
        
        # Ensure directory exists
        self.report_dir.mkdir(parents=True, exist_ok=True)
    
    def save_report(
        self,
        results: Union[ScenarioResult, List[ScenarioResult]],
        base_filename: Optional[str] = None
    ) -> Dict[str, Path]:
        """
        Save both JSON and text summary reports.
        
        Returns:
            Dict with 'json' and 'txt' keys pointing to saved file paths
        """
        if base_filename is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            base_filename = f"chaos_report_{timestamp}"
        
        json_path = self.report_dir / f"{base_filename}.json"
        txt_path = self.report_dir / f"{base_filename}.txt"
        
        # Save JSON
        json_content = results_to_json(results)
        json_path.write_text(json_content, encoding="utf-8")
        
        # Save summary
        summary_content = generate_summary(results)
        txt_path.write_text(summary_content, encoding="utf-8")
        
        return {
            "json": json_path,
            "txt": txt_path,
            "base": self.report_dir / base_filename
        }
    
    def list_reports(self) -> List[Path]:
        """List all report files in the directory."""
        if not self.report_dir.exists():
            return []
        
        json_files = sorted(self.report_dir.glob("chaos_report_*.json"))
        return json_files
    
    def load_report(self, json_path: Path) -> Union[Dict, List[Dict]]:
        """Load a JSON report back into dict format."""
        content = json_path.read_text(encoding="utf-8")
        return json.loads(content)


# ---------------------------------------------------------------------------
# CLI utilities (for standalone use)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Test/demo: Create sample results and generate reports
    print("Testing chaos reporting system...")
    
    # Create sample results
    sample_phase = PhaseResult(
        name="inject",
        status="passed",
        duration_ms=1200,
        message="OSPF process removed via no router ospf 1"
    )
    
    sample_scenario = ScenarioResult(
        scenario_name="OSPF Process Removal",
        scenario_id=3,
        phase="1",
        status="passed",
        phases=[sample_phase],
        auto_remediated=True,
        restore_required=False
    )
    
    # Generate and print summary
    summary = generate_summary(sample_scenario)
    print(summary)
    
    # Save report
    reporter = ChaosReporter()
    paths = reporter.save_report(sample_scenario, "test_report")
    print(f"\nReports saved to:")
    print(f"  JSON: {paths['json']}")
    print(f"  TXT:  {paths['txt']}")