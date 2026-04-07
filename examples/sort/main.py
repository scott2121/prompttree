from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import string
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from statistics import mean
from textwrap import dedent
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from prompttree import ArtifactHandle, ExperimentManager, Ledger, PromotionPolicy, Registry, artifact_from_path, collect_prompt_hops

EXAMPLE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = EXAMPLE_DIR / "output"
GENERATED_DIR = OUTPUT_DIR / "generated"
LINEAGE_CONTEXT_DIR = OUTPUT_DIR / "lineage-contexts"
RUN_PATH = OUTPUT_DIR / "run.txt"
FAMILY_ID = "sort-optimizer"
CODEX_TIMEOUT_SECONDS = 180
DEFAULT_ROUND_COUNT = 2
BASELINE_VERSION_ID = "V1"

SORT_SPEC = [
    {"field": "age", "order": "asc"},
    {"field": "score", "order": "desc"},
    {"field": "name", "order": "asc"},
]

PROMPT_V1 = dedent(
    """
    You are Codex. Write a Python function named `solve(records)` that returns records sorted by:
    1. `age` ascending
    2. `score` descending
    3. `name` ascending

    Requirements:
    - Prefer clarity over optimization.
    - Return a new list.
    - The input records are dictionaries.
    - Output code only.
    """
).strip()

PROMPT_V2 = dedent(
    """
    You are Codex. Write a Python function named `solve(records)` that sorts dictionaries by:
    1. `age` ascending
    2. `score` descending
    3. `name` ascending

    Optimization goal:
    - Minimize allocations while staying correct.
    - Copy the input list once, then sort that list in place.
    - Use one composite sort key.
    - Return the sorted copy.
    - Output code only.
    """
).strip()

PROMPT_V3 = dedent(
    """
    You are Codex. Write a Python function named `solve(records)` that sorts dictionaries by:
    1. `age` ascending
    2. `score` descending
    3. `name` ascending

    Optimization goal:
    - Keep correctness identical to the baseline.
    - Use Python's stable sort intentionally.
    - Prefer `operator.itemgetter` if it improves the hot path.
    - Return a new list.
    - Output code only.
    """
).strip()

GENERATED_CODE_BY_VERSION: Dict[str, str] = {}
DEPARTMENTS = ["sales", "research", "ops", "design", "finance", "hr"]
CITIES = ["tokyo", "osaka", "nagoya", "fukuoka", "sapporo", "kyoto"]


def version_id(number: int) -> str:
    return f"V{number}"


def allocate_version_ids(registry: Registry, family_id: str, count: int) -> List[str]:
    start_number = len(registry.list_versions(family_id)) + 1
    return [version_id(number) for number in range(start_number, start_number + count)]


def reset_demo_workspace() -> Path:
    workspace = Path(tempfile.gettempdir()) / "prompttree-sort-optimization"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def prepare_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if GENERATED_DIR.exists():
        shutil.rmtree(GENERATED_DIR)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    if LINEAGE_CONTEXT_DIR.exists():
        shutil.rmtree(LINEAGE_CONTEXT_DIR)
    LINEAGE_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    if RUN_PATH.exists():
        RUN_PATH.unlink()


def seed_registry(workspace: Path) -> Registry:
    registry = Registry.load(workspace / "prompting")
    registry.init_layout()
    registry.create_family(
        family_id=FAMILY_ID,
        name="Sort Optimizer Prompt",
        description="Codex prompts for generating a composite-key sort implementation.",
        current_version=version_id(1),
        artifact_kind="python_source",
        stage="benchmark",
        promotion_policy=PromotionPolicy(
            score_name="weighted_cost",
            direction="lower",
            min_evaluations=1,
            tie_breakers=["score", "evaluation_count", "version"],
        ),
    )
    registry.write_version(
        FAMILY_ID,
        version_id(1),
        PROMPT_V1,
        label="baseline clarity prompt",
        parent_id=None,
        status="current",
        author="example",
        hypothesis="A simple Codex prompt should produce correct code, but not the fastest code.",
        tags=["codex", "baseline", "sort"],
    )
    return registry


def register_v2_candidates(registry: Registry, ledger: Ledger) -> tuple[ExperimentManager, object]:
    manager = ExperimentManager(registry=registry, ledger=ledger)
    experiment = manager.branch(
        family_id=FAMILY_ID,
        from_version="current",
        mode="three-arm",
        children=[
            {
                "id": version_id(2),
                "label": "single composite key",
                "author": "example",
                "hypothesis": "One copy plus one composite key should beat the baseline on time and memory.",
                "body": PROMPT_V2,
                "tags": ["codex", "candidate", "sort", "optimized"],
            },
            {
                "id": version_id(3),
                "label": "stable sort with itemgetter",
                "author": "example",
                "hypothesis": "Stable multi-pass sorting with itemgetter may outperform the tuple-key approach.",
                "body": PROMPT_V3,
                "tags": ["codex", "candidate", "sort", "optimized"],
            },
        ],
        assignment_unit="benchmark_suite",
    )
    return manager, experiment


def make_name(rng: random.Random, used: Set[str]) -> str:
    vowels = "aeiou"
    consonants = "".join(c for c in string.ascii_lowercase if c not in vowels)
    while True:
        length = rng.randint(4, 8)
        start_with_consonant = rng.choice([True, False])
        chars = []
        for index in range(length):
            use_consonant = (index % 2 == 0 and start_with_consonant) or (index % 2 == 1 and not start_with_consonant)
            pool = consonants if use_consonant else vowels
            chars.append(rng.choice(pool))
        name = "".join(chars)
        if name not in used:
            used.add(name)
            return name


def difficulty_ranges(level: str) -> Tuple[int, int, int, int]:
    if level == "easy":
        return 18, 65, 0, 100
    if level == "medium":
        return 18, 35, 0, 50
    return 20, 25, 0, 10


def generate_records(rng: random.Random, n: int) -> List[Dict[str, Any]]:
    difficulty = rng.choices(["easy", "medium", "hard"], weights=[0.15, 0.35, 0.50], k=1)[0]
    age_min, age_max, score_min, score_max = difficulty_ranges(difficulty)
    used_names: Set[str] = set()
    records: List[Dict[str, Any]] = []
    anchor_count = max(1, min(6, n // 8))
    anchors = [(rng.randint(age_min, age_max), rng.randint(score_min, score_max)) for _ in range(anchor_count)]
    for index in range(n):
        if rng.random() < 0.65:
            age, score = rng.choice(anchors)
            if rng.random() < 0.25:
                age = rng.randint(age_min, age_max)
            if rng.random() < 0.25:
                score = rng.randint(score_min, score_max)
        else:
            age = rng.randint(age_min, age_max)
            score = rng.randint(score_min, score_max)
        records.append(
            {
                "name": make_name(rng, used_names),
                "age": age,
                "score": score,
                "department": rng.choice(DEPARTMENTS),
                "city": rng.choice(CITIES),
                "uid": f"u{index:05d}",
            }
        )
    rng.shuffle(records)
    return records


def gold_sort(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(records, key=lambda row: (row["age"], -row["score"], row["name"]))


def build_cases() -> Tuple[List[List[Dict[str, Any]]], List[List[Dict[str, Any]]]]:
    correctness = [generate_records(random.Random(1000 + index), 120 + (index % 5) * 25) for index in range(12)]
    benchmark = [generate_records(random.Random(20000 + size), size) for size in [2000, 8000, 16000]]
    return correctness, benchmark


def run_codex_cli(prompt: str, *, schema: Dict[str, Any]) -> str:
    with tempfile.TemporaryDirectory(prefix="prompttree-codex-") as temp_dir:
        temp_path = Path(temp_dir)
        schema_path = temp_path / "schema.json"
        output_path = temp_path / "response.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        command = [
            "codex",
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "workspace-write",
            "-C",
            str(REPO_ROOT),
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
            "-",
        ]
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=CODEX_TIMEOUT_SECONDS,
            check=False,
        )
        response_text = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else result.stdout.strip()
        if result.returncode != 0 or not response_text:
            raise RuntimeError(f"codex exec failed (exit={result.returncode}). stderr tail:\n{result.stderr[-1200:]}")
        return response_text


def generate_code_with_codex(version_id: str, rendered_prompt: str) -> str:
    if version_id in GENERATED_CODE_BY_VERSION:
        return GENERATED_CODE_BY_VERSION[version_id]
    prompt = (
        "You are Codex running inside an automated benchmark harness.\n"
        "Generate Python source code for the requested function.\n\n"
        f"{rendered_prompt}\n\n"
        "Additional requirements:\n"
        "- Return valid Python source in the `code` field.\n"
        "- Define a top-level function named `solve(records)`.\n"
        "- Do not include markdown fences.\n"
        "- Do not include explanations.\n"
    )
    schema = {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"], "additionalProperties": False}
    last_error: Optional[str] = None
    for _ in range(3):
        trial_prompt = prompt if not last_error else f"{prompt}\nPrevious issue: {last_error}\nRegenerate from scratch.\n"
        payload = json.loads(run_codex_cli(trial_prompt, schema=schema))
        code = _extract_python_code(payload["code"])
        try:
            solver = load_solver(code)
            probe = [{"name": "a", "age": 2, "score": 1}, {"name": "b", "age": 1, "score": 2}]
            result = solver(probe)
            if not isinstance(result, list):
                raise TypeError("solve(records) must return a list")
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        GENERATED_CODE_BY_VERSION[version_id] = code
        return code
    raise RuntimeError(f"Could not generate valid code for {version_id}: {last_error}")


def _extract_python_code(text: str) -> str:
    stripped = text.strip()
    fence_match = re.search(r"```(?:python)?\s*(.*?)```", stripped, re.DOTALL)
    return fence_match.group(1).strip() if fence_match else stripped


def load_solver(code: str):
    namespace: Dict[str, Any] = {}
    exec(code, namespace)
    return namespace["solve"]


def benchmark_once(solver, records: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int, int]:
    tracemalloc.start()
    started = time.perf_counter_ns()
    output = solver(list(records))
    elapsed_ns = time.perf_counter_ns() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return output, elapsed_ns, peak_bytes


def evaluate_version(
    registry: Registry,
    ledger: Ledger,
    version_id: str,
    correctness_cases: List[List[Dict[str, Any]]],
    benchmark_cases: List[List[Dict[str, Any]]],
    *,
    round_name: str,
) -> Dict[str, Any]:
    version = registry.resolve_version(FAMILY_ID, version_id)
    rendered_prompt = version.body
    code = generate_code_with_codex(version.id, rendered_prompt)
    generated_path = GENERATED_DIR / f"{version.id}.py"
    generated_path.write_text(code.rstrip() + "\n", encoding="utf-8")
    code_artifact = artifact_from_path(generated_path, kind="python", label=generated_path.name)
    ledger.record_run(
        family_id=FAMILY_ID,
        version_id=version.id,
        run_status="succeeded",
        stage="code_generation",
        dataset="sort-benchmark",
        target_kind="code_file",
        target_id=f"{round_name}:{version.id}",
        provider="codex",
        model_name="codex-cli",
        rendered_prompt=rendered_prompt,
        output_artifacts=[code_artifact],
        metadata={"round": round_name},
    )

    solver = load_solver(code)
    failures: List[str] = []
    for index, records in enumerate(correctness_cases):
        if solver(list(records)) != gold_sort(records):
            failures.append(f"correctness-{index:02d}")

    elapsed_samples: List[int] = []
    peak_samples: List[int] = []
    for index, records in enumerate(benchmark_cases):
        output, elapsed_ns, peak_bytes = benchmark_once(solver, records)
        if output != gold_sort(records):
            failures.append(f"bench-{index:02d}")
        elapsed_samples.append(elapsed_ns)
        peak_samples.append(peak_bytes)

    run_status = "failed" if failures else "succeeded"
    benchmark_run_id, _ = ledger.record_run(
        family_id=FAMILY_ID,
        version_id=version.id,
        run_status=run_status,
        stage="benchmark",
        dataset="sort-benchmark",
        target_kind="benchmark_suite",
        target_id=f"{round_name}:{version.id}",
        provider="benchmark-harness",
        model_name="python",
        rendered_prompt=rendered_prompt,
        output_artifacts=[code_artifact],
        metadata={"round": round_name, "generated_file": str(generated_path)},
    )
    avg_time_ns = int(mean(elapsed_samples))
    avg_peak_bytes = int(mean(peak_samples))
    return {
        "run_id": benchmark_run_id,
        "version_id": version.id,
        "label": version.label,
        "parent_id": version.parent_id,
        "round": round_name,
        "prompt": rendered_prompt,
        "code": code,
        "generated_file": str(generated_path),
        "failure_count": len(failures),
        "failures": failures,
        "avg_time_ns": avg_time_ns,
        "avg_peak_bytes": avg_peak_bytes,
    }


def add_benchmark_evaluations(ledger: Ledger, results: List[Dict[str, Any]], *, baseline: Dict[str, Any]) -> None:
    for item in results:
        if item["failure_count"]:
            decision = "rejected"
            score = None
            notes = f"Failed cases: {', '.join(item['failures'])}"
        else:
            decision = "accepted"
            score = round(
                0.7 * (item["avg_time_ns"] / baseline["avg_time_ns"]) + 0.3 * (item["avg_peak_bytes"] / baseline["avg_peak_bytes"]),
                3,
            )
            notes = (
                f"avg_time_ms={item['avg_time_ns'] / 1_000_000:.3f}, "
                f"avg_peak_kb={item['avg_peak_bytes'] / 1024:.1f}"
            )
        item["score"] = float("inf") if score is None else score
        ledger.record_evaluation(
            run_id=item["run_id"],
            kind="benchmark_summary",
            decision=decision,
            score_name="weighted_cost",
            score=score,
            metrics={
                "avg_time_ns": item["avg_time_ns"],
                "avg_peak_bytes": item["avg_peak_bytes"],
                "failure_count": item["failure_count"],
                "round": item["round"],
            },
            notes=notes,
            evaluator_kind="deterministic",
            provider="benchmark-harness",
            metadata={"generated_file": item["generated_file"]},
        )


def choose_winner(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    return sorted(
        results,
        key=lambda item: (item["failure_count"], item["score"], item["avg_time_ns"], item["avg_peak_bytes"]),
    )[0]


def summary_by_version(results: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for item in results:
        latest[item["version_id"]] = {
            "round": item["round"],
            "score": item["score"],
            "avg_time_ms": round(item["avg_time_ns"] / 1_000_000, 3),
            "avg_peak_kb": round(item["avg_peak_bytes"] / 1024, 1),
            "failures": item["failure_count"],
            "notes": " / ".join(item["failures"]) if item["failures"] else "accepted",
            "generated_file": item["generated_file"],
        }
    return latest


def record_prompt_generation_run(ledger: Ledger, variant: Dict[str, str], parent_version_id: str, round_name: str) -> None:
    ledger.record_run(
        family_id=FAMILY_ID,
        version_id=variant["id"],
        run_status="succeeded",
        stage="prompt_generation",
        dataset="sort-benchmark",
        target_kind="prompt_variant",
        target_id=f"{round_name}:{variant['id']}",
        provider="codex",
        model_name="codex-cli",
        rendered_prompt=variant["body"],
        output_artifacts=[
            ArtifactHandle(
                kind="text",
                uri=f"inline://prompt/{variant['id']}",
                mime_type="text/plain",
                label=variant["id"],
                metadata={"text": variant["body"], "parent_version_id": parent_version_id},
            )
        ],
        metadata={"label": variant["label"], "hypothesis": variant["hypothesis"]},
    )


def generate_prompt_variants_with_codex(
    lineage_context: List[Dict[str, Any]],
    *,
    round_number: int,
    candidate_ids: List[str],
) -> List[Dict[str, str]]:
    winner = lineage_context[0]
    history_note = "\n".join(
        f"- {item['version_id']}: score={item['summary'].get('score', 'n/a')}, "
        f"time_ms={item['summary'].get('avg_time_ms', 'n/a')}, "
        f"peak_kb={item['summary'].get('avg_peak_kb', 'n/a')}, "
        f"notes={item['summary'].get('notes', '')}"
        for item in lineage_context
    )
    prompt = (
        "You are improving prompts for Codex CLI.\n"
        "Create exactly two distinct candidate prompts for a Python sort benchmark.\n\n"
        f"Round: {round_number}\n"
        f"Current incumbent: {winner['version_id']}\n"
        "Recent lineage:\n"
        f"{history_note}\n\n"
        "Each candidate prompt body must:\n"
        "- Be addressed to Codex.\n"
        "- Ask for a Python function named `solve(records)`.\n"
        "- Preserve this ordering: age ascending, score descending, name ascending.\n"
        "- Return code only and a new list.\n"
        "- Focus on a distinct optimization strategy from the other candidate.\n\n"
        "Parent prompt body:\n"
        f"{winner['prompt']}\n\n"
        f"- {candidate_ids[0]} should refine the winner's best traits more explicitly.\n"
        f"- {candidate_ids[1]} should try a different strategy such as DSU or compact composite key.\n\n"
        "Return JSON matching the provided schema."
    )
    schema = {
        "type": "object",
        "properties": {
            "variants": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "hypothesis": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["label", "hypothesis", "body"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["variants"],
        "additionalProperties": False,
    }
    payload = json.loads(run_codex_cli(prompt, schema=schema))
    variants = payload["variants"]
    return [
        {
            "id": candidate_ids[index],
            "label": variants[index]["label"].strip(),
            "hypothesis": variants[index]["hypothesis"].strip(),
            "body": variants[index]["body"].strip(),
        }
        for index in range(2)
    ]


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the sort prompt discovery example.")
    parser.add_argument("--round", type=int, default=DEFAULT_ROUND_COUNT, dest="round_count")
    args = parser.parse_args(argv)
    if args.round_count < 1:
        parser.error("--round must be 1 or greater")
    return args


def append_log(lines: List[str]) -> None:
    RUN_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    prepare_output_dir()
    workspace = reset_demo_workspace()
    registry = seed_registry(workspace)
    ledger = Ledger(workspace / ".prompttree" / "prompttree.db")
    manager, round1_experiment = register_v2_candidates(registry, ledger)
    correctness_cases, benchmark_cases = build_cases()

    round1_results = [
        evaluate_version(registry, ledger, version_id, correctness_cases, benchmark_cases, round_name="round-1")
        for version_id in [version_id(1), version_id(2), version_id(3)]
    ]
    baseline = next(item for item in round1_results if item["version_id"] == BASELINE_VERSION_ID)
    add_benchmark_evaluations(ledger, round1_results, baseline=baseline)
    round1_winner = choose_winner(round1_results)
    manager.complete_experiment(
        round1_experiment.id,
        winner_version_id=round1_winner["version_id"],
        metadata={"round": "round-1"},
    )

    all_results = list(round1_results)
    rounds: List[Dict[str, Any]] = [{"round": "round-1", "results": round1_results, "winner": round1_winner}]
    incumbent_version_id = round1_winner["version_id"]

    for round_number in range(2, args.round_count + 1):
        lineage_context = collect_prompt_hops(
            registry,
            FAMILY_ID,
            incumbent_version_id,
            max_hops=3,
            metrics_by_version=summary_by_version(all_results),
        )
        lineage_path = LINEAGE_CONTEXT_DIR / f"round-{round_number:02d}.json"
        lineage_path.write_text(json.dumps(lineage_context, ensure_ascii=False, indent=2), encoding="utf-8")
        candidate_ids = allocate_version_ids(registry, FAMILY_ID, 2)
        generated_prompts = generate_prompt_variants_with_codex(
            lineage_context,
            round_number=round_number,
            candidate_ids=candidate_ids,
        )
        for variant in generated_prompts:
            record_prompt_generation_run(ledger, variant, incumbent_version_id, f"round-{round_number}")
        experiment = manager.branch(
            family_id=FAMILY_ID,
            from_version=incumbent_version_id,
            mode="three-arm",
            children=generated_prompts,
            assignment_unit="benchmark_suite",
        )
        round_results = [
            evaluate_version(registry, ledger, version_id_value, correctness_cases, benchmark_cases, round_name=f"round-{round_number}")
            for version_id_value in [incumbent_version_id, *candidate_ids]
        ]
        add_benchmark_evaluations(ledger, round_results, baseline=baseline)
        round_winner = choose_winner(round_results)
        manager.complete_experiment(
            experiment.id,
            winner_version_id=round_winner["version_id"],
            metadata={"round": f"round-{round_number}"},
        )
        rounds.append({"round": f"round-{round_number}", "results": round_results, "winner": round_winner})
        all_results.extend(round_results)
        incumbent_version_id = round_winner["version_id"]

    winner = manager.select_and_promote(
        family_id=FAMILY_ID,
        stage="benchmark",
        dataset="sort-benchmark",
        reason="Automatically promoted the prompt with the lowest weighted benchmark cost.",
    )
    if winner is None:
        raise RuntimeError("No eligible winner found for sort example")

    lines = [
        f"Demo workspace: {workspace}",
        "Prompt evolution benchmark for Codex-generated sort implementations",
        "",
    ]
    for round_info in rounds:
        lines.append(round_info["round"])
        for item in sorted(round_info["results"], key=lambda row: (row["failure_count"], row["score"], row["avg_time_ns"])):
            mark = " winner" if item["version_id"] == round_info["winner"]["version_id"] else ""
            lines.append(
                f"- {item['version_id']}: failures={item['failure_count']}, "
                f"score={item['score']:.3f}, avg_time_ms={item['avg_time_ns'] / 1_000_000:.3f}, "
                f"avg_peak_kb={item['avg_peak_bytes'] / 1024:.1f}{mark}"
            )
        lines.append("")
    lines.append(f"Final promoted current version: {winner.version_id}")
    lines.append("")
    lines.append("Scoreboard")
    for summary in ledger.summarize_versions(family_id=FAMILY_ID, score_name="weighted_cost", stage="benchmark"):
        lines.append(
            f"- {summary.version_id}: average_score={summary.average_score}, "
            f"latest_decision={summary.latest_decision}, latest_artifacts={[artifact.uri for artifact in summary.latest_artifacts]}"
        )
    append_log(lines)
    print(RUN_PATH.read_text(encoding="utf-8").strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
