from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List

from .ledger import Ledger
from .models import RepairContext


class History:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def artifact_recent(self, *, artifact_kind: str, dataset: str, key: str, limit: int = 3) -> List[Dict[str, Any]]:
        rows = self.ledger.query(
            """
            SELECT revision_id, before_value, after_value, apply_reason, adopted, created_at, assignment_id, applied_by_run_id
            FROM artifact_revisions
            WHERE artifact_kind = ? AND dataset = ? AND logical_key = ?
            ORDER BY revision_id DESC
            LIMIT ?
            """,
            (artifact_kind, dataset, key, limit),
        )
        return [dict(row) for row in rows]

    def failed_attempts(self, *, artifact_kind: str, dataset: str, key: str, limit: int = 3) -> List[Dict[str, Any]]:
        rows = self.ledger.query(
            """
            SELECT ar.revision_id, ar.after_value, ar.apply_reason, ar.created_at, ev.reason, ev.kind, ev.status
            FROM artifact_revisions ar
            LEFT JOIN evaluations ev ON ev.run_id = ar.applied_by_run_id
            WHERE ar.artifact_kind = ? AND ar.dataset = ? AND ar.logical_key = ? AND ar.adopted = 0
            ORDER BY ar.revision_id DESC
            LIMIT ?
            """,
            (artifact_kind, dataset, key, limit),
        )
        return [dict(row) for row in rows]

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
        adopted = self.ledger.query(
            """
            SELECT revision_id, before_value, after_value, apply_reason, created_at
            FROM artifact_revisions
            WHERE artifact_kind = ? AND dataset = ? AND logical_key = ? AND adopted = 1
            ORDER BY revision_id DESC
            LIMIT ?
            """,
            (artifact_kind, dataset, key, adopted_limit),
        )
        rejected = self.ledger.query(
            """
            SELECT ar.revision_id, ar.after_value, ar.apply_reason, ar.created_at, ev.reason
            FROM artifact_revisions ar
            LEFT JOIN evaluations ev ON ev.run_id = ar.applied_by_run_id
            WHERE ar.artifact_kind = ? AND ar.dataset = ? AND ar.logical_key = ? AND ar.adopted = 0
            ORDER BY ar.revision_id DESC
            LIMIT ?
            """,
            (artifact_kind, dataset, key, rejected_limit),
        )
        reasons = self.ledger.query(
            """
            SELECT ev.reason, COUNT(*) AS count
            FROM artifact_revisions ar
            JOIN evaluations ev ON ev.run_id = ar.applied_by_run_id
            WHERE ar.artifact_kind = ? AND ar.dataset = ? AND ar.logical_key = ? AND ev.reason != ''
            GROUP BY ev.reason
            ORDER BY count DESC, ev.reason ASC
            LIMIT ?
            """,
            (artifact_kind, dataset, key, failure_reason_limit),
        )
        current_value = adopted[0]["after_value"] if adopted else None
        repeated_flags = self._repeated_mistake_flags([dict(row) for row in reasons])
        return RepairContext(
            artifact_kind=artifact_kind,
            dataset=dataset,
            logical_key=key,
            current_value=current_value,
            recent_adopted_revisions=[dict(row) for row in adopted],
            recent_rejected_candidates=[dict(row) for row in rejected],
            recent_failure_reasons=[dict(row) for row in reasons],
            repeated_mistake_flags=repeated_flags,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _repeated_mistake_flags(reasons: List[Dict[str, Any]]) -> List[str]:
        flags = []
        for item in reasons:
            reason = item.get("reason") or ""
            count = int(item.get("count") or 0)
            if count >= 2:
                flags.append(f"{reason} repeated {count} times recently")
        return flags

