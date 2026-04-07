# Sort Prompt Evolution Example

This example treats the prompt itself as the thing being optimized for Codex.

The script:

- runs an initial multi-arm test between `V1`, `V2`, and `V3`
- collects up to 3 hops of prompt lineage plus scores from the winning branch
- uses `codex exec` to propose two new prompt variants each round (`V4`, `V5`, ...)
- uses `codex exec` again to generate the Python sort implementation for each prompt version
- writes each generated implementation to `examples/sort/output/generated/`
- benchmarks correctness, runtime, and peak memory several times
- records every run and evaluation in the PromptTree ledger
- promotes the winning prompt version to `current`
- writes `examples/sort/output/prompt-tree.svg` with the compact family tree and per-version score
- writes `examples/sort/output/prompt-improvement.svg` with prompt-change summaries and prompt focus by version
- writes `examples/sort/output/score-summary.svg` with benchmark results only

Run it from the repository root:

```bash
python examples/sort/main.py
```

The SVG outputs are configurable from the command line. Common options:

- `--score-rows latest-per-version|all-results`
- `--score-columns rank,version,label,round,global_score,round_score,time_ms,peak_kb,status`
- `--score-sort failures,global_score,time_ms,peak_kb,version`
- `--tree-fields score,time_ms,peak_kb,prompt_changes` or `--tree-fields none`
- `--improvement-sections winner,latest_result,parent,changes,focus` or `--improvement-sections none`

Example:

```bash
python examples/sort/main.py \
  --score-columns rank,version,label,round,global_score,round_score,time_ms,peak_kb,status \
  --tree-fields score,time_ms,peak_kb,prompt_changes \
  --tree-max-prompt-changes 1 \
  --improvement-sections winner,latest_result,parent,changes,focus
```

The whole flow is self-contained in `main.py`. Before each run, previously generated Python files are deleted from `examples/sort/output/generated/`. This example now expects a working `codex` CLI login because both prompt evolution and code generation are executed through `codex exec`.
