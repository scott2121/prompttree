# AGENTS.md

## Purpose

This file defines the minimum operating rules for agents working in this repository.

## Core Rule

When you make any change, do not stop at the edit itself. Run the relevant verification for the area you changed, and if it fails, keep fixing the code and rerunning the verification until the test or check passes.

Do not end with "implemented but not tested" if a local verification path exists.

## Completion Priority

Do not optimize for ending quickly. Optimize for reaching a correct, verified outcome with the smallest sufficient change.

Do not stop because the first edit looks plausible. Stop when the requested work is actually complete and the relevant checks pass.

## Execution Boundary

If the user has clearly requested a specific change, proceed with the fix, run the relevant checks, and continue until the requested state is achieved.

Do not pause just to restate intent or wait for confirmation that is already implied by the user's instruction.

Pause and ask only when there is a special choice to make, such as:

- adding a new feature the user did not explicitly request
- choosing between multiple materially different implementations
- making a destructive, risky, or difficult-to-reverse change
- proceeding without information that would significantly affect the outcome

## Required Work Loop

1. Read the files you are about to change and understand the local behavior.
2. Make the smallest change that can solve the problem.
3. Run the most relevant local verification commands.
4. If a check fails, fix the issue and rerun.
5. Repeat until the relevant checks pass or you are blocked by an external dependency that cannot be resolved from this repository.
6. In your final report, state exactly which commands you ran and whether they passed.

## Verification Policy For This Repo

Use the smallest command set that proves the change, but prefer real execution over assumption.

- For general Python edits, run:
  - `python -m compileall src examples`
- For CLI or package entrypoint edits, run:
  - `python -m prompttree --help`
- For changes in the sort example or shared code it depends on, run:
  - `python examples/sort/main.py`
- For changes in the A/B hardening example or shared code it depends on, run:
  - `python examples/ab_prompt_hardening/main.py`
- For changes in core registry, ledger, experiments, history, evolution, or visualization code, run:
  - `python -m compileall src examples`
  - `python examples/sort/main.py`
  - `python examples/ab_prompt_hardening/main.py`

## Quality Bar

- Do not claim success while relevant checks are still failing.
- Do not skip reruns after a fix.
- Prefer fixing the root cause over patching symptoms.
- If no automated test exists for the touched area, run the closest executable validation path and say that explicitly.

## Scope Discipline

- Avoid unrelated refactors.
- Do not revert user changes outside your task.
- Keep edits consistent with the existing style of the repository.
