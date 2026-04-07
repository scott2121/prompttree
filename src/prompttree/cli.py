from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .experiments import ExperimentManager
from .history import History
from .ledger import Ledger
from .models import ArtifactHandle, PromotionPolicy
from .registry import Registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prompttree")
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("init", help="Initialize prompttree layout")
    init_parser.add_argument("--root", type=Path, default=Path("."))

    family_parser = sub.add_parser("family", help="Family operations")
    family_sub = family_parser.add_subparsers(dest="family_command", required=True)
    family_list = family_sub.add_parser("list")
    family_list.add_argument("--root", type=Path, default=Path("."))

    version_parser = sub.add_parser("version", help="Version operations")
    version_sub = version_parser.add_subparsers(dest="version_command", required=True)
    version_show = version_sub.add_parser("show")
    version_show.add_argument("--root", type=Path, default=Path("."))
    version_show.add_argument("ref")
    version_diff = version_sub.add_parser("diff", help="Show prompt diff and result deltas")
    version_diff.add_argument("--root", type=Path, default=Path("."))
    version_diff.add_argument("--db", type=Path, default=Path(".prompttree/prompttree.db"))
    version_diff.add_argument("--compare-to", default="parent")
    version_diff.add_argument("--score-name", default="")
    version_diff.add_argument("--stage", default="")
    version_diff.add_argument("--dataset", default="")
    version_diff.add_argument("ref")

    ref_parser = sub.add_parser("ref", help="Named ref operations")
    ref_sub = ref_parser.add_subparsers(dest="ref_command", required=True)
    ref_list = ref_sub.add_parser("list")
    ref_list.add_argument("--root", type=Path, default=Path("."))
    ref_list.add_argument("--family", required=True)
    ref_set = ref_sub.add_parser("set")
    ref_set.add_argument("--root", type=Path, default=Path("."))
    ref_set.add_argument("--db", type=Path, default=Path(".prompttree/prompttree.db"))
    ref_set.add_argument("--family", required=True)
    ref_set.add_argument("--name", required=True)
    ref_set.add_argument("--version", required=True)
    ref_set.add_argument("--reason", default="")

    exp_parser = sub.add_parser("experiment", help="Experiment operations")
    exp_sub = exp_parser.add_subparsers(dest="experiment_command", required=True)
    branch = exp_sub.add_parser("branch-and-start")
    branch.add_argument("--root", type=Path, default=Path("."))
    branch.add_argument("--db", type=Path, default=Path(".prompttree/prompttree.db"))
    branch.add_argument("--family", required=True)
    branch.add_argument("--from", dest="from_version", default="current")
    branch.add_argument("--mode", default="three-arm", choices=["two-arm", "three-arm"])
    branch.add_argument("--assignment-unit", default="run")
    branch.add_argument("--child-id", action="append", required=True)
    branch.add_argument("--child-label", action="append", required=True)
    branch.add_argument("--child-body-file", action="append", type=Path)
    show = exp_sub.add_parser("show")
    show.add_argument("--root", type=Path, default=Path("."))
    show.add_argument("--family")
    show.add_argument("--id")

    evaluation_parser = sub.add_parser("evaluation", help="Evaluation operations")
    evaluation_sub = evaluation_parser.add_subparsers(dest="evaluation_command", required=True)
    record = evaluation_sub.add_parser("record")
    record.add_argument("--db", type=Path, required=True)
    record.add_argument("--run-id", type=int, required=True)
    record.add_argument("--kind", required=True)
    record.add_argument("--decision", required=True)
    record.add_argument("--score-name", default="")
    record.add_argument("--score", type=float)
    record.add_argument("--notes", default="")
    record.add_argument("--metrics-file", type=Path)
    record.add_argument("--subscores-file", type=Path)
    record.add_argument("--reviewer-id", default="")
    record.add_argument("--provider", default="")
    record.add_argument("--evaluator-kind", default="external")
    record.add_argument("--attachment-uri", action="append", default=[])

    scoreboard = sub.add_parser("scoreboard", help="Show version summaries")
    scoreboard.add_argument("--root", type=Path, default=Path("."))
    scoreboard.add_argument("--db", type=Path, default=Path(".prompttree/prompttree.db"))
    scoreboard.add_argument("--family", required=True)
    scoreboard.add_argument("--score-name", default="")
    scoreboard.add_argument("--stage", default="")
    scoreboard.add_argument("--dataset", default="")

    promote = sub.add_parser("promote", help="Automatic promotion commands")
    promote_sub = promote.add_subparsers(dest="promote_command", required=True)
    promote_auto = promote_sub.add_parser("auto")
    promote_auto.add_argument("--root", type=Path, default=Path("."))
    promote_auto.add_argument("--db", type=Path, default=Path(".prompttree/prompttree.db"))
    promote_auto.add_argument("--family", required=True)
    promote_auto.add_argument("--score-name", default="")
    promote_auto.add_argument("--stage", default="")
    promote_auto.add_argument("--dataset", default="")

    repair = sub.add_parser("repair-context", help="Show recent repair context")
    repair.add_argument("--db", type=Path, required=True)
    repair.add_argument("--kind", required=True)
    repair.add_argument("--dataset", required=True)
    repair.add_argument("--key", required=True)
    repair.add_argument("--limit", type=int, default=3)

    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command

    if command == "init":
        registry = Registry.load(args.root / "prompting")
        registry.init_layout()
        Ledger(args.root / ".prompttree" / "prompttree.db")
        print(f"Initialized PromptTree in {args.root}")
        return 0

    if command == "family" and args.family_command == "list":
        registry = Registry.load(args.root / "prompting")
        for family in registry.list_families():
            policy = family.promotion_policy.score_name if family.promotion_policy else "-"
            print(f"{family.id}\t{family.current_version}\t{policy}\t{family.description}")
        return 0

    if command == "version" and args.version_command == "show":
        family_id, version_ref = _split_ref(args.ref)
        registry = Registry.load(args.root / "prompting")
        version = registry.resolve_version(family_id, version_ref)
        print(
            json.dumps(
                {
                    "id": version.id,
                    "family_id": version.family_id,
                    "label": version.label,
                    "parent_id": version.parent_id,
                    "status": version.status,
                    "author": version.author,
                    "created_at": version.created_at,
                    "hypothesis": version.hypothesis,
                    "tags": version.tags,
                    "metadata": version.metadata,
                    "body": version.body,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if command == "version" and args.version_command == "diff":
        family_id, version_ref = _split_ref(args.ref)
        registry = Registry.load(args.root / "prompting")
        history = History(Ledger(args.db))
        payload = history.prompt_change_summary(
            registry,
            family_id=family_id,
            version_ref=version_ref,
            compare_to=args.compare_to,
            score_name=args.score_name,
            stage=args.stage,
            dataset=args.dataset,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if command == "ref" and args.ref_command == "list":
        registry = Registry.load(args.root / "prompting")
        refs = registry.list_refs(args.family)
        try:
            refs["latest"] = registry.resolve_version(args.family, "latest").id
        except FileNotFoundError:
            pass
        for ref_name, version_id in sorted(refs.items()):
            print(f"{ref_name}\t{version_id}")
        return 0

    if command == "ref" and args.ref_command == "set":
        registry = Registry.load(args.root / "prompting")
        ledger = Ledger(args.db)
        manager = ExperimentManager(registry=registry, ledger=ledger)
        manager.set_ref(
            family_id=args.family,
            ref_name=args.name,
            version_id=args.version,
            reason=args.reason,
        )
        print(f"{args.family}@{args.name}\t{args.version}")
        return 0

    if command == "experiment" and args.experiment_command == "branch-and-start":
        registry = Registry.load(args.root / "prompting")
        ledger = Ledger(args.db)
        manager = ExperimentManager(registry=registry, ledger=ledger)
        if len(args.child_id) != len(args.child_label):
            raise SystemExit("--child-id and --child-label must be provided the same number of times")
        body_files = args.child_body_file or []
        if body_files and len(body_files) != len(args.child_id):
            raise SystemExit("--child-body-file must match the number of --child-id values")
        children = []
        for index, (child_id, child_label) in enumerate(zip(args.child_id, args.child_label)):
            child = {"id": child_id, "label": child_label, "author": "prompttree"}
            if body_files:
                child["body"] = body_files[index].read_text(encoding="utf-8")
            children.append(child)
        experiment = manager.branch(
            family_id=args.family,
            from_version=args.from_version,
            mode=args.mode,
            children=children,
            assignment_unit=args.assignment_unit,
        )
        print(experiment.id)
        return 0

    if command == "experiment" and args.experiment_command == "show":
        registry = Registry.load(args.root / "prompting")
        if args.id:
            experiment = registry.get_experiment(args.id)
        elif args.family:
            experiment = registry.get_active_experiment(args.family)
            if experiment is None:
                raise SystemExit(f"No active experiment for family: {args.family}")
        else:
            raise SystemExit("Provide --id or --family")
        print(json.dumps(_experiment_to_dict(experiment), ensure_ascii=False, indent=2))
        return 0

    if command == "evaluation" and args.evaluation_command == "record":
        ledger = Ledger(args.db)
        metrics = _load_optional_data(args.metrics_file, default={})
        subscores = _load_optional_data(args.subscores_file, default={})
        attachments = [
            ArtifactHandle(kind="file", uri=uri, label=Path(uri).name)
            for uri in args.attachment_uri
        ]
        evaluation_id = ledger.record_evaluation(
            run_id=args.run_id,
            kind=args.kind,
            decision=args.decision,
            score_name=args.score_name,
            score=args.score,
            metrics=metrics,
            subscores=subscores,
            notes=args.notes,
            evaluator_kind=args.evaluator_kind,
            provider=args.provider,
            reviewer_id=args.reviewer_id,
            attachments=attachments,
        )
        print(evaluation_id)
        return 0

    if command == "scoreboard":
        registry = Registry.load(args.root / "prompting")
        ledger = Ledger(args.db)
        summaries = ledger.summarize_versions(
            family_id=args.family,
            score_name=args.score_name,
            stage=args.stage,
            dataset=args.dataset,
        )
        versions_by_id = {version.id: version for version in registry.list_versions(args.family)}
        rows = []
        for summary in summaries:
            rows.append(
                {
                    "version_id": summary.version_id,
                    "label": versions_by_id.get(summary.version_id).label if summary.version_id in versions_by_id else summary.version_id,
                    "run_count": summary.run_count,
                    "evaluation_count": summary.evaluation_count,
                    "average_score": summary.average_score,
                    "latest_score": summary.latest_score,
                    "latest_decision": summary.latest_decision,
                    "decision_counts": summary.decision_counts,
                    "latest_artifacts": [artifact.to_dict() for artifact in summary.latest_artifacts],
                }
            )
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    if command == "promote" and args.promote_command == "auto":
        registry = Registry.load(args.root / "prompting")
        ledger = Ledger(args.db)
        manager = ExperimentManager(registry=registry, ledger=ledger)
        winner = manager.select_and_promote(
            family_id=args.family,
            score_name=args.score_name,
            stage=args.stage,
            dataset=args.dataset,
        )
        if winner is None:
            print("null")
        else:
            print(
                json.dumps(
                    {
                        "version_id": winner.version_id,
                        "label": winner.label,
                        "average_score": winner.average_score,
                        "latest_score": winner.latest_score,
                        "decision_counts": winner.decision_counts,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 0

    if command == "repair-context":
        history = History(Ledger(args.db))
        context = history.repair_context(
            artifact_kind=args.kind,
            dataset=args.dataset,
            key=args.key,
            adopted_limit=args.limit,
            rejected_limit=args.limit,
            failure_reason_limit=args.limit,
        )
        payload = {
            "artifact_kind": context.artifact_kind,
            "dataset": context.dataset,
            "logical_key": context.logical_key,
            "current_artifact": context.current_artifact.to_dict() if context.current_artifact else None,
            "recent_adopted_revisions": _serialize_revision_items(context.recent_adopted_revisions),
            "recent_rejected_candidates": _serialize_revision_items(context.recent_rejected_candidates),
            "recent_failure_notes": context.recent_failure_notes,
            "repeated_mistake_flags": context.repeated_mistake_flags,
            "generated_at": context.generated_at,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    return 1


def _split_ref(ref: str) -> tuple[str, str]:
    if "@" not in ref:
        raise SystemExit("Expected FAMILY@VERSION")
    family_id, version_ref = ref.split("@", 1)
    return family_id, version_ref


def _load_optional_data(path: Path | None, *, default: Dict[str, Any]) -> Dict[str, Any]:
    if path is None:
        return default
    text = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        return dict(yaml.safe_load(text) or {})
    return dict(json.loads(text))


def _experiment_to_dict(experiment: Any) -> Dict[str, Any]:
    return {
        "id": experiment.id,
        "family_id": experiment.family_id,
        "name": experiment.name,
        "status": experiment.status,
        "assignment_unit": experiment.assignment_unit,
        "assignment_strategy": experiment.assignment_strategy,
        "sticky": experiment.sticky,
        "target_filter": experiment.target_filter,
        "arms": [vars(arm) for arm in experiment.arms],
        "primary_metrics": experiment.primary_metrics,
        "secondary_metrics": experiment.secondary_metrics,
        "started_at": experiment.started_at,
        "ended_at": experiment.ended_at,
        "winner_version_id": experiment.winner_version_id,
        "metadata": experiment.metadata,
    }


def _serialize_revision_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    for item in items:
        serialized.append(
            {
                key: value.to_dict() if isinstance(value, ArtifactHandle) else value
                for key, value in item.items()
            }
        )
    return serialized
