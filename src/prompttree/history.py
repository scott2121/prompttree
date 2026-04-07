from __future__ import annotations

import difflib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .ledger import Ledger
from .models import ArtifactHandle, RepairContext, VersionSummary
from .registry import Registry


class History:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def prompt_change_summary(
        self,
        registry: Registry,
        *,
        family_id: str,
        version_ref: str,
        compare_to: str = "parent",
        score_name: str = "",
        stage: str = "",
        dataset: str = "",
    ) -> Dict[str, Any]:
        version = registry.resolve_version(family_id, version_ref)
        compare_version = self._resolve_compare_version(
            registry,
            family_id=family_id,
            version_id=version.id,
            parent_id=version.parent_id,
            compare_to=compare_to,
        )
        summaries = {
            summary.version_id: summary
            for summary in self.ledger.summarize_versions(
                family_id=family_id,
                score_name=score_name,
                stage=stage,
                dataset=dataset,
            )
        }
        current_summary = summaries.get(version.id)
        compare_summary = summaries.get(compare_version.id) if compare_version else None
        prompt_diff_lines = self._prompt_diff_lines(
            before_text=compare_version.body if compare_version else "",
            after_text=version.body,
            before_label=f"{family_id}@{compare_version.id}" if compare_version else "(initial)",
            after_label=f"{family_id}@{version.id}",
        )
        return {
            "family_id": family_id,
            "version": self._version_to_dict(version),
            "compare_to": self._version_to_dict(compare_version) if compare_version else None,
            "compare_source": "parent" if compare_to == "parent" else "explicit_ref",
            "selection_context": {
                "score_name": score_name,
                "stage": stage,
                "dataset": dataset,
            },
            "prompt_diff": "\n".join(prompt_diff_lines),
            "prompt_change_counts": self._prompt_change_counts(prompt_diff_lines),
            "summary": self._summary_to_dict(current_summary),
            "compare_to_summary": self._summary_to_dict(compare_summary),
            "summary_delta": self._summary_delta(current_summary, compare_summary),
        }

    def artifact_recent(self, *, artifact_kind: str, dataset: str, key: str, limit: int = 3) -> List[Dict[str, Any]]:
        rows = self.ledger.query(
            """
            SELECT revision_id, before_artifact, after_artifact, diff_summary, apply_reason,
                   adopted, created_at, assignment_id, applied_by_run_id, metadata
            FROM artifact_revisions
            WHERE artifact_kind = ? AND dataset = ? AND logical_key = ?
            ORDER BY revision_id DESC
            LIMIT ?
            """,
            (artifact_kind, dataset, key, limit),
        )
        return [self._revision_row_to_dict(row) for row in rows]

    def failed_attempts(self, *, artifact_kind: str, dataset: str, key: str, limit: int = 3) -> List[Dict[str, Any]]:
        rows = self.ledger.query(
            """
            SELECT ar.revision_id, ar.after_artifact, ar.diff_summary, ar.apply_reason, ar.created_at,
                   ev.decision, ev.notes, ev.kind
            FROM artifact_revisions ar
            LEFT JOIN evaluations ev ON ev.run_id = ar.applied_by_run_id
            WHERE ar.artifact_kind = ? AND ar.dataset = ? AND ar.logical_key = ? AND ar.adopted = 0
            ORDER BY ar.revision_id DESC
            LIMIT ?
            """,
            (artifact_kind, dataset, key, limit),
        )
        items: List[Dict[str, Any]] = []
        for row in rows:
            items.append(
                {
                    "revision_id": row["revision_id"],
                    "after_artifact": self._artifact_from_json(row["after_artifact"]),
                    "diff_summary": row["diff_summary"],
                    "apply_reason": row["apply_reason"],
                    "created_at": row["created_at"],
                    "decision": row["decision"],
                    "notes": row["notes"],
                    "kind": row["kind"],
                }
            )
        return items

    def repair_context(
        self,
        *,
        artifact_kind: str,
        dataset: str,
        key: str,
        adopted_limit: int = 3,
        rejected_limit: int = 3,
        failure_reason_limit: int = 3,
    ) -> RepairContext:
        adopted = self.artifact_recent(artifact_kind=artifact_kind, dataset=dataset, key=key, limit=adopted_limit)
        rejected = self.failed_attempts(artifact_kind=artifact_kind, dataset=dataset, key=key, limit=rejected_limit)
        note_rows = self.ledger.query(
            """
            SELECT ev.notes, COUNT(*) AS count
            FROM artifact_revisions ar
            JOIN evaluations ev ON ev.run_id = ar.applied_by_run_id
            WHERE ar.artifact_kind = ? AND ar.dataset = ? AND ar.logical_key = ? AND ev.notes != ''
            GROUP BY ev.notes
            ORDER BY count DESC, ev.notes ASC
            LIMIT ?
            """,
            (artifact_kind, dataset, key, failure_reason_limit),
        )
        failure_notes = [{"notes": row["notes"], "count": row["count"]} for row in note_rows]
        current_artifact = adopted[0]["after_artifact"] if adopted else None
        repeated_flags = [
            f"{item['notes']} repeated {item['count']} times recently"
            for item in failure_notes
            if int(item["count"]) >= 2
        ]
        return RepairContext(
            artifact_kind=artifact_kind,
            dataset=dataset,
            logical_key=key,
            current_artifact=current_artifact,
            recent_adopted_revisions=adopted,
            recent_rejected_candidates=rejected,
            recent_failure_notes=failure_notes,
            repeated_mistake_flags=repeated_flags,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _resolve_compare_version(
        registry: Registry,
        *,
        family_id: str,
        version_id: str,
        parent_id: Optional[str],
        compare_to: str,
    ) -> Optional[Any]:
        if compare_to == "parent":
            return registry.resolve_version(family_id, parent_id) if parent_id else None
        resolved = registry.resolve_version(family_id, compare_to)
        return None if resolved.id == version_id else resolved

    @staticmethod
    def _prompt_diff_lines(
        *,
        before_text: str,
        after_text: str,
        before_label: str,
        after_label: str,
    ) -> List[str]:
        return list(
            difflib.unified_diff(
                before_text.splitlines(),
                after_text.splitlines(),
                fromfile=before_label,
                tofile=after_label,
                lineterm="",
            )
        )

    @staticmethod
    def _prompt_change_counts(diff_lines: List[str]) -> Dict[str, int]:
        added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
        return {"added": added, "removed": removed}

    @staticmethod
    def _summary_to_dict(summary: Optional[VersionSummary]) -> Optional[Dict[str, Any]]:
        if summary is None:
            return None
        return {
            "version_id": summary.version_id,
            "run_count": summary.run_count,
            "evaluation_count": summary.evaluation_count,
            "average_score": summary.average_score,
            "latest_score": summary.latest_score,
            "latest_decision": summary.latest_decision,
            "latest_notes": summary.latest_notes,
            "decision_counts": dict(summary.decision_counts),
            "latest_artifact_uris": [artifact.uri for artifact in summary.latest_artifacts],
        }

    @staticmethod
    def _summary_delta(
        current: Optional[VersionSummary],
        previous: Optional[VersionSummary],
    ) -> Dict[str, Any]:
        return {
            "average_score": History._numeric_delta(
                current.average_score if current else None,
                previous.average_score if previous else None,
            ),
            "latest_score": History._numeric_delta(
                current.latest_score if current else None,
                previous.latest_score if previous else None,
            ),
        }

    @staticmethod
    def _numeric_delta(current: Optional[float], previous: Optional[float]) -> Optional[float]:
        if current is None or previous is None:
            return None
        return current - previous

    @staticmethod
    def _version_to_dict(version: Any) -> Dict[str, Any]:
        return {
            "id": version.id,
            "label": version.label,
            "parent_id": version.parent_id,
            "status": version.status,
            "author": version.author,
            "created_at": version.created_at,
            "hypothesis": version.hypothesis,
            "tags": list(version.tags),
        }

    def _revision_row_to_dict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "revision_id": row["revision_id"],
            "before_artifact": self._artifact_from_json(row["before_artifact"]),
            "after_artifact": self._artifact_from_json(row["after_artifact"]),
            "diff_summary": row["diff_summary"],
            "apply_reason": row["apply_reason"],
            "adopted": bool(row["adopted"]),
            "created_at": row["created_at"],
            "assignment_id": row["assignment_id"],
            "applied_by_run_id": row["applied_by_run_id"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
        }

    @staticmethod
    def _artifact_from_json(value: str) -> Optional[ArtifactHandle]:
        if not value:
            return None
        return ArtifactHandle.from_dict(json.loads(value))
