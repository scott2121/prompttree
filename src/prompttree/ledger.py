from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
                    stage TEXT,
                    dataset TEXT,
                    target_kind TEXT,
                    target_id TEXT,
                    provider TEXT,
                    model_name TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    input_snapshot TEXT,
                    rendered_prompt TEXT,
                    raw_output TEXT,
                    normalized_output TEXT,
                    token_usage TEXT,
                    latency_ms INTEGER,
                    status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metrics TEXT,
                    reason TEXT,
                    details TEXT,
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
                    location TEXT,
                    before_value TEXT,
                    after_value TEXT,
                    applied_by_run_id INTEGER,
                    assignment_id INTEGER,
                    apply_reason TEXT,
                    adopted INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    metadata TEXT,
                    FOREIGN KEY(applied_by_run_id) REFERENCES prompt_runs(run_id),
                    FOREIGN KEY(assignment_id) REFERENCES assignments(assignment_id)
                );
                """
            )

    def start_run(
        self,
        *,
        family_id: str,
        version_id: str,
        stage: str = "",
        dataset: str = "",
        target_kind: str = "",
        target_id: str = "",
        provider: str = "",
        model_name: str = "",
        input_snapshot: Optional[Dict[str, Any]] = None,
        rendered_prompt: str = "",
        status: str = "running",
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO prompt_runs
                (family_id, version_id, stage, dataset, target_kind, target_id, provider, model_name,
                 started_at, input_snapshot, rendered_prompt, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    utc_now(),
                    json.dumps(input_snapshot or {}, ensure_ascii=False),
                    rendered_prompt,
                    status,
                ),
            )
            return int(cur.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        raw_output: str,
        normalized_output: str,
        status: str,
        token_usage: Optional[Dict[str, Any]] = None,
        latency_ms: Optional[int] = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE prompt_runs
                SET finished_at = ?, raw_output = ?, normalized_output = ?, status = ?, token_usage = ?, latency_ms = ?
                WHERE run_id = ?
                """,
                (
                    utc_now(),
                    raw_output,
                    normalized_output,
                    status,
                    json.dumps(token_usage or {}, ensure_ascii=False),
                    latency_ms,
                    run_id,
                ),
            )

    def record_evaluation(
        self,
        *,
        run_id: int,
        kind: str,
        status: str,
        metrics: Optional[Dict[str, Any]] = None,
        reason: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO evaluations (run_id, kind, status, metrics, reason, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    kind,
                    status,
                    json.dumps(metrics or {}, ensure_ascii=False),
                    reason,
                    json.dumps(details or {}, ensure_ascii=False),
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
        before_value: Optional[str] = None,
        after_value: Optional[str] = None,
        applied_by_run_id: Optional[int] = None,
        assignment_id: Optional[int] = None,
        apply_reason: str = "",
        adopted: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO artifact_revisions
                (artifact_kind, dataset, logical_key, location, before_value, after_value, applied_by_run_id,
                 assignment_id, apply_reason, adopted, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_kind,
                    dataset,
                    logical_key,
                    location,
                    before_value,
                    after_value,
                    applied_by_run_id,
                    assignment_id,
                    apply_reason,
                    int(adopted),
                    utc_now(),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            return int(cur.lastrowid)

    def query(self, sql: str, params: Iterable[Any] = ()) -> List[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute(sql, tuple(params)).fetchall())

