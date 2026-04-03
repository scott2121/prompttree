from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from .experiments import ExperimentManager
from .history import History
from .ledger import Ledger
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
            print(f"{family.id}\t{family.current_version}\t{family.description}")
        return 0

    if command == "version" and args.version_command == "show":
        family_id, version_ref = _split_ref(args.ref)
        registry = Registry.load(args.root / "prompting")
        version = registry.resolve_version(family_id, version_ref)
        print(json.dumps(
            {
                "id": version.id,
                "family_id": version.family_id,
                "label": version.label,
                "parent_id": version.parent_id,
                "status": version.status,
                "author": version.author,
                "created_at": version.created_at,
                "hypothesis": version.hypothesis,
                "body": version.body,
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    if command == "experiment" and args.experiment_command == "branch-and-start":
        registry = Registry.load(args.root / "prompting")
        ledger = Ledger(args.db)
        manager = ExperimentManager(registry=registry, ledger=ledger)
        children = []
        for child_id, child_label in zip(args.child_id, args.child_label):
            children.append({"id": child_id, "label": child_label, "author": "prompttree"})
        experiment = manager.branch_and_start(
            family_id=args.family,
            from_version=args.from_version,
            mode=args.mode,
            children=children,
            assignment_unit=args.assignment_unit,
        )
        print(experiment.id)
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
        print(json.dumps(context.__dict__, ensure_ascii=False, indent=2))
        return 0

    return 1


def _split_ref(ref: str) -> tuple[str, str]:
    if "@" not in ref:
        raise SystemExit("Expected FAMILY@VERSION")
    family_id, version_ref = ref.split("@", 1)
    return family_id, version_ref

