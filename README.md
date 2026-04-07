# PromptTree

PromptTree is a Python library for managing prompt families, output artifacts, external evaluations, and automatic promotion across text, code, image, and other generation tasks.

Japanese README: [README.ja.md](/Users/hikaru/Desktop/prompttree/README.ja.md)

Agent workflow guidance for repository-local changes lives in [AGENTS.md](/Users/hikaru/Desktop/prompttree/AGENTS.md). It explicitly requires agents to run relevant verification after every change and continue fixing issues until those checks pass.

It is designed to be reusable across repositories:

- registry for prompt families and versions
- prompt outputs stored as artifact handles instead of raw text only
- named refs such as `current`, `best`, and derived `latest`
- branching and A/B experiments
- deterministic assignment
- SQLite ledger for runs, output artifacts, evaluations, assignments, prompt ref revisions, and artifact revisions
- promotion policies for automatic `best` / `current` updates
- repair context with a default lookback of 3
- adapter interface so each repository can define its own artifacts and evaluation logic

## Install

```bash
pip install -e .
```

## Layout

```text
prompttree/
  pyproject.toml
  src/prompttree/
  examples/prompttree.project.yaml
```

Registry layout:

```text
prompting/
  families/
    variable-line/
      family.yaml
      versions/
        variable-line-v1.md
        variable-line-v2.md
  experiments/
    exp-variable-line-v2a-v2b.yaml
```

## What It Does

- `Registry`: load families, versions, refs, templates, and experiments from disk
- `Template`: render prompt text from a version body and variables
- `ArtifactHandle`: represent generated outputs such as files, inline text, images, or URLs
- `Ledger`: store runs, output artifacts, evaluations, assignments, prompt ref revisions, and artifact revisions in SQLite
- `Experiments`: create branched prompt variants, complete experiments, and auto-promote winners
- `History`: return recent revisions and repair context, with default limits of 3
- `History.prompt_change_summary(...)`: compare a prompt version to its parent or another ref, including unified diff plus score deltas
- `Adapter`: repository-specific contract for artifact loading, diffing, evaluation, and apply steps

## CLI

```bash
prompttree init --root .
prompttree family list --root .
prompttree version show --root . variable-line@current
prompttree version show --root . variable-line@latest
prompttree version diff --root . --db .prompttree/prompttree.db --score-name rubric_score \
  --stage generation --dataset uniprot variable-line@variable-line-v2
prompttree ref list --root . --family variable-line
prompttree ref set --root . --db .prompttree/prompttree.db --family variable-line --name best --version variable-line-v4
prompttree experiment branch-and-start --root . --family variable-line --from current --mode three-arm \
  --child-id variable-line-v4a --child-label "contrast-heavy wording" \
  --child-id variable-line-v4b --child-label "example-anchored wording"
prompttree experiment show --root . --family variable-line
prompttree scoreboard --root . --db .prompttree/prompttree.db --family variable-line --score-name rubric_score
prompttree promote auto --root . --db .prompttree/prompttree.db --family variable-line
prompttree repair-context --db .prompttree/prompttree.db --kind variable_doc_line --dataset uniprot --key gene_label
```

## Managing Multiple Prompt Tracks

Use one prompt `family` per unrelated task, even when everything lives in the same repository.

- `support-reply`, `refund-classifier`, and `image-poster` should be separate families.
- Variants of the same task should stay in one family as versions and experiments.
- The ledger can stay shared across families; `family_id`, `stage`, and `dataset` keep the histories separate.

## Example Usage

```python
from pathlib import Path

from prompttree import ArtifactHandle, ExperimentManager, Ledger, PromotionPolicy, Registry

root = Path(".")
registry = Registry.load(root / "prompting")
ledger = Ledger(root / ".prompttree" / "prompttree.db")

registry.init_layout()
registry.create_family(
    family_id="variable-line",
    name="Variable Line",
    description="Prompt family for generated variable descriptions.",
    current_version="variable-line-v1",
    artifact_kind="text",
    stage="generation",
    promotion_policy=PromotionPolicy(score_name="rubric_score", direction="higher"),
)
registry.write_version(
    "variable-line",
    "variable-line-v1",
    "Write one clear description for {{variable_name}}.",
    label="baseline",
    parent_id=None,
    status="current",
    author="example",
    hypothesis="Baseline wording.",
)

version = registry.resolve_version("variable-line", "current")
rendered_prompt = version.render(variable_name="gene_label")

run_id, evaluation_id = ledger.record_run(
    family_id="variable-line",
    version_id=version.id,
    run_status="succeeded",
    stage="generation",
    dataset="uniprot",
    target_kind="variable_doc_line",
    target_id="uniprot:gene_label",
    provider="openai",
    model_name="gpt-5.4",
    input_snapshot={"variable_name": "gene_label"},
    rendered_prompt=rendered_prompt,
    output_artifacts=[
        ArtifactHandle(
            kind="text",
            uri="inline://variable-line/gene_label",
            mime_type="text/plain",
            label="gene_label.txt",
            metadata={"text": "Gene label used in the UniProt export."},
        )
    ],
    evaluation={
        "kind": "rubric",
        "decision": "approved",
        "metrics": {"score": 0.92},
        "evaluator_kind": "external",
        "provider": "user-code",
        "score_name": "rubric_score",
        "score": 0.92,
    },
)

manager = ExperimentManager(registry=registry, ledger=ledger)
winner = manager.select_and_promote(
    family_id="variable-line",
    stage="generation",
    dataset="uniprot",
)
print(winner.version_id if winner else "no winner")
```

## Examples

- `python examples/sort/main.py`
  End-to-end prompt evolution for code generation.
  Runs prompt discovery for code generation, records `prompt_generation`, `code_generation`, and `benchmark` runs, and auto-promotes the lowest-cost prompt.
  This is the best example if you want to see version branching, generated artifacts, benchmark-driven evaluation, and visualization output working together.
- `python examples/ab_prompt_hardening/main.py`
  Deterministic A/B testing for a text-generation workflow.
  Runs a deterministic A/B support-reply experiment where external rubric scores are ingested into the ledger and promotion happens automatically.
  This is the clearest example for teams that already have an evaluator or human-review rubric and want PromptTree to handle assignment, run logging, and winner promotion.
- `python examples/qualitative_image_review/main.py`
  Human-in-the-loop review for image-style prompt iteration.
  Demonstrates a qualitative review loop with simulated local PNG artifacts, structured human review files, prompt generation from review notes, and auto-promotion.
  Use this example as the reference shape for multimodal workflows where the main signal comes from reviewer feedback rather than a numeric benchmark.

```bash
python examples/sort/main.py
python examples/ab_prompt_hardening/main.py
python examples/qualitative_image_review/main.py
```

## Visualized Example Output

The sort example writes visual artifacts that make prompt evolution easier to inspect without opening the SQLite ledger directly.

- [`examples/sort/output/prompt-tree.svg`](examples/sort/output/prompt-tree.svg)
  Version lineage graph for the sort prompt family.
- [`examples/sort/output/score-summary.svg`](examples/sort/output/score-summary.svg)
  Compact score and benchmark summary by version.
- [`examples/sort/output/prompt-improvement.svg`](examples/sort/output/prompt-improvement.svg)
  A prompt-to-prompt comparison view showing how later candidates changed.
- [`examples/sort/output/run.txt`](examples/sort/output/run.txt)
  Plain-text run summary with promoted winner and benchmark results.
- [`examples/sort/output/lineage-context.json`](examples/sort/output/lineage-context.json)
  Machine-readable lineage context that can be fed back into future prompt generation steps.

Prompt tree preview:

![Prompt tree example](examples/sort/output/prompt-tree.svg)

Score summary preview:

![Score summary example](examples/sort/output/score-summary.svg)

Prompt improvement preview:

![Prompt improvement example](examples/sort/output/prompt-improvement.svg)
