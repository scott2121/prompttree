from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .models import ArtifactHandle, VersionSummary


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


class Ledger:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS prompt_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    family_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    stage TEXT NOT NULL DEFAULT '',
                    dataset TEXT NOT NULL DEFAULT '',
                    target_kind TEXT NOT NULL DEFAULT '',
                    target_id TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    model_name TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    input_snapshot TEXT NOT NULL DEFAULT '{}',
                    rendered_prompt TEXT NOT NULL DEFAULT '',
                    run_metadata TEXT NOT NULL DEFAULT '{}',
                    token_usage TEXT NOT NULL DEFAULT '{}',
                    latency_ms INTEGER,
                    status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS run_artifacts (
                    artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT '',
                    sha256 TEXT NOT NULL DEFAULT '',
                    size_bytes INTEGER,
                    label TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES prompt_runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    score_name TEXT NOT NULL DEFAULT '',
                    score REAL,
                    subscores TEXT NOT NULL DEFAULT '{}',
                    metrics TEXT NOT NULL DEFAULT '{}',
                    notes TEXT NOT NULL DEFAULT '',
                    attachments TEXT NOT NULL DEFAULT '[]',
                    evaluator_kind TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    reviewer_id TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES prompt_runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS assignments (
                    assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    unit_key TEXT NOT NULL,
                    arm_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    assignment_hash TEXT NOT NULL,
                    sticky INTEGER NOT NULL DEFAULT 1,
                    assigned_at TEXT NOT NULL,
                    UNIQUE(experiment_id, unit_key)
                );

                CREATE TABLE IF NOT EXISTS artifact_revisions (
                    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    artifact_kind TEXT NOT NULL,
                    dataset TEXT NOT NULL,
                    logical_key TEXT NOT NULL,
                    location TEXT NOT NULL DEFAULT '',
                    before_artifact TEXT NOT NULL DEFAULT '',
                    after_artifact TEXT NOT NULL DEFAULT '',
                    diff_summary TEXT NOT NULL DEFAULT '',
                    applied_by_run_id INTEGER,
                    assignment_id INTEGER,
                    apply_reason TEXT NOT NULL DEFAULT '',
                    adopted INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(applied_by_run_id) REFERENCES prompt_runs(run_id),
                    FOREIGN KEY(assignment_id) REFERENCES assignments(assignment_id)
                );

                CREATE TABLE IF NOT EXISTS prompt_ref_revisions (
                    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    family_id TEXT NOT NULL,
                    ref_name TEXT NOT NULL,
                    before_version_id TEXT,
                    after_version_id TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_columns(
                conn,
                "prompt_runs",
                {
                    "run_metadata": "TEXT NOT NULL DEFAULT '{}'",
                    "token_usage": "TEXT NOT NULL DEFAULT '{}'",
                    "finished_at": "TEXT NOT NULL DEFAULT ''",
                },
            )
            self._ensure_columns(
                conn,
                "evaluations",
                {
                    "decision": "TEXT NOT NULL DEFAULT ''",
                    "score_name": "TEXT NOT NULL DEFAULT ''",
                    "score": "REAL",
                    "subscores": "TEXT NOT NULL DEFAULT '{}'",
                    "metrics": "TEXT NOT NULL DEFAULT '{}'",
                    "notes": "TEXT NOT NULL DEFAULT ''",
                    "attachments": "TEXT NOT NULL DEFAULT '[]'",
                    "evaluator_kind": "TEXT NOT NULL DEFAULT ''",
                    "provider": "TEXT NOT NULL DEFAULT ''",
                    "reviewer_id": "TEXT NOT NULL DEFAULT ''",
                    "metadata": "TEXT NOT NULL DEFAULT '{}'",
                },
            )
            self._ensure_columns(
                conn,
                "artifact_revisions",
                {
                    "before_artifact": "TEXT NOT NULL DEFAULT ''",
                    "after_artifact": "TEXT NOT NULL DEFAULT ''",
                    "diff_summary": "TEXT NOT NULL DEFAULT ''",
                    "metadata": "TEXT NOT NULL DEFAULT '{}'",
                },
            )

    def record_run(
        self,
        *,
        family_id: str,
        version_id: str,
        run_status: str,
        stage: str = "",
        dataset: str = "",
        target_kind: str = "",
        target_id: str = "",
        provider: str = "",
        model_name: str = "",
        input_snapshot: Optional[Dict[str, Any]] = None,
        rendered_prompt: str = "",
        token_usage: Optional[Dict[str, Any]] = None,
        latency_ms: Optional[int] = None,
        output_artifacts: Optional[Sequence[ArtifactHandle | Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        evaluation: Optional[Dict[str, Any]] = None,
    ) -> tuple[int, Optional[int]]:
        started_at = utc_now()
        finished_at = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO prompt_runs
                (family_id, version_id, stage, dataset, target_kind, target_id, provider, model_name,
                 started_at, finished_at, input_snapshot, rendered_prompt, run_metadata, token_usage,
                 latency_ms, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    family_id,
                    version_id,
                    stage,
                    dataset,
                    target_kind,
                    target_id,
                    provider,
                    model_name,
                    started_at,
                    finished_at,
                    _json_dumps(input_snapshot or {}),
                    rendered_prompt,
                    _json_dumps(metadata or {}),
                    _json_dumps(token_usage or {}),
                    latency_ms,
                    run_status,
                ),
            )
            run_id = int(cur.lastrowid)
            for artifact in output_artifacts or []:
                self._insert_run_artifact(conn, run_id, self._normalize_artifact(artifact))
        evaluation_id: Optional[int] = None
        if evaluation is not None:
            evaluation_id = self.record_evaluation(run_id=run_id, **evaluation)
        return run_id, evaluation_id

    def _insert_run_artifact(self, conn: sqlite3.Connection, run_id: int, artifact: ArtifactHandle) -> int:
        cur = conn.execute(
            """
            INSERT INTO run_artifacts
            (run_id, kind, uri, mime_type, sha256, size_bytes, label, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                artifact.kind,
                artifact.uri,
                artifact.mime_type,
                artifact.sha256,
                artifact.size_bytes,
                artifact.label,
                _json_dumps(artifact.metadata),
                utc_now(),
            ),
        )
        return int(cur.lastrowid)

    def list_run_artifacts(self, run_id: int) -> List[ArtifactHandle]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT kind, uri, mime_type, sha256, size_bytes, label, metadata
                FROM run_artifacts
                WHERE run_id = ?
                ORDER BY artifact_id
                """,
                (run_id,),
            ).fetchall()
        return [
            ArtifactHandle(
                kind=row["kind"],
                uri=row["uri"],
                mime_type=row["mime_type"],
                sha256=row["sha256"],
                size_bytes=row["size_bytes"],
                label=row["label"],
                metadata=_json_loads(row["metadata"], {}),
            )
            for row in rows
        ]

    def record_evaluation(
        self,
        *,
        run_id: int,
        kind: str,
        decision: str,
        score_name: str = "",
        score: Optional[float] = None,
        subscores: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, Any]] = None,
        notes: str = "",
        attachments: Optional[Sequence[ArtifactHandle | Dict[str, Any]]] = None,
        evaluator_kind: str = "external",
        provider: str = "",
        reviewer_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        attachment_dicts = [self._normalize_artifact(item).to_dict() for item in attachments or []]
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO evaluations
                (run_id, kind, decision, score_name, score, subscores, metrics, notes, attachments,
                 evaluator_kind, provider, reviewer_id, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    kind,
                    decision,
                    score_name,
                    score,
                    _json_dumps(subscores or {}),
                    _json_dumps(metrics or {}),
                    notes,
                    _json_dumps(attachment_dicts),
                    evaluator_kind,
                    provider,
                    reviewer_id,
                    _json_dumps(metadata or {}),
                    utc_now(),
                ),
            )
            return int(cur.lastrowid)

    def record_ref_revision(
        self,
        *,
        family_id: str,
        ref_name: str,
        after_version_id: str,
        before_version_id: Optional[str] = None,
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO prompt_ref_revisions
                (family_id, ref_name, before_version_id, after_version_id, reason, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    family_id,
                    ref_name,
                    before_version_id,
                    after_version_id,
                    reason,
                    _json_dumps(metadata or {}),
                    utc_now(),
                ),
            )
            return int(cur.lastrowid)

    def record_assignment(
        self,
        *,
        experiment_id: str,
        family_id: str,
        unit_key: str,
        arm_id: str,
        version_id: str,
        assignment_hash: str,
        sticky: bool = True,
    ) -> int:
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT assignment_id FROM assignments WHERE experiment_id = ? AND unit_key = ?",
                (experiment_id, unit_key),
            ).fetchone()
            if existing:
                return int(existing["assignment_id"])
            cur = conn.execute(
                """
                INSERT INTO assignments
                (experiment_id, family_id, unit_key, arm_id, version_id, assignment_hash, sticky, assigned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    family_id,
                    unit_key,
                    arm_id,
                    version_id,
                    assignment_hash,
                    int(sticky),
                    utc_now(),
                ),
            )
            return int(cur.lastrowid)

    def get_assignment(self, experiment_id: str, unit_key: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM assignments WHERE experiment_id = ? AND unit_key = ?",
                (experiment_id, unit_key),
            ).fetchone()

    def record_artifact_revision(
        self,
        *,
        artifact_kind: str,
        dataset: str,
        logical_key: str,
        location: str = "",
        before_artifact: Optional[ArtifactHandle | Dict[str, Any]] = None,
        after_artifact: Optional[ArtifactHandle | Dict[str, Any]] = None,
        diff_summary: str = "",
        applied_by_run_id: Optional[int] = None,
        assignment_id: Optional[int] = None,
        apply_reason: str = "",
        adopted: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        before_json = _json_dumps(self._normalize_artifact(before_artifact).to_dict()) if before_artifact else ""
        after_json = _json_dumps(self._normalize_artifact(after_artifact).to_dict()) if after_artifact else ""
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO artifact_revisions
                (artifact_kind, dataset, logical_key, location, before_artifact, after_artifact, diff_summary,
                 applied_by_run_id, assignment_id, apply_reason, adopted, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_kind,
                    dataset,
                    logical_key,
                    location,
                    before_json,
                    after_json,
                    diff_summary,
                    applied_by_run_id,
                    assignment_id,
                    apply_reason,
                    int(adopted),
                    utc_now(),
                    _json_dumps(metadata or {}),
                ),
            )
            return int(cur.lastrowid)

    def summarize_versions(
        self,
        *,
        family_id: str,
        score_name: str = "",
        stage: str = "",
        dataset: str = "",
    ) -> List[VersionSummary]:
        filters = ["family_id = ?"]
        params: List[Any] = [family_id]
        if stage:
            filters.append("stage = ?")
            params.append(stage)
        if dataset:
            filters.append("dataset = ?")
            params.append(dataset)

        with self.connect() as conn:
            run_rows = conn.execute(
                f"""
                SELECT *
                FROM prompt_runs
                WHERE {' AND '.join(filters)}
                ORDER BY run_id
                """,
                tuple(params),
            ).fetchall()
            eval_rows = conn.execute(
                f"""
                SELECT e.*, r.version_id
                FROM evaluations e
                JOIN prompt_runs r ON r.run_id = e.run_id
                WHERE {' AND '.join('r.' + clause for clause in filters)}
                ORDER BY e.evaluation_id
                """,
                tuple(params),
            ).fetchall()

        summaries: Dict[str, Dict[str, Any]] = {}
        for run_row in run_rows:
            version_id = run_row["version_id"]
            entry = summaries.setdefault(
                version_id,
                {
                    "run_count": 0,
                    "evaluation_count": 0,
                    "score_count": 0,
                    "scores": [],
                    "latest_run_id": None,
                    "latest_evaluation_id": None,
                    "latest_evaluation_at": "",
                    "latest_notes": "",
                    "latest_decision": "",
                    "latest_score": None,
                    "decision_counts": Counter(),
                },
            )
            entry["run_count"] += 1
            entry["latest_run_id"] = run_row["run_id"]

        for eval_row in eval_rows:
            version_id = eval_row["version_id"]
            entry = summaries.setdefault(
                version_id,
                {
                    "run_count": 0,
                    "evaluation_count": 0,
                    "score_count": 0,
                    "scores": [],
                    "latest_run_id": None,
                    "latest_evaluation_id": None,
                    "latest_evaluation_at": "",
                    "latest_notes": "",
                    "latest_decision": "",
                    "latest_score": None,
                    "decision_counts": Counter(),
                },
            )
            entry["evaluation_count"] += 1
            decision = eval_row["decision"] or ""
            if decision:
                entry["decision_counts"][decision] += 1
            if score_name == "" or eval_row["score_name"] == score_name:
                if eval_row["score"] is not None:
                    entry["scores"].append(float(eval_row["score"]))
                    entry["score_count"] += 1
                    entry["latest_score"] = float(eval_row["score"])
            entry["latest_run_id"] = eval_row["run_id"]
            entry["latest_evaluation_id"] = eval_row["evaluation_id"]
            entry["latest_evaluation_at"] = eval_row["created_at"]
            entry["latest_notes"] = eval_row["notes"]
            entry["latest_decision"] = decision

        result: List[VersionSummary] = []
        for version_id, entry in sorted(summaries.items()):
            latest_artifacts = self.list_run_artifacts(entry["latest_run_id"]) if entry["latest_run_id"] else []
            average_score = (
                sum(entry["scores"]) / len(entry["scores"])
                if entry["scores"]
                else None
            )
            result.append(
                VersionSummary(
                    family_id=family_id,
                    version_id=version_id,
                    run_count=entry["run_count"],
                    evaluation_count=entry["evaluation_count"],
                    score_count=entry["score_count"],
                    average_score=average_score,
                    latest_score=entry["latest_score"],
                    latest_decision=entry["latest_decision"],
                    decision_counts=dict(entry["decision_counts"]),
                    latest_run_id=entry["latest_run_id"],
                    latest_evaluation_id=entry["latest_evaluation_id"],
                    latest_evaluation_at=entry["latest_evaluation_at"],
                    latest_notes=entry["latest_notes"],
                    latest_artifacts=latest_artifacts,
                )
            )
        return result

    def query(self, sql: str, params: Iterable[Any] = ()) -> List[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute(sql, tuple(params)).fetchall())

    @staticmethod
    def _normalize_artifact(value: ArtifactHandle | Dict[str, Any]) -> ArtifactHandle:
        if isinstance(value, ArtifactHandle):
            return value
        return ArtifactHandle.from_dict(dict(value))

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection, table_name: str, columns: Dict[str, str]) -> None:
        existing = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, definition in columns.items():
            if column_name in existing:
                continue
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
