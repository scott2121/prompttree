from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PromptVersion:
    id: str
    label: str
    family_id: str
    parent_id: Optional[str]
    status: str
    author: str
    created_at: str
    hypothesis: str
    template_path: Path
    body: str
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def render(self, **values: Any) -> str:
        rendered = self.body
        for key, value in values.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
        return Template(rendered).safe_substitute(**{k: str(v) for k, v in values.items()})


@dataclass(frozen=True)
class PromptFamily:
    id: str
    name: str
    description: str
    current_version: str
    artifact_kind: str
    stage: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExperimentArm:
    id: str
    version_id: str
    weight: int


@dataclass(frozen=True)
class PromptExperiment:
    id: str
    family_id: str
    name: str
    status: str
    assignment_unit: str
    assignment_strategy: str
    sticky: bool
    target_filter: Dict[str, Any]
    arms: List[ExperimentArm]
    primary_metrics: List[str]
    secondary_metrics: List[str]
    started_at: str = ""
    ended_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Assignment:
    experiment_id: str
    unit_key: str
    arm_id: str
    version_id: str
    assignment_hash: str


@dataclass(frozen=True)
class RepairContext:
    artifact_kind: str
    dataset: str
    logical_key: str
    current_value: Optional[str]
    recent_adopted_revisions: List[Dict[str, Any]]
    recent_rejected_candidates: List[Dict[str, Any]]
    recent_failure_reasons: List[Dict[str, Any]]
    repeated_mistake_flags: List[str]
    generated_at: str

