# PromptTree

PromptTree は、テキスト、コード、画像などの生成タスクにまたがって、プロンプトファミリー、出力アーティファクト、外部評価、自動プロモーションを管理するための Python ライブラリです。

English README: [README.md](/Users/hikaru/Desktop/prompttree/README.md)

リポジトリ内で作業するエージェント向けの運用ルールは [AGENTS.md](/Users/hikaru/Desktop/prompttree/AGENTS.md) にあります。変更後に関連する検証を実行し、通るまで修正を継続することが明記されています。

複数のリポジトリで再利用できるように設計されており、主に次の要素を提供します。

- プロンプトファミリーとバージョンのレジストリ
- 生テキストだけでなくアーティファクトハンドルとして保持される出力
- `current`、`best`、派生の `latest` といった名前付き ref
- ブランチ分岐と A/B 実験
- 決定論的な割り当て
- 実行、出力アーティファクト、評価、割り当て、プロンプト ref 改訂、アーティファクト改訂を記録する SQLite ledger
- `best` / `current` の自動更新を行うプロモーションポリシー
- デフォルトの lookback が 3 の repair context
- 各リポジトリが独自のアーティファクトや評価ロジックを定義できる adapter インターフェース

## インストール

```bash
pip install -e .
```

## レイアウト

```text
prompttree/
  pyproject.toml
  src/prompttree/
  examples/prompttree.project.yaml
```

レジストリのレイアウト:

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

## できること

- `Registry`: ファミリー、バージョン、ref、テンプレート、実験定義をディスクから読み込む
- `Template`: バージョン本文と変数からプロンプトテキストをレンダリングする
- `ArtifactHandle`: ファイル、インラインテキスト、画像、URL などの生成物を表現する
- `Ledger`: 実行、出力アーティファクト、評価、割り当て、プロンプト ref 改訂、アーティファクト改訂を SQLite に保存する
- `Experiments`: 分岐したプロンプトバリアントを作成し、実験を完了し、勝者を自動プロモートする
- `History`: 直近の改訂履歴と repair context を返す。デフォルトの件数は 3
- `History.prompt_change_summary(...)`: プロンプトバージョンを親または別 ref と比較し、unified diff とスコア差分を返す
- `Adapter`: アーティファクト読み込み、差分、評価、適用手順を定義するリポジトリ固有の契約

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

## 複数のプロンプト系統を管理する

同じリポジトリ内であっても、無関係なタスクごとに 1 つの `family` を使います。

- `support-reply`、`refund-classifier`、`image-poster` は別ファミリーに分けるべきです。
- 同じタスクのバリエーションは、1 つのファミリー内でバージョンや実験として管理します。
- ledger は複数ファミリーで共有したままで構いません。`family_id`、`stage`、`dataset` によって履歴が分離されます。

## 使用例

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
  コード生成向けの prompt discovery を実行し、`prompt_generation`、`code_generation`、`benchmark` の実行を記録し、最小コストのプロンプトを自動プロモートします。
- `python examples/ab_prompt_hardening/main.py`
  決定論的な A/B の support-reply 実験を実行し、外部 rubric score を ledger に取り込み、自動プロモーションを行います。
- `python examples/qualitative_image_review/main.py`
  ローカル PNG アーティファクト、構造化された人手レビュー、レビュー内容からの prompt generation、自動プロモーションを含む定性的レビューのループを示します。

```bash
python examples/sort/main.py
python examples/ab_prompt_hardening/main.py
python examples/qualitative_image_review/main.py
```
