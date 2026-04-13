# tests/chaos/chaos_runner.py
#
# CLI entrypoint for chaos engineering framework.
#
# Usage:
#   python tests/chaos/chaos_runner.py --scenario 3
#   python tests/chaos/chaos_runner.py --phase 1
#   python tests/chaos/chaos_runner.py --all
#   python tests/chaos/chaos_runner.py --scenario 3 --no-remediate
#   python tests/chaos/chaos_runner.py --all --report chaos_report.json

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Type

# Add project root to path for imports
BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from tests.chaos.base import ChaosScenario, ScenarioResult
from tests.chaos.report import ChaosReporter, generate_summary, results_to_json
from tests.chaos.registry import SCENARIO_REGISTRY, PHASE_REGISTRY, register_scenario
import tests.chaos.injectors.ospf  # noqa: F401 — registers Scenario 3

# ---------------------------------------------------------------------------
# CLI Argument Parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enterprise Network Automation Platform - Chaos Engineering Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --scenario 3                    # Run scenario 3 only
  %(prog)s --phase 1                       # Run all Phase 1 scenarios
  %(prog)s --all                           # Run all registered scenarios
  %(prog)s --scenario 3 --no-remediate     # Run without auto-remediation
  %(prog)s --all --report chaos_report.json # Save report to file
        """
    )
    
    # Execution mode (mutually exclusive)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--scenario",
        type=int,
        metavar="ID",
        help="Run specific scenario by ID (e.g., 3 for OSPF removal)"
    )
    group.add_argument(
        "--phase",
        type=str,
        choices=["1", "2", "3"],
        help="Run all scenarios in phase (1=Single faults, 2=Steady state, 3=Combined)"
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Run all registered scenarios across all phases"
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="List all available scenarios and exit"
    )
    
    # Options
    parser.add_argument(
        "--no-remediate",
        action="store_true",
        help="Disable auto-remediation (manual restore required)"
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=5,
        metavar="SECONDS",
        help="Wait time between inject and detect (default: 5)"
    )
    parser.add_argument(
        "--report",
        type=str,
        metavar="FILE",
        help="Save JSON report to file (use with --all or --phase)"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        default=True,
        help="Print human-readable summary (default: True)"
    )
    parser.add_argument(
        "--testbed",
        type=str,
        default="tests/testbed.yaml",
        help="Path to pyATS testbed file (default: tests/testbed.yaml)"
    )
    
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Execution Logic
# ---------------------------------------------------------------------------

def list_scenarios() -> None:
    """Print available scenarios and exit."""
    print("=" * 60)
    print("REGISTERED CHAOS SCENARIOS")
    print("=" * 60)
    
    if not SCENARIO_REGISTRY:
        print("No scenarios registered yet.")
        print("Injector modules must be imported to register scenarios.")
        return
    
    # Group by phase
    for phase in ["1", "2", "3"]:
        scenarios = PHASE_REGISTRY.get(phase, [])
        if not scenarios:
            continue
            
        phase_name = {
            "1": "Phase 1 - Single Fault Scenarios",
            "2": "Phase 2 - Steady State Baseline",
            "3": "Phase 3 - Combined Failures"
        }.get(phase, f"Phase {phase}")
        
        print(f"\n{phase_name}:")
        print("-" * 40)
        
        for sid in sorted(scenarios):
            scenario_class, auto_remed = SCENARIO_REGISTRY[sid]
            auto_str = "auto-remediate" if auto_remed else "manual-restore"
            print(f"  {sid:2d}. {scenario_class.__name__:<30} [{auto_str}]")
    
    print(f"\nTotal: {len(SCENARIO_REGISTRY)} scenario(s) registered")
    print("=" * 60)


def run_scenario(
    scenario_id: int,
    auto_remediate: bool = True,
    wait_seconds: int = 5,
    testbed: str = "tests/testbed.yaml"
) -> Optional[ScenarioResult]:
    """
    Execute a single scenario by ID.
    
    Returns:
        ScenarioResult on success, None if scenario not found
    """
    if scenario_id not in SCENARIO_REGISTRY:
        print(f"[ERROR] Scenario {scenario_id} not found in registry")
        return None
    
    scenario_class, auto_default = SCENARIO_REGISTRY[scenario_id]
    
    # Override with CLI --no-remediate if provided
    if not auto_remediate:
        effective_auto = False
    else:
        effective_auto = auto_default
    
    # Instantiate and run
    try:
        scenario = scenario_class()
        result = scenario.run(
            auto_remediate=effective_auto,
            wait_seconds=wait_seconds
        )
        return result
    except Exception as e:
        print(f"[ERROR] Scenario {scenario_id} execution failed: {e}")
        return None


def run_phase(
    phase: str,
    auto_remediate: bool = True,
    wait_seconds: int = 5,
    testbed: str = "tests/testbed.yaml"
) -> List[ScenarioResult]:
    """Run all scenarios in a phase."""
    scenario_ids = PHASE_REGISTRY.get(phase, [])
    
    if not scenario_ids:
        print(f"[WARNING] No scenarios registered for phase {phase}")
        return []
    
    print(f"\n>>> Running Phase {phase}: {len(scenario_ids)} scenario(s)")
    print(f">>> Auto-remediate: {'Yes' if auto_remediate else 'No'}")
    print("=" * 60)
    
    results = []
    for sid in sorted(scenario_ids):
        result = run_scenario(sid, auto_remediate, wait_seconds, testbed)
        if result:
            results.append(result)
    
    return results


def run_all(
    auto_remediate: bool = True,
    wait_seconds: int = 5,
    testbed: str = "tests/testbed.yaml"
) -> List[ScenarioResult]:
    """Run all registered scenarios."""
    if not SCENARIO_REGISTRY:
        print("[WARNING] No scenarios registered")
        return []
    
    print(f"\n>>> Running ALL scenarios: {len(SCENARIO_REGISTRY)} total")
    print(f">>> Auto-remediate: {'Yes' if auto_remediate else 'No'}")
    print("=" * 60)
    
    results = []
    # Run in order: Phase 1, then 2, then 3
    for phase in ["1", "2", "3"]:
        phase_results = run_phase(phase, auto_remediate, wait_seconds, testbed)
        results.extend(phase_results)
    
    return results


# ---------------------------------------------------------------------------
# Main Entrypoint
# ---------------------------------------------------------------------------

def main() -> int:
    """Main entrypoint for chaos runner."""
    args = parse_args()

    # List mode
    if args.list:
        list_scenarios()
        return 0
    
    # Initialize reporter (for potential use)
    reporter = ChaosReporter()
    results: List[ScenarioResult] = []
    
    # Route to execution mode
    if args.scenario:
        # Single scenario
        result = run_scenario(
            args.scenario,
            auto_remediate=not args.no_remediate,
            wait_seconds=args.wait,
            testbed=args.testbed
        )
        if result:
            results.append(result)
        else:
            return 1  # Scenario not found or failed
    
    elif args.phase:
        # Phase execution
        results = run_phase(
            args.phase,
            auto_remediate=not args.no_remediate,
            wait_seconds=args.wait,
            testbed=args.testbed
        )
    
    elif args.all:
        # All scenarios
        results = run_all(
            auto_remediate=not args.no_remediate,
            wait_seconds=args.wait,
            testbed=args.testbed
        )
    
    # Generate summary
    if args.summary and results:
        summary = generate_summary(results)
        print("\n" + summary)
    
    # Save report if requested
    if args.report and results:
        try:
            paths = reporter.save_report(results, Path(args.report).stem)
            print(f"\n[REPORT] Saved to:")
            print(f"  JSON: {paths['json']}")
            print(f"  TXT:  {paths['txt']}")
        except Exception as e:
            print(f"\n[ERROR] Failed to save report: {e}")
            return 1
    
    # Exit code based on results
    failed = sum(1 for r in results if r.status != "passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())