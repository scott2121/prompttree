from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .ledger import Ledger
from .models import Assignment, ExperimentArm, PromptExperiment, PromptVersion, PromotionPolicy, VersionSummary
from .registry import Registry


class ExperimentManager:
    def __init__(self, *, registry: Registry, ledger: Ledger) -> None:
        self.registry = registry
        self.ledger = ledger

    def branch(
        self,
        *,
        family_id: str,
        from_version: str = "current",
        mode: str = "three-arm",
        children: List[Dict[str, Any]],
        target_filter: Optional[Dict[str, Any]] = None,
        assignment_unit: str = "run",
    ) -> PromptExperiment:
        parent = self.registry.resolve_version(family_id, from_version)
        family = self.registry.get_family(family_id)
        arms: List[ExperimentArm] = []

        if mode == "three-arm":
            arms.append(ExperimentArm(id="control", version_id=parent.id, weight=34))

        for index, child in enumerate(children, start=1):
            child_id = self._ensure_child_version(family_id=family_id, parent=parent, child=child)
            arm_id = child.get("arm_id") or f"treatment_{index}"
            arms.append(
                ExperimentArm(
                    id=arm_id,
                    version_id=child_id,
                    weight=int(child.get("weight", 33 if mode == "three-arm" else 50)),
                )
            )

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
            primary_metrics=["score"],
            secondary_metrics=["decision_count"],
            started_at=datetime.now(timezone.utc).isoformat(),
            metadata={"mode": mode, "parent_version_id": parent.id},
        )
        self.registry.write_experiment(experiment)
        return experiment

    def branch_and_start(
        self,
        *,
        family_id: str,
        from_version: str = "current",
        mode: str = "three-arm",
        children: List[Dict[str, Any]],
        target_filter: Optional[Dict[str, Any]] = None,
        assignment_unit: str = "run",
    ) -> PromptExperiment:
        return self.branch(
            family_id=family_id,
            from_version=from_version,
            mode=mode,
            children=children,
            target_filter=target_filter,
            assignment_unit=assignment_unit,
        )

    def complete_experiment(
        self,
        experiment_id: str,
        *,
        status: str = "completed",
        winner_version_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PromptExperiment:
        experiment = self.registry.get_experiment(experiment_id)
        merged_metadata = dict(experiment.metadata)
        merged_metadata.update(metadata or {})
        updated = replace(
            experiment,
            status=status,
            ended_at=datetime.now(timezone.utc).isoformat(),
            winner_version_id=winner_version_id or experiment.winner_version_id,
            metadata=merged_metadata,
        )
        self.registry.write_experiment(updated)
        return updated

    def set_ref(
        self,
        *,
        family_id: str,
        ref_name: str,
        version_id: str,
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.set_refs(
            family_id=family_id,
            refs={ref_name: version_id},
            reason=reason,
            metadata=metadata,
        )

    def set_refs(
        self,
        *,
        family_id: str,
        refs: Dict[str, str],
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        family = self.registry.get_family(family_id)
        before_versions = {ref_name: family.refs.get(ref_name) for ref_name in refs}
        self.registry.set_refs(family_id, refs)
        for ref_name, after_version_id in refs.items():
            self.ledger.record_ref_revision(
                family_id=family_id,
                ref_name=ref_name,
                before_version_id=before_versions.get(ref_name),
                after_version_id=after_version_id,
                reason=reason,
                metadata=metadata,
            )

    def promote_version(
        self,
        *,
        family_id: str,
        version_id: str,
        refs: Optional[List[str]] = None,
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        target_refs = refs or ["best", "current"]
        self.set_refs(
            family_id=family_id,
            refs={ref_name: version_id for ref_name in target_refs},
            reason=reason,
            metadata=metadata,
        )

    def select_and_promote(
        self,
        *,
        family_id: str,
        score_name: str = "",
        stage: str = "",
        dataset: str = "",
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[VersionSummary]:
        family = self.registry.get_family(family_id)
        policy = family.promotion_policy or PromotionPolicy(score_name=score_name)
        if score_name:
            policy = replace(policy, score_name=score_name)
        summaries = self.ledger.summarize_versions(
            family_id=family_id,
            score_name=policy.score_name,
            stage=stage,
            dataset=dataset,
        )
        versions_by_id = {version.id: version for version in self.registry.list_versions(family_id)}
        candidates = [
            replace(
                summary,
                label=versions_by_id[summary.version_id].label if summary.version_id in versions_by_id else summary.version_id,
            )
            for summary in summaries
            if self._summary_eligible(summary, policy)
        ]
        if not candidates:
            return None
        winner = self._choose_summary(candidates, policy)
        rationale = {
            "policy": policy.to_dict(),
            "summary": {
                "version_id": winner.version_id,
                "average_score": winner.average_score,
                "latest_score": winner.latest_score,
                "decision_counts": winner.decision_counts,
                "evaluation_count": winner.evaluation_count,
            },
        }
        merged_metadata = dict(metadata or {})
        merged_metadata.update(rationale)
        self.promote_version(
            family_id=family_id,
            version_id=winner.version_id,
            refs=policy.ref_names,
            reason=reason or "Automatically promoted best version under family promotion policy.",
            metadata=merged_metadata,
        )
        experiment = self.registry.get_active_experiment(family_id)
        if experiment is not None:
            self.complete_experiment(
                experiment.id,
                winner_version_id=winner.version_id,
                metadata={"promotion_policy": policy.to_dict()},
            )
        return winner

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
        self.ledger.record_assignment(
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

    def _summary_eligible(self, summary: VersionSummary, policy: PromotionPolicy) -> bool:
        if summary.evaluation_count < policy.min_evaluations:
            return False
        return all(summary.decision_counts.get(decision, 0) > 0 for decision in policy.required_decisions)

    def _choose_summary(self, summaries: List[VersionSummary], policy: PromotionPolicy) -> VersionSummary:
        ordered = sorted(summaries, key=lambda item: self._summary_sort_key(item, policy), reverse=True)
        return ordered[0]

    def _summary_sort_key(self, summary: VersionSummary, policy: PromotionPolicy) -> tuple:
        values: List[Any] = []
        primary_score = summary.average_score
        if primary_score is None:
            primary_value = float("-inf")
        elif policy.direction == "lower":
            primary_value = -primary_score
        else:
            primary_value = primary_score
        values.append(primary_value)
        for tie_breaker in policy.tie_breakers:
            if tie_breaker == "score":
                latest = summary.latest_score
                if latest is None:
                    values.append(float("-inf"))
                elif policy.direction == "lower":
                    values.append(-latest)
                else:
                    values.append(latest)
            elif tie_breaker == "preferred_count":
                values.append(summary.decision_counts.get("preferred", 0))
            elif tie_breaker == "approved_count":
                values.append(summary.decision_counts.get("approved", 0))
            elif tie_breaker == "evaluation_count":
                values.append(summary.evaluation_count)
            elif tie_breaker == "run_count":
                values.append(summary.run_count)
            elif tie_breaker == "version":
                values.append(summary.version_id)
            else:
                values.append(summary.decision_counts.get(tie_breaker, 0))
        return tuple(values)

    def _ensure_child_version(
        self,
        *,
        family_id: str,
        parent: PromptVersion,
        child: Dict[str, Any],
    ) -> str:
        child_id = str(child["id"])
        body = child.get("body")
        if body is None:
            try:
                self.registry.resolve_version(family_id, child_id)
            except FileNotFoundError as exc:
                raise ValueError(
                    f"Child version {family_id}@{child_id} does not exist. "
                    "Provide child['body'] or create the version before branching."
                ) from exc
            return child_id

        tags = child.get("tags")
        if isinstance(tags, str):
            normalized_tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
        elif tags is None:
            normalized_tags = list(parent.tags)
        else:
            normalized_tags = [str(tag).strip() for tag in tags if str(tag).strip()]

        parent_id = child.get("parent_id", parent.id)
        self.registry.write_version(
            family_id,
            child_id,
            str(body),
            label=str(child.get("label", child_id)),
            parent_id=str(parent_id) if parent_id is not None else None,
            status=str(child.get("status", "candidate")),
            author=str(child.get("author", "prompttree")),
            hypothesis=str(child.get("hypothesis", "")),
            tags=normalized_tags,
            metadata=child.get("metadata"),
        )
        return child_id
