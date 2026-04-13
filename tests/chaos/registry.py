# tests/chaos/registry.py
from __future__ import annotations

from typing import Dict, List, Type

SCENARIO_REGISTRY: Dict[int, tuple] = {}

PHASE_REGISTRY: Dict[str, List[int]] = {
    "1": [],
    "2": [],
    "3": [],
}


def register_scenario(
    scenario_id: int,
    scenario_class: Type,
    phase: str = "1",
    auto_remediate_default: bool = True,
) -> None:
    SCENARIO_REGISTRY[scenario_id] = (scenario_class, auto_remediate_default)
    if phase in PHASE_REGISTRY:
        if scenario_id not in PHASE_REGISTRY[phase]:
            PHASE_REGISTRY[phase].append(scenario_id)