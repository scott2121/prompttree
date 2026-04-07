from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from statistics import mean
from textwrap import dedent

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from prompttree import ArtifactHandle, ExperimentManager, Ledger, PromotionPolicy, Registry


BASE_PROMPT = dedent(
    """
    You are a customer support agent.
    Reply to the customer using a calm and helpful tone.
    Keep the answer short and resolve the issue if you can.

    Customer name: {{customer_name}}
    Issue: {{issue}}
    Policy: {{policy}}
    """
).strip()

PROMPT_V2A = dedent(
    """
    You are a customer support agent.
    Write a reply that sounds calm, confident, and practical.
    Mention the policy in plain language.
    End with one concrete next step the customer can take.
    Keep the answer under 80 words.

    Customer name: {{customer_name}}
    Issue: {{issue}}
    Policy: {{policy}}
    """
).strip()

PROMPT_V2B = dedent(
    """
    You are a customer support agent.
    Reply in exactly three short parts:
    1. Acknowledge the problem with empathy.
    2. Quote the exact policy sentence that applies.
    3. Give the next step.
    If key information is missing, ask exactly one clarifying question before promising a final result.
    Keep the answer under 80 words and avoid filler.

    Customer name: {{customer_name}}
    Issue: {{issue}}
    Policy: {{policy}}
    """
).strip()

SCENARIOS = [
    {
        "slug": "refund",
        "issue": "My blender stopped working after 12 days and I want my money back.",
        "policy": "Refunds are available within 30 days of delivery.",
        "policy_terms": ["30 days", "refunds"],
        "next_step": "Reply with your order number and I can start a refund or replacement today.",
        "next_terms": ["order number", "refund", "replacement"],
        "needs_question": False,
        "question": "Would you prefer a refund or a replacement?",
    },
    {
        "slug": "damaged",
        "issue": "The lamp arrived cracked. The box was damaged too.",
        "policy": "Damaged items can be replaced once we confirm the shipping damage.",
        "policy_terms": ["damaged items", "replaced"],
        "next_step": "Please send one photo of the damage and I will arrange a replacement.",
        "next_terms": ["photo", "replacement"],
        "needs_question": False,
        "question": "Could you send one photo of the damaged item?",
    },
    {
        "slug": "address_change",
        "issue": "I placed an order this morning and need to change the shipping address.",
        "policy": "We can update the shipping address before the warehouse marks the order as packed.",
        "policy_terms": ["shipping address", "packed"],
        "next_step": "Send the updated address and I will check whether the order is still editable.",
        "next_terms": ["updated address", "editable"],
        "needs_question": True,
        "question": "What is the updated shipping address you want us to use?",
    },
    {
        "slug": "invoice",
        "issue": "Can you send me a VAT invoice for order 1842?",
        "policy": "VAT invoices are issued after payment is confirmed.",
        "policy_terms": ["vat invoices", "payment is confirmed"],
        "next_step": "I can send the invoice PDF as soon as the payment status is confirmed.",
        "next_terms": ["invoice pdf", "payment status"],
        "needs_question": False,
        "question": "Could you confirm the billing email address?",
    },
    {
        "slug": "late_delivery",
        "issue": "My package was supposed to arrive yesterday and there is no update.",
        "policy": "Standard shipping takes 3 to 5 business days, and delays can happen during carrier scans.",
        "policy_terms": ["3 to 5 business days", "carrier scans"],
        "next_step": "Share your order number and I will check the latest tracking scan for you.",
        "next_terms": ["order number", "tracking scan"],
        "needs_question": True,
        "question": "What is the order number for the delayed package?",
    },
    {
        "slug": "subscription",
        "issue": "Please cancel my monthly plan before the next renewal.",
        "policy": "Subscriptions can be canceled any time before the next billing date.",
        "policy_terms": ["canceled any time", "billing date"],
        "next_step": "I can cancel it now and confirm the end date of your access.",
        "next_terms": ["cancel", "end date"],
        "needs_question": False,
        "question": "Do you want the subscription to end immediately?",
    },
]


def build_tickets() -> list[dict[str, object]]:
    names = [
        "Avery", "Kai", "Mika", "Ren", "Sora", "Emi", "Noa", "Yui",
        "Haru", "Rin", "Mei", "Tao", "Niko", "Lena", "Theo", "Luca",
        "Mina", "Jules", "Ari", "Ivy", "Milo", "Nina", "Owen", "Sara",
    ]
    tickets: list[dict[str, object]] = []
    for index, (name, scenario) in enumerate(zip(names, SCENARIOS * 4), start=1):
        tickets.append(
            {
                "customer_id": f"cust-{index:02d}",
                "customer_name": name,
                **scenario,
            }
        )
    return tickets


def reset_demo_workspace() -> Path:
    workspace = Path(tempfile.gettempdir()) / "prompttree-ab-prompt-hardening"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def seed_registry(workspace: Path) -> Registry:
    registry = Registry.load(workspace / "prompting")
    registry.init_layout()
    registry.create_family(
        family_id="support-reply",
        name="Support Reply",
        description="Prompt family for support email replies.",
        current_version="support-reply-v1",
        artifact_kind="support_reply",
        stage="reply_generation",
        promotion_policy=PromotionPolicy(
            score_name="rubric_score",
            direction="higher",
            min_evaluations=1,
            tie_breakers=["score", "evaluation_count", "version"],
        ),
    )
    registry.write_version(
        "support-reply",
        "support-reply-v1",
        BASE_PROMPT,
        label="baseline",
        parent_id=None,
        status="current",
        author="example",
        hypothesis="Baseline prompt without explicit policy or clarification rules.",
        tags=["baseline"],
    )
    return registry


def prepare_experiment(registry: Registry, ledger: Ledger) -> tuple[ExperimentManager, object]:
    manager = ExperimentManager(registry=registry, ledger=ledger)
    experiment = manager.branch(
        family_id="support-reply",
        from_version="current",
        mode="three-arm",
        children=[
            {
                "id": "support-reply-v2a",
                "label": "policy + next step",
                "author": "example",
                "hypothesis": "Adding explicit policy mention should improve consistency.",
                "body": PROMPT_V2A,
                "tags": ["ab-test", "policy"],
            },
            {
                "id": "support-reply-v2b",
                "label": "policy + next step + clarifying question",
                "author": "example",
                "hypothesis": "A three-part structure with a required clarification step should improve pass rate.",
                "body": PROMPT_V2B,
                "tags": ["ab-test", "policy", "clarification"],
            },
        ],
        assignment_unit="customer",
    )
    return manager, experiment


def simulate_model_output(rendered_prompt: str, ticket: dict[str, object]) -> str:
    prompt = rendered_prompt.lower()
    uses_plain_policy = "mention the policy in plain language" in prompt
    uses_exact_policy = "quote the exact policy sentence" in prompt
    uses_clarifying_question = "ask exactly one clarifying question" in prompt

    parts = []
    if uses_plain_policy or uses_exact_policy:
        parts.append(f"Sorry about that, {ticket['customer_name']}.")
    else:
        parts.append(f"Hi {ticket['customer_name']}, I can help with this.")

    if uses_exact_policy:
        parts.append(str(ticket["policy"]))
    elif uses_plain_policy:
        parts.append(f"In short: {ticket['policy']}")

    if uses_clarifying_question and bool(ticket["needs_question"]):
        parts.append(str(ticket["question"]))

    parts.append(str(ticket["next_step"]))
    if not (uses_plain_policy or uses_exact_policy):
        parts = [parts[0], str(ticket["next_step"])]
    return " ".join(parts).replace("  ", " ").strip()


def evaluate_reply(reply: str, ticket: dict[str, object]) -> tuple[str, float, dict[str, object]]:
    lower = reply.lower()
    checks = {
        "empathy": "sorry" in lower,
        "policy": all(term in lower for term in ticket["policy_terms"]),
        "next_step": all(term in lower for term in ticket["next_terms"]),
        "clarifying_question": (not bool(ticket["needs_question"])) or ("?" in reply),
        "concise": len(reply.split()) <= 80,
    }
    score = round(sum(1 for passed in checks.values() if passed) / len(checks), 2)
    decision = "approved" if checks["policy"] and checks["next_step"] and checks["clarifying_question"] else "rejected"
    failed_checks = [name for name, passed in checks.items() if not passed]
    return decision, score, {"checks": checks, "notes": ", ".join(failed_checks)}


def run_demo(manager: ExperimentManager, registry: Registry, ledger: Ledger) -> None:
    for ticket in build_tickets():
        assignment = manager.assign("support-reply", str(ticket["customer_id"]))
        version = registry.resolve_version("support-reply", assignment.version_id)
        rendered_prompt = version.render(
            customer_name=ticket["customer_name"],
            issue=ticket["issue"],
            policy=ticket["policy"],
        )
        reply = simulate_model_output(rendered_prompt, ticket)
        decision, score, result = evaluate_reply(reply, ticket)
        ledger.record_run(
            family_id="support-reply",
            version_id=version.id,
            run_status="succeeded",
            stage="reply_generation",
            dataset="support-demo",
            target_kind="customer_ticket",
            target_id=str(ticket["customer_id"]),
            provider="demo",
            model_name="simulated-support-model",
            input_snapshot=ticket,
            rendered_prompt=rendered_prompt,
            latency_ms=140 + len(reply),
            output_artifacts=[
                ArtifactHandle(
                    kind="text",
                    uri=f"inline://support-reply/{ticket['customer_id']}",
                    mime_type="text/plain",
                    label=f"reply-{ticket['customer_id']}",
                    metadata={"text": reply},
                )
            ],
            evaluation={
                "kind": "rubric",
                "decision": decision,
                "score_name": "rubric_score",
                "score": score,
                "metrics": result["checks"],
                "notes": result["notes"],
                "evaluator_kind": "deterministic",
                "provider": "example",
                "metadata": {"arm_id": assignment.arm_id, "customer_id": ticket["customer_id"]},
            },
        )


def print_summary(workspace: Path, experiment_id: str, registry: Registry, ledger: Ledger) -> None:
    versions_by_id = {version.id: version for version in registry.list_versions("support-reply")}
    summaries = ledger.summarize_versions(family_id="support-reply", score_name="rubric_score", stage="reply_generation")
    ordered = sorted(
        summaries,
        key=lambda item: ((item.average_score or 0.0), item.evaluation_count, item.version_id),
        reverse=True,
    )

    print(f"Demo workspace: {workspace}")
    print(f"Experiment: {experiment_id}")
    print()
    print("Scoreboard")
    for summary in ordered:
        label = versions_by_id.get(summary.version_id).label if summary.version_id in versions_by_id else summary.version_id
        print(
            f"- {summary.version_id} ({label}): "
            f"evaluations={summary.evaluation_count}, average_score={summary.average_score:.2f}, "
            f"latest_decision={summary.latest_decision}, decisions={summary.decision_counts}"
        )

    family = registry.get_family("support-reply")
    print()
    print(f"Promoted current version: {family.current_version}")
    print()
    print("Family manifest")
    manifest = (workspace / "prompting" / "families" / "support-reply" / "family.yaml").read_text(encoding="utf-8")
    print(manifest.strip())
    print()
    print("Sample evaluation rows")
    sample = ledger.query(
        """
        SELECT r.run_id, r.version_id, e.decision, e.score_name, e.score, e.notes, e.metrics
        FROM prompt_runs r
        JOIN evaluations e ON e.run_id = r.run_id
        ORDER BY r.run_id
        LIMIT 3
        """
    )
    for row in sample:
        print(
            json.dumps(
                {
                    "run_id": row["run_id"],
                    "version_id": row["version_id"],
                    "decision": row["decision"],
                    "score_name": row["score_name"],
                    "score": row["score"],
                    "notes": row["notes"],
                    "metrics": json.loads(row["metrics"]),
                },
                ensure_ascii=False,
            )
        )


def main() -> int:
    workspace = reset_demo_workspace()
    registry = seed_registry(workspace)
    ledger = Ledger(workspace / ".prompttree" / "prompttree.db")
    manager, experiment = prepare_experiment(registry, ledger)
    run_demo(manager, registry, ledger)
    winner = manager.select_and_promote(
        family_id="support-reply",
        stage="reply_generation",
        dataset="support-demo",
        reason="Automatically promoted the highest-scoring support reply prompt.",
    )
    if winner is None:
        raise RuntimeError("No eligible winner found for support-reply")
    print_summary(workspace, experiment.id, registry, ledger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
