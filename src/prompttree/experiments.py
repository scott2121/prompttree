from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .ledger import Ledger
from .models import Assignment, ExperimentArm, PromptExperiment
from .registry import Registry


class ExperimentManager:
    def __init__(self, *, registry: Registry, ledger: Ledger) -> None:
        self.registry = registry
        self.ledger = ledger

    def branch_and_start(
        self,
        *,
        family_id: str,
        from_version: str = "current",
        mode: str = "three-arm",
        children: List[Dict[str, str]],
        target_filter: Optional[Dict[str, Any]] = None,
        assignment_unit: str = "run",
    ) -> PromptExperiment:
        parent = self.registry.resolve_version(family_id, from_version)
        family = self.registry.get_family(family_id)
        arms: List[ExperimentArm] = []

        if mode == "three-arm":
            arms.append(ExperimentArm(id="control", version_id=parent.id, weight=34))

        for index, child in enumerate(children, start=1):
            child_id = child["id"]
            self.registry.write_version(
                family_id,
                child_id,
                parent.body,
                label=child.get("label", child_id),
                parent_id=parent.id,
                status="candidate",
                author=child.get("author", "prompttree"),
                hypothesis=child.get("hypothesis", ""),
                tags=child.get("tags", "").split(",") if child.get("tags") else list(parent.tags),
            )
            arm_id = child.get("arm_id") or f"treatment_{index}"
            arms.append(ExperimentArm(id=arm_id, version_id=child_id, weight=33 if mode == "three-arm" else 50))

        experiment_id = f"exp-{family_id}-{children[0]['id']}-{children[-1]['id']}"
        experiment = PromptExperiment(
            id=experiment_id,
            family_id=family_id,
            name=f"{family.name} branch experiment",
            status="running",
            assignment_unit=assignment_unit,
            assignment_strategy="deterministic_hash",
            sticky=True,
            target_filter=target_filter or {},
            arms=arms,
            primary_metrics=["success_rate"],
            secondary_metrics=["manual_review_rate"],
            started_at=datetime.now(timezone.utc).isoformat(),
            metadata={"mode": mode, "parent_version_id": parent.id},
        )
        self.registry.write_experiment(experiment)
        return experiment

    def assign(self, family_id: str, unit_key: str) -> Assignment:
        experiment = self.registry.get_active_experiment(family_id)
        if experiment is None:
            family = self.registry.get_family(family_id)
            return Assignment(
                experiment_id="",
                unit_key=unit_key,
                arm_id="default",
                version_id=family.current_version,
                assignment_hash="",
            )

        existing = self.ledger.get_assignment(experiment.id, unit_key)
        if existing:
            return Assignment(
                experiment_id=existing["experiment_id"],
                unit_key=existing["unit_key"],
                arm_id=existing["arm_id"],
                version_id=existing["version_id"],
                assignment_hash=existing["assignment_hash"],
            )

        digest = hashlib.sha256(f"{experiment.id}:{unit_key}".encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % 100
        arm = self._choose_arm(experiment, bucket)
        assignment_id = self.ledger.record_assignment(
            experiment_id=experiment.id,
            family_id=family_id,
            unit_key=unit_key,
            arm_id=arm.id,
            version_id=arm.version_id,
            assignment_hash=digest,
            sticky=experiment.sticky,
        )
        return Assignment(
            experiment_id=experiment.id,
            unit_key=unit_key,
            arm_id=arm.id,
            version_id=arm.version_id,
            assignment_hash=digest,
        )

    @staticmethod
    def _choose_arm(experiment: PromptExperiment, bucket: int) -> ExperimentArm:
        total = 0
        normalized = ExperimentManager._normalized_weights(experiment.arms)
        for arm, weight in zip(experiment.arms, normalized):
            total += weight
            if bucket < total:
                return arm
        return experiment.arms[-1]

    @staticmethod
    def _normalized_weights(arms: List[ExperimentArm]) -> List[int]:
        weights = [max(arm.weight, 0) for arm in arms]
        total = sum(weights)
        if total <= 0:
            even = 100 // max(len(arms), 1)
            return [even for _ in arms]
        normalized = [int((weight / total) * 100) for weight in weights]
        while sum(normalized) < 100:
            for idx in range(len(normalized)):
                normalized[idx] += 1
                if sum(normalized) == 100:
                    break
        return normalized

