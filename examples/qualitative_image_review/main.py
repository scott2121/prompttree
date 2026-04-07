from __future__ import annotations

import json
import shutil
import struct
import sys
import tempfile
import zlib
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, List

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from prompttree import ArtifactHandle, ExperimentManager, Ledger, PromotionPolicy, Registry, artifact_from_path, collect_prompt_hops

FAMILY_ID = "image-poster"

PROMPT_V1 = dedent(
    """
    Create a poster-style hero image for a citrus sparkling drink.
    Show one can on a simple background.
    Keep it clean and commercial.
    """
).strip()

PROMPT_V2 = dedent(
    """
    Create a bright poster-style hero image for a citrus sparkling drink.
    Use a vivid yellow-orange palette, strong central subject, and energetic commercial lighting.
    Keep the composition clean and graphic.
    """
).strip()

PROMPT_V3 = dedent(
    """
    Create a premium hero image for a citrus sparkling drink.
    Use a moody dark background, subtle highlights, and a centered can with restrained styling.
    Aim for a polished but understated look.
    """
).strip()


def reset_demo_workspace() -> Path:
    workspace = Path(tempfile.gettempdir()) / "prompttree-qualitative-image-review"
    if workspace.exists():
        shutil.rmtree(workspace)
    (workspace / "generated").mkdir(parents=True, exist_ok=True)
    (workspace / "reviews").mkdir(parents=True, exist_ok=True)
    (workspace / "lineage").mkdir(parents=True, exist_ok=True)
    return workspace


def seed_registry(workspace: Path) -> Registry:
    registry = Registry.load(workspace / "prompting")
    registry.init_layout()
    registry.create_family(
        family_id=FAMILY_ID,
        name="Poster Image Prompt",
        description="Prompt family for qualitative image review loops.",
        current_version="V1",
        artifact_kind="image",
        stage="image_generation",
        promotion_policy=PromotionPolicy(
            score_name="visual_preference",
            direction="higher",
            min_evaluations=1,
            tie_breakers=["preferred_count", "score", "evaluation_count", "version"],
        ),
    )
    registry.write_version(
        FAMILY_ID,
        "V1",
        PROMPT_V1,
        label="baseline poster prompt",
        parent_id=None,
        status="current",
        author="example",
        hypothesis="A generic commercial prompt will produce a usable but bland poster image.",
        tags=["baseline", "image", "qualitative"],
    )
    return registry


def prepare_round1(manager: ExperimentManager) -> object:
    return manager.branch(
        family_id=FAMILY_ID,
        from_version="current",
        mode="three-arm",
        children=[
            {
                "id": "V2",
                "label": "bright poster direction",
                "author": "example",
                "hypothesis": "Brighter palette and stronger subject emphasis should be preferred.",
                "body": PROMPT_V2,
                "tags": ["candidate", "bright"],
            },
            {
                "id": "V3",
                "label": "premium dark direction",
                "author": "example",
                "hypothesis": "A moodier premium style may feel more distinctive.",
                "body": PROMPT_V3,
                "tags": ["candidate", "dark"],
            },
        ],
        assignment_unit="review_batch",
    )


def write_png(path: Path, *, rgb: tuple[int, int, int], width: int = 96, height: int = 96) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    row = b"\x00" + bytes(rgb) * width
    raw = row * height
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, level=9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def record_image_run(
    ledger: Ledger,
    *,
    workspace: Path,
    version_id: str,
    rendered_prompt: str,
    round_name: str,
    color: tuple[int, int, int],
    style: str,
) -> int:
    image_path = workspace / "generated" / f"{round_name}-{version_id}.png"
    write_png(image_path, rgb=color)
    artifact = artifact_from_path(
        image_path,
        kind="image",
        label=image_path.name,
        metadata={"style": style, "round": round_name, "prompt_version_id": version_id},
    )
    run_id, _ = ledger.record_run(
        family_id=FAMILY_ID,
        version_id=version_id,
        run_status="succeeded",
        stage="image_generation",
        dataset="qualitative-demo",
        target_kind="poster_batch",
        target_id=f"{round_name}:{version_id}",
        provider="simulated-image-generator",
        model_name="local-png-writer",
        rendered_prompt=rendered_prompt,
        output_artifacts=[artifact],
        metadata={"style": style, "round": round_name},
    )
    return run_id


def write_review_file(path: Path, entries: List[Dict[str, Any]]) -> None:
    path.write_text(yaml.safe_dump({"entries": entries}, sort_keys=False), encoding="utf-8")


def ingest_review_file(ledger: Ledger, *, path: Path, run_ids_by_version: Dict[str, int]) -> None:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for entry in payload.get("entries", []):
        version_id = str(entry["version_id"])
        ledger.record_evaluation(
            run_id=run_ids_by_version[version_id],
            kind="human_review",
            decision=str(entry["decision"]),
            score_name=str(entry.get("score_name", "visual_preference")),
            score=float(entry["score"]) if entry.get("score") is not None else None,
            metrics={"tags": entry.get("tags", []), "selected_output": entry.get("selected_output", "")},
            notes=str(entry.get("notes", "")),
            evaluator_kind="human",
            provider="structured-review-file",
            reviewer_id=str(entry.get("reviewer_id", "demo-reviewer")),
            metadata={"review_file": str(path)},
        )


def summarize_for_lineage(ledger: Ledger) -> Dict[str, Dict[str, Any]]:
    summaries = ledger.summarize_versions(
        family_id=FAMILY_ID,
        score_name="visual_preference",
        stage="image_generation",
        dataset="qualitative-demo",
    )
    return {
        summary.version_id: {
            "score": summary.average_score,
            "latest_decision": summary.latest_decision,
            "notes": summary.latest_notes,
            "preferred_count": summary.decision_counts.get("preferred", 0),
            "artifact_uris": [artifact.uri for artifact in summary.latest_artifacts],
        }
        for summary in summaries
    }


def generate_prompt_variants_from_reviews(
    registry: Registry,
    ledger: Ledger,
    *,
    incumbent_version_id: str,
    candidate_ids: List[str],
) -> List[Dict[str, str]]:
    lineage = collect_prompt_hops(
        registry,
        FAMILY_ID,
        incumbent_version_id,
        max_hops=3,
        metrics_by_version=summarize_for_lineage(ledger),
    )
    winner = lineage[0]
    notes = " ".join(item["summary"].get("notes", "") for item in lineage if item["summary"].get("notes"))
    guidance = notes.lower()
    bright_focus = "bright, punchy citrus palette and clearer subject silhouette"
    if "generic background" in guidance:
        bright_focus += "; avoid generic empty backgrounds"
    cinematic_focus = "premium poster crop with stronger focal framing and more purposeful contrast"
    if "poster" in guidance:
        cinematic_focus += "; keep the image poster-like rather than photo-journal"
    return [
        {
            "id": candidate_ids[0],
            "label": "bright refined poster",
            "hypothesis": "Doubling down on the preferred bright poster notes should improve human preference.",
            "body": (
                "Create a bold poster image for a citrus sparkling drink. "
                f"Emphasize {bright_focus}. Keep the background graphic, polished, and non-generic."
            ),
        },
        {
            "id": candidate_ids[1],
            "label": "cinematic poster crop",
            "hypothesis": "A clearer focal crop may outperform both the generic and dark variants.",
            "body": (
                "Create a premium advertising poster for a citrus sparkling drink. "
                f"Use {cinematic_focus}. Keep one hero can as the clear focal point."
            ),
        },
    ]


def record_prompt_generation_runs(ledger: Ledger, variants: List[Dict[str, str]], *, round_name: str, parent_version_id: str) -> None:
    for variant in variants:
        ledger.record_run(
            family_id=FAMILY_ID,
            version_id=variant["id"],
            run_status="succeeded",
            stage="prompt_generation",
            dataset="qualitative-demo",
            target_kind="prompt_variant",
            target_id=f"{round_name}:{variant['id']}",
            provider="review-driven-generator",
            model_name="deterministic",
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


def print_scoreboard(registry: Registry, ledger: Ledger) -> None:
    versions_by_id = {version.id: version for version in registry.list_versions(FAMILY_ID)}
    summaries = ledger.summarize_versions(
        family_id=FAMILY_ID,
        score_name="visual_preference",
        stage="image_generation",
        dataset="qualitative-demo",
    )
    ordered = sorted(
        summaries,
        key=lambda item: ((item.average_score or 0.0), item.decision_counts.get("preferred", 0), item.version_id),
        reverse=True,
    )
    print("Scoreboard")
    for summary in ordered:
        label = versions_by_id.get(summary.version_id).label if summary.version_id in versions_by_id else summary.version_id
        print(
            f"- {summary.version_id} ({label}): average_score={summary.average_score}, "
            f"latest_decision={summary.latest_decision}, preferred_count={summary.decision_counts.get('preferred', 0)}, "
            f"notes={summary.latest_notes}"
        )


def main() -> int:
    workspace = reset_demo_workspace()
    registry = seed_registry(workspace)
    ledger = Ledger(workspace / ".prompttree" / "prompttree.db")
    manager = ExperimentManager(registry=registry, ledger=ledger)

    round1_experiment = prepare_round1(manager)
    round1_runs = {
        "V1": record_image_run(
            ledger,
            workspace=workspace,
            version_id="V1",
            rendered_prompt=registry.resolve_version(FAMILY_ID, "V1").body,
            round_name="round-1",
            color=(218, 214, 196),
            style="neutral studio packshot",
        ),
        "V2": record_image_run(
            ledger,
            workspace=workspace,
            version_id="V2",
            rendered_prompt=registry.resolve_version(FAMILY_ID, "V2").body,
            round_name="round-1",
            color=(248, 197, 48),
            style="bright poster composition",
        ),
        "V3": record_image_run(
            ledger,
            workspace=workspace,
            version_id="V3",
            rendered_prompt=registry.resolve_version(FAMILY_ID, "V3").body,
            round_name="round-1",
            color=(54, 57, 79),
            style="dark premium mood",
        ),
    }

    round1_review_path = workspace / "reviews" / "round-1.yaml"
    write_review_file(
        round1_review_path,
        [
            {
                "version_id": "V1",
                "decision": "rejected",
                "score": 2.8,
                "notes": "safe but too generic background and weak product presence",
                "tags": ["generic", "weak-subject"],
                "selected_output": "round-1-V1.png",
            },
            {
                "version_id": "V2",
                "decision": "preferred",
                "score": 4.8,
                "notes": "liked bright composition, clearer subject, and style closer to poster",
                "tags": ["bright", "clear-subject", "poster"],
                "selected_output": "round-1-V2.png",
            },
            {
                "version_id": "V3",
                "decision": "rejected",
                "score": 3.4,
                "notes": "interesting mood but the dark treatment hides the product too much",
                "tags": ["dark", "hidden-subject"],
                "selected_output": "round-1-V3.png",
            },
        ],
    )
    ingest_review_file(ledger, path=round1_review_path, run_ids_by_version=round1_runs)
    round1_winner = manager.select_and_promote(
        family_id=FAMILY_ID,
        stage="image_generation",
        dataset="qualitative-demo",
        reason="Round 1 qualitative winner promoted as incumbent before further exploration.",
    )
    if round1_winner is None:
        raise RuntimeError("Round 1 did not produce an eligible winner")

    lineage_context = collect_prompt_hops(
        registry,
        FAMILY_ID,
        round1_winner.version_id,
        max_hops=3,
        metrics_by_version=summarize_for_lineage(ledger),
    )
    (workspace / "lineage" / "round-2.json").write_text(json.dumps(lineage_context, ensure_ascii=False, indent=2), encoding="utf-8")
    new_ids = ["V4", "V5"]
    generated_prompts = generate_prompt_variants_from_reviews(
        registry,
        ledger,
        incumbent_version_id=round1_winner.version_id,
        candidate_ids=new_ids,
    )
    record_prompt_generation_runs(ledger, generated_prompts, round_name="round-2", parent_version_id=round1_winner.version_id)
    round2_experiment = manager.branch(
        family_id=FAMILY_ID,
        from_version=round1_winner.version_id,
        mode="three-arm",
        children=generated_prompts,
        assignment_unit="review_batch",
    )

    round2_runs = {
        round1_winner.version_id: record_image_run(
            ledger,
            workspace=workspace,
            version_id=round1_winner.version_id,
            rendered_prompt=registry.resolve_version(FAMILY_ID, round1_winner.version_id).body,
            round_name="round-2",
            color=(248, 197, 48),
            style="bright poster composition",
        ),
        "V4": record_image_run(
            ledger,
            workspace=workspace,
            version_id="V4",
            rendered_prompt=registry.resolve_version(FAMILY_ID, "V4").body,
            round_name="round-2",
            color=(255, 166, 32),
            style="refined bright poster with stronger subject",
        ),
        "V5": record_image_run(
            ledger,
            workspace=workspace,
            version_id="V5",
            rendered_prompt=registry.resolve_version(FAMILY_ID, "V5").body,
            round_name="round-2",
            color=(137, 90, 58),
            style="cinematic crop with warmer contrast",
        ),
    }

    round2_review_path = workspace / "reviews" / "round-2.yaml"
    write_review_file(
        round2_review_path,
        [
            {
                "version_id": round1_winner.version_id,
                "decision": "approved",
                "score": 4.6,
                "notes": "still strong, but the composition could feel a bit more intentional",
                "tags": ["bright", "good-baseline"],
                "selected_output": f"round-2-{round1_winner.version_id}.png",
            },
            {
                "version_id": "V4",
                "decision": "preferred",
                "score": 5.0,
                "notes": "best result: bright composition, subject is clearest, and background no longer feels generic",
                "tags": ["preferred", "clear-subject", "non-generic"],
                "selected_output": "round-2-V4.png",
            },
            {
                "version_id": "V5",
                "decision": "approved",
                "score": 4.1,
                "notes": "interesting crop, but slightly less immediately commercial than V4",
                "tags": ["cinematic", "commercial"],
                "selected_output": "round-2-V5.png",
            },
        ],
    )
    ingest_review_file(ledger, path=round2_review_path, run_ids_by_version=round2_runs)
    final_winner = manager.select_and_promote(
        family_id=FAMILY_ID,
        stage="image_generation",
        dataset="qualitative-demo",
        reason="Automatically promoted the most preferred qualitative image prompt.",
    )
    if final_winner is None:
        raise RuntimeError("Round 2 did not produce an eligible winner")

    print(f"Demo workspace: {workspace}")
    print()
    print_scoreboard(registry, ledger)
    print()
    print(f"Final promoted current version: {registry.get_family(FAMILY_ID).current_version}")
    print()
    print("Round 2 lineage context")
    print((workspace / "lineage" / "round-2.json").read_text(encoding="utf-8").strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
