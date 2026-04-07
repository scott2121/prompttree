from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import asdict, dataclass, field
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
class ArtifactHandle:
    kind: str
    uri: str
    mime_type: str = ""
    sha256: str = ""
    size_bytes: Optional[int] = None
    label: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArtifactHandle":
        return cls(
            kind=str(data.get("kind", "file")),
            uri=str(data.get("uri", "")),
            mime_type=str(data.get("mime_type", "")),
            sha256=str(data.get("sha256", "")),
            size_bytes=int(data["size_bytes"]) if data.get("size_bytes") is not None else None,
            label=str(data.get("label", "")),
            metadata=dict(data.get("metadata", {})),
        )


def artifact_from_path(
    path: Path,
    *,
    kind: str = "file",
    label: str = "",
    mime_type: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> ArtifactHandle:
    resolved = path.resolve()
    payload = resolved.read_bytes()
    guessed_mime, _ = mimetypes.guess_type(str(resolved))
    return ArtifactHandle(
        kind=kind,
        uri=str(resolved),
        mime_type=mime_type or guessed_mime or "",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        label=label or resolved.name,
        metadata=metadata or {},
    )


@dataclass(frozen=True)
class PromotionPolicy:
    score_name: str = ""
    direction: str = "higher"
    min_evaluations: int = 1
    required_decisions: List[str] = field(default_factory=list)
    tie_breakers: List[str] = field(default_factory=lambda: ["score", "evaluation_count", "version"])
    ref_names: List[str] = field(default_factory=lambda: ["best", "current"])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["PromotionPolicy"]:
        if not data:
            return None
        return cls(
            score_name=str(data.get("score_name", "")),
            direction=str(data.get("direction", "higher")),
            min_evaluations=int(data.get("min_evaluations", 1)),
            required_decisions=[str(item) for item in data.get("required_decisions", [])],
            tie_breakers=[str(item) for item in data.get("tie_breakers", ["score", "evaluation_count", "version"])],
            ref_names=[str(item) for item in data.get("ref_names", ["best", "current"])],
        )


@dataclass(frozen=True)
class PromptFamily:
    id: str
    name: str
    description: str
    current_version: str
    artifact_kind: str
    refs: Dict[str, str] = field(default_factory=dict)
    stage: str = ""
    promotion_policy: Optional[PromotionPolicy] = None
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
    winner_version_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Assignment:
    experiment_id: str
    unit_key: str
    arm_id: str
    version_id: str
    assignment_hash: str


@dataclass(frozen=True)
class EvaluationRecord:
    run_id: int
    kind: str
    decision: str
    score_name: str = ""
    score: Optional[float] = None
    subscores: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    attachments: List[ArtifactHandle] = field(default_factory=list)
    evaluator_kind: str = "external"
    provider: str = ""
    reviewer_id: str = ""
    created_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VersionSummary:
    family_id: str
    version_id: str
    label: str = ""
    run_count: int = 0
    evaluation_count: int = 0
    score_count: int = 0
    average_score: Optional[float] = None
    latest_score: Optional[float] = None
    latest_decision: str = ""
    decision_counts: Dict[str, int] = field(default_factory=dict)
    latest_run_id: Optional[int] = None
    latest_evaluation_id: Optional[int] = None
    latest_evaluation_at: str = ""
    latest_notes: str = ""
    latest_artifacts: List[ArtifactHandle] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepairContext:
    artifact_kind: str
    dataset: str
    logical_key: str
    current_artifact: Optional[ArtifactHandle]
    recent_adopted_revisions: List[Dict[str, Any]]
    recent_rejected_candidates: List[Dict[str, Any]]
    recent_failure_notes: List[Dict[str, Any]]
    repeated_mistake_flags: List[str]
    generated_at: str
