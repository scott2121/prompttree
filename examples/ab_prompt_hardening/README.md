# A/B Prompt Hardening Example

This example shows how to use PromptTree to improve a prompt with A/B testing:

1. Create a baseline prompt family.
2. Branch two candidate prompt versions from `current`.
3. Assign traffic deterministically across control and treatment arms.
4. Record runs and rubric evaluations in the SQLite ledger.
5. Promote the winning prompt version to `current`.

Run it from the repository root:

```bash
python examples/ab_prompt_hardening/main.py
```

What the example includes:

- `main.py`: end-to-end demo runner
- a temporary PromptTree workspace under your system temp directory
- a deterministic fake model, so the example runs without external APIs
- pass-rate and score summaries per arm
- a final promotion step that updates `family.yaml`

To adapt this for a real workflow, replace `simulate_model_output` with your LLM call and keep the assignment, run logging, evaluation logging, and version promotion flow unchanged.
