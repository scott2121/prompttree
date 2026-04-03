# Prompt Versioning Library Design

## 背景

このリポジトリでは、`variables_info.txt` の説明文や `sparql.yaml` の description がパイプライン実行中に更新される。
単純に GitHub 上の diff だけで追うと、次の情報を横断して見るのが難しい。

- どの prompt family/version が使われたか
- どの入力コンテキストで生成されたか
- 生成結果が検証で通ったか
- 何が reason で修正されたか
- 最終的に `variables_info.txt` のどの行が何から何に変わったか

さらに現状は、prompt の管理レイヤーと実行レイヤーが分かれている。

- `monitoring/prompt-registry.json` と `monitoring/prompts/*.md` には prompt 系の履歴がある
- 実際のパイプライン実行では `scripts/incremental_variable_docs.rb` に heredoc の prompt が埋め込まれている

つまり、現状の `prompt-registry` は「閲覧・運用メタデータ」であって、「実行時の source of truth」ではない。

## 結論

設計できる。  
ただし「prompt のバージョン管理ライブラリ」として作るより、以下をまとめて扱う **prompt lineage library** として設計した方がよい。

- prompt versioning
- prompt rendering
- run logging
- evaluation logging
- artifact revision logging

この最後の artifact revision logging がないと、知りたい「説明文の更新履歴」が取れない。

## 設計原則

1. Prompt は immutable にする
2. 実行ログは append-only にする
3. 出力ファイルの更新は artifact revision として記録する
4. 「prompt version」と「artifact revision」を別概念にする
5. Git は保管場所の一つとして使うが、履歴参照は library の API/CLI で行う

## 追いたいエンティティ

### 1. PromptFamily

同じ用途の prompt 群。

例:

- `variable-line`
- `query-description`
- `infer-variables`
- `repair-variable-description`
- `repair-query-description`

### 2. PromptVersion

1つの family に属する immutable な version。

持つべき属性:

- `id`
- `family_id`
- `label`
- `parent_id`
- `status`
- `created_at`
- `author`
- `hypothesis`
- `template_path`
- `input_schema`
- `output_schema`
- `tags`

### 3. PromptRun

ある prompt version を 1 回実行した記録。

持つべき属性:

- `run_id`
- `family_id`
- `version_id`
- `stage`
- `dataset`
- `target_kind`
- `target_id`
- `model_backend`
- `model_name`
- `started_at`
- `finished_at`
- `input_snapshot`
- `rendered_prompt`
- `raw_output`
- `normalized_output`
- `token_usage`
- `latency_ms`
- `status`

### 4. EvaluationResult

生成結果に対する検証。

例:

- round-trip 成功/失敗
- templated 率
- raw token 混入
- description quality
- reviewer note

持つべき属性:

- `evaluation_id`
- `run_id`
- `kind`
- `status`
- `metrics`
- `reason`
- `details`
- `created_at`

### 5. PromptExperiment

A/B テストや多腕比較の定義。

持つべき属性:

- `experiment_id`
- `family_id`
- `name`
- `status`
- `assignment_unit`
- `assignment_strategy`
- `traffic_split`
- `target_filter`
- `primary_metrics`
- `secondary_metrics`
- `started_at`
- `ended_at`

`assignment_unit` の例:

- `dataset`
- `dataset_variable`
- `dataset_query`
- `run`

この用途では `dataset_variable` か `dataset_query` が重要。

### 6. PromptAssignment

どの対象がどの arm に入ったかの記録。  
A/B テストではここがないと再現できない。

持つべき属性:

- `assignment_id`
- `experiment_id`
- `unit_key`
- `arm_id`
- `version_id`
- `assigned_at`
- `assignment_hash`
- `sticky`

例:

- `unit_key = "uniprot:gene_label"`
- `arm_id = "treatment"`
- `version_id = "variable-line-v4"`

### 7. ArtifactRevision

これが本丸。`variables_info.txt` の各行や `sparql.yaml` の各 entry の改訂履歴。

持つべき属性:

- `artifact_id`
- `artifact_kind`
- `dataset`
- `location`
- `logical_key`
- `revision_id`
- `parent_revision_id`
- `before_value`
- `after_value`
- `applied_by_run_id`
- `applied_at`
- `apply_reason`

例:

- artifact_kind: `variable_doc_line`
- dataset: `uniprot`
- logical_key: `gene_label`
- location: `rdf-config/config/uniprot/variables_info.txt`

## 重要な見方

この設計では、質問に対して次の形で答えられるようにする。

- `gene_label` の説明文はいつ変わったか
- その変更はどの prompt version で起きたか
- 変更前後の文面は何か
- その変更は round-trip validation を通ったか
- 同じ family の他 version と比べて成績はどうか
- A/B テストで control と treatment のどちらに割り当てられていたか

これが Git diff だけでは見づらい部分。

## 推奨ストレージ構成

### Git 管理するもの

- prompt template
- prompt family/version manifest
- 実験計画
- 集計サマリ

### Git 管理しない、または任意にするもの

- 実行ごとの詳細ログ
- 全 run の rendered prompt
- 全 candidate output
- 大量の evaluation 明細

推奨は次の二層構造。

### A. Registry layer

Git 管理対象。人がレビューする設定。

```text
prompting/
  families/
    variable-line/
      family.yaml
      versions/
        v1.md
        v2.md
        v3.md
    query-description/
      family.yaml
      versions/
        v1.md
        v2.md
```

### B. Ledger layer

append-only の run / evaluation / artifact revision 記録。

選択肢:

- `JSONL`
- `SQLite`

推奨は SQLite。

理由:

- 参照クエリがしやすい
- append-only を保ちやすい
- artifact 単位の履歴検索が速い
- rendered prompt や metrics を持たせやすい
- experiment / assignment / exposure を同じ場所で追える

例:

```text
.promptops/
  promptops.db
  exports/
    latest-summary.json
```

## ファイル形式案

### family manifest

```yaml
id: variable-line
name: Variable Documentation Line
stage: variables_info_generation
current_version: v3
artifact_kind: variable_doc_line
description: Build one natural-language line for variables_info.txt.
```

### version prompt

Markdown 本文の前に front matter を持たせる。

```md
---
id: v3
label: distinction-first line
parent_id: v2
status: active
author: hikaru
created_at: 2026-04-03
hypothesis: Longer prompts should keep natural language while making neighboring variables easier to distinguish.
input_schema:
  required:
    - variable_name
    - example_value
    - root
    - structure_paths
output_schema:
  type: single_line_variable_doc
tags:
  - variables_info
  - generation
---

You write one variable documentation line for variables_info.txt.
...
```

### experiment manifest

```yaml
id: exp-variable-line-2026-04
family_id: variable-line
name: Variable line clarity A/B
status: running
assignment_unit: dataset_variable
assignment_strategy: deterministic_hash
sticky: true
target_filter:
  datasets:
    - uniprot
    - chebi
  variable_name_regex: ".*"
arms:
  - id: control
    version_id: variable-line-v3
    weight: 50
  - id: treatment
    version_id: variable-line-v4
    weight: 50
primary_metrics:
  - roundtrip_pass_rate
secondary_metrics:
  - templated_rate
  - detailed_rate
```

## A/B テストの基本フロー

この library では、A/B テストは「今の current prompt を起点に 2 本の候補を派生させ、同じ family の中で比較する」形を標準にする。

### 標準フロー

1. 現在の `current_version` を親にする
2. 親から 2 つの子 version を作る
3. それぞれに狙いを 1 つずつ持たせる
4. experiment manifest を自動生成する
5. assignment unit ごとに control / treatment / treatment_b へ固定割当する
6. outcome を集計して勝者を promote する

### なぜ「今ある prompt から 2 つ作る」のがよいか

- 比較対象の差分が明確になる
- どちらも現在の production knowledge を引き継げる
- parent-child 関係が保たれるので進化履歴を追いやすい
- 勝った案をそのまま次の親にできる

### 推奨する実験単位

- 1 つの family につき 1 回の実験では、変更の論点は 1 つに絞る
- `variable-line` なら「identifier と label の対比を強める」など 1 論点
- `query-description` なら「より user-facing にする」など 1 論点

差分が多すぎる 2 案を比べると、何が効いたか分からなくなる。

## Prompt Branching

今ある prompt から新しい 2 案を作る機能を library に持たせる。

### 期待する操作

- current version を複製して 2 本の branch version を作る
- 各 branch に仮ラベル、仮 hypothesis、親 version を付ける
- experiment manifest を同時に作る
- 必要なら control として親 version も残す

### 生成されるもの

例:

- parent: `variable-line-v3`
- child A: `variable-line-v4a`
- child B: `variable-line-v4b`
- experiment: `exp-variable-line-v4a-v4b`

### モード

#### 1. Three-arm mode

親も含めて 3 腕比較する。

- control: current parent
- treatment_a: child A
- treatment_b: child B

production の現行品質を保険として残したいときに向く。

#### 2. Two-arm mode

親から作った 2 子だけを比較する。

- arm_a: child A
- arm_b: child B

既に parent が十分弱いと分かっていて、次の改善候補同士だけを比較したいときに向く。

この repo の初期運用では `three-arm mode` を標準にするのが安全。

### API 案

```ruby
PromptOps::Experiments.branch_and_start(
  family_id: "variable-line",
  from_version: :current,
  mode: :three_arm,
  children: [
    {
      id: "variable-line-v4a",
      label: "contrast-heavy wording",
      hypothesis: "Make identifier and label roles more explicit."
    },
    {
      id: "variable-line-v4b",
      label: "example-anchored wording",
      hypothesis: "Use example-driven wording to reduce abstract boilerplate."
    }
  ],
  assignment_unit: "dataset_variable",
  target_filter: { datasets: %w[uniprot chebi pubchem] }
)
```

### CLI 案

```bash
promptops experiment branch-and-start \
  --family variable-line \
  --from current \
  --mode three-arm \
  --child-id variable-line-v4a \
  --child-label "contrast-heavy wording" \
  --child-id variable-line-v4b \
  --child-label "example-anchored wording"
```

### agent 支援機能

agent が「今の prompt から 2 案作って試したい」と判断したとき、次の補助機能があるとよい。

- current prompt をベースに 2 つのドラフト prompt を自動複製する
- 親との差分を可視化する
- hypothesis テンプレートを自動で入れる
- experiment manifest を scaffold する
- 対象 dataset/filter をその場で指定できる

### 重要な記録

branching 実験では、各 arm について次を必ず残す。

- parent_version_id
- child_version_id
- version diff summary
- experiment_id
- assignment_unit
- outcome metrics
- promote / retire の判断理由

## A/B テスト対応で必要な原則

1. Assignment は deterministic にする
2. Assignment は sticky にする
3. Exposure と outcome を分けて記録する
4. 実験の対象単位を family ごとに明示する
5. 集計は run 単位ではなく assignment unit 単位でも出せるようにする
6. branch 元の parent version を必ず記録する

### なぜ deterministic assignment が必要か

`uniprot:gene_label` が一度 control に入ったら、同じ experiment が active な間は同じ arm に残すべき。  
これが毎回ランダムだと、改善なのか対象差なのか分からなくなる。

推奨は次のような hash ベース割り当て。

```text
bucket = hash("#{experiment_id}:#{unit_key}") % 100
```

これで `traffic_split` に応じて arm を決める。

### Assignment unit の選び方

- `dataset_variable`: `variables_info.txt` の 1 行説明を比較する時に使う
- `dataset_query`: `sparql.yaml` の description を比較する時に使う
- `dataset`: データセット全体で prompt version を切り替えたい時に使う
- `run`: 探索用途には使えるが、品質比較にはノイズが大きい

この repo では、通常は `dataset_variable` と `dataset_query` を標準にするのがよい。

### 取るべきログ

A/B テストでは少なくとも次を 1 セットで残す。

- exposure: どの対象がどの arm/version で実行されたか
- output: 実際に出た文面
- evaluation: 検証結果と metrics
- apply: 実ファイルに採用されたか

つまり `run があった` だけでは不十分で、`採用された revision かどうか` まで必要。

## Repair Context

再修正時には、現在値だけではなく「直前までに何を試したか」を短く取り出せる必要がある。

### 目的

- 同じ失敗を繰り返さない
- なぜ現在の文面に落ち着いているかを理解する
- 過去の採用案と却下案を区別して参照する
- validation failure の繰り返しパターンを見つける

### デフォルトの遡り件数

既定値は `3` とする。

理由:

- 1 件だけだと直前の局所最適しか見えない
- 5 件以上を毎回 prompt に入れるとノイズが増えやすい
- 多くの修正は直近 2-3 回の履歴で十分に傾向が見える

したがって、repair 系 API のデフォルトは次とする。

- `adopted_limit = 3`
- `rejected_limit = 3`
- `failure_reason_limit = 3`

### RepairContext モデル

持つべき属性:

- `artifact_kind`
- `dataset`
- `logical_key`
- `current_value`
- `recent_adopted_revisions`
- `recent_rejected_candidates`
- `recent_failure_reasons`
- `repeated_mistake_flags`
- `generated_at`

### 返す内容の方針

repair 用のコンテキストでは、生ログ全件ではなく次だけ返す。

- 現在採用されている文面
- 直近 3 件の採用 revision
- 直近 3 件の不採用 candidate
- 直近 3 件の validation failure reason
- 同じ失敗の反復があればその要約

### API 案

```ruby
PromptOps::History.artifact_recent(
  artifact_kind: "variable_doc_line",
  dataset: "uniprot",
  key: "gene_label",
  limit: 3
)

PromptOps::History.failed_attempts(
  artifact_kind: "variable_doc_line",
  dataset: "uniprot",
  key: "gene_label",
  limit: 3
)

PromptOps::History.repair_context(
  artifact_kind: "variable_doc_line",
  dataset: "uniprot",
  key: "gene_label",
  adopted_limit: 3,
  rejected_limit: 3,
  failure_reason_limit: 3
)
```

### Prompt 注入の方針

repair prompt に渡す履歴は短い要約に整形する。

例:

- current: current approved description
- adopted_history: last 3 approved descriptions with version and reason
- rejected_history: last 3 rejected candidates with failure reason
- repeated_mistakes: identifier/label swap happened twice recently

履歴をそのまま全文注入するのではなく、agent が次の修正に必要な差分だけを渡す。

## Ruby ライブラリ API 案

現在のパイプラインが Ruby なので、まず Ruby 実装がよい。

### コア API

```ruby
registry = PromptOps::Registry.load(root: PROJECT_ROOT.join("prompting"))

template = registry.resolve("variable-line", version: :current)

rendered = template.render(
  variable_name: leaf[:name],
  example_value: VariablesInfo.format_example(leaf[:example]),
  root: root,
  structure_paths: structure_text,
  query_variables: query_payload[:query_variables].join(", "),
  sample_rows: sample[:text]
)

run = PromptOps::Ledger.start_run(
  family_id: "variable-line",
  version_id: template.version_id,
  dataset: dataset,
  target_kind: "variable_doc_line",
  target_id: "#{dataset}:#{leaf[:name]}",
  rendered_prompt: rendered,
  input_snapshot: {...},
  model_backend: "codex"
)

output = llm.call(rendered)

PromptOps::Ledger.finish_run(
  run_id: run.id,
  raw_output: output.raw,
  normalized_output: output.text,
  status: "succeeded"
)

PromptOps::Ledger.record_evaluation(
  run_id: run.id,
  kind: "roundtrip",
  status: "passed",
  metrics: { expected: 3, inferred: 3 }
)

assignment = PromptOps::Experiments.assign(
  family_id: "variable-line",
  unit_key: "#{dataset}:#{leaf[:name]}"
)

PromptOps::Ledger.record_artifact_revision(
  artifact_kind: "variable_doc_line",
  dataset: dataset,
  logical_key: leaf[:name],
  location: variables_info_path.to_s,
  before_value: current_line,
  after_value: candidate_line,
  applied_by_run_id: run.id,
  assignment_id: assignment.id,
  apply_reason: "initial_generation"
)
```

### 補助 API

```ruby
PromptOps::Registry.promote_family_version("variable-line", "v4")
PromptOps::Registry.create_child_version("variable-line", from: "v3", id: "v4")
PromptOps::History.artifact("variable_doc_line", dataset: "uniprot", key: "gene_label")
PromptOps::History.family_metrics("variable-line")
PromptOps::History.run(run_id)
PromptOps::Experiments.assignment(experiment_id: "exp-variable-line-2026-04", unit_key: "uniprot:gene_label")
PromptOps::History.repair_context(artifact_kind: "variable_doc_line", dataset: "uniprot", key: "gene_label")
PromptOps::Experiments.branch_and_start(family_id: "variable-line", from_version: :current, mode: :three_arm, children: [...])
```

## CLI 案

```bash
promptops family list
promptops version show variable-line@v3
promptops version diff variable-line@v2 variable-line@v3
promptops run list --family variable-line --dataset uniprot
promptops artifact history --kind variable_doc_line --dataset uniprot --key gene_label
promptops artifact diff --revision rev_123 --revision rev_124
promptops promote variable-line v4
promptops experiment show exp-variable-line-2026-04
promptops assignment show --experiment exp-variable-line-2026-04 --unit-key uniprot:gene_label
promptops experiment report exp-variable-line-2026-04
promptops repair-context --kind variable_doc_line --dataset uniprot --key gene_label
promptops experiment branch-and-start --family variable-line --from current --mode three-arm ...
```

## 現リポジトリへの当てはめ

### いま足りないもの

1. 実行時 prompt が registry から読まれていない
2. `repair-*` 系 prompt family が registry に入っていない
3. run / experiment / assignment / artifact revision の ledger がない
4. `variables_info.txt` の各行更新が prompt version や arm と結びついていない
5. A/B テストの割り当て規則が実行系に入っていない

### 最小移行ステップ

1. `scripts/incremental_variable_docs.rb` の heredoc prompt を family/version 化する
2. `monitoring/prompts` を実行時にも読む directory に昇格させる
3. SQLite ledger を追加する
4. experiment manifest と deterministic assignment を追加する
5. `append_variable_line` / `upsert_variable_line` の直前で artifact revision を記録する
6. dashboard は JSON ではなく library API から prompt 状態を読む

## 最小スコープ v1

まずは全部を一般化しすぎず、次だけ実装すれば価値が出る。

- family/version の読み込み
- template render
- run logging
- experiment / assignment logging
- branch-and-start experiment scaffolding
- artifact revision logging
- artifact history query
- repair context query

この時点で次が見えるようになる。

- `uniprot:gene_label` はいつ更新されたか
- 何の prompt version が使われたか
- control / treatment のどちらだったか
- 変更前後の文面
- そのとき validation は通ったか
- 直近 3 回で何を試してどう失敗したか

## v2 で追加するもの

- 実験管理
- 自動 metric 集計
- prompt promotion workflow
- A/B 実行
- rollback 候補の提示
- family ごとの current version 切替

## v3 で追加するもの

- provider 抽象化
- structured output validator
- cache
- dataset 別 override
- prompt dependency graph

## なぜ汎用ライブラリとして成立するか

この設計は RDF 固有情報を `artifact_kind` と `input_snapshot` に押し込めているので、コア自体は汎用化できる。

RDF 固有なのは主に次だけ。

- `dataset`
- `variables_info.txt`
- `sparql.yaml`
- round-trip validation の評価器

つまりコア library は汎用、RDF 部分は adapter に切り分けられる。

## 他リポジトリでも使えるようにするための一般化方針

この library は最初は `rdf-config-agent` で使うとしても、設計上は最初から repo 非依存にしておくべき。

### コアと adapter を分離する

#### Core に入れるもの

- prompt family / version 管理
- prompt branching
- experiment / assignment 管理
- run logging
- evaluation logging
- artifact revision logging
- repair context 取得
- CLI / API

#### Adapter に逃がすもの

- artifact の物理ファイル形式
- diff の取り方
- validation 方法
- metrics の定義
- prompt に渡す入力コンテキストの構築
- 変更の apply 方法

つまり core は「prompt 運用の仕組み」、adapter は「その repo で何を artifact と呼ぶか」を担当する。

### repo 側が実装する契約

他 repo で使うために、library は次のインターフェースを要求する形がよい。

```ruby
module PromptOps
  module Adapter
    def list_artifacts; end
    def load_artifact(artifact_ref); end
    def diff_artifact(before_value:, after_value:, artifact_ref:); end
    def build_prompt_inputs(family_id:, artifact_ref:, context: {}); end
    def evaluate_output(family_id:, artifact_ref:, output:, context: {}); end
    def apply_output(family_id:, artifact_ref:, output:, context: {}); end
    def summarize_failure(evaluation_result); end
  end
end
```

この形なら、RDF 以外でも adapter だけ差し替えれば使える。

### artifact の抽象化

RDF repo では artifact は次のように見える。

- `variable_doc_line`
- `query_description`

他 repo では例えば次になる。

- `system_prompt`
- `tool_prompt`
- `classifier_instruction`
- `evaluation_rubric`
- `email_template`
- `workflow_step_message`

したがって core では artifact の意味を固定せず、次の最小属性だけを持てばよい。

- `artifact_kind`
- `artifact_ref`
- `logical_key`
- `location`

### metrics も一般化する

core で固定すべきなのは metrics の保存形式だけで、内容は固定しない。

例:

- RDF repo: `roundtrip_pass_rate`, `templated_rate`
- 別 repo: `judge_score`, `conversion_rate`, `error_rate`, `manual_edit_rate`

したがって evaluation は共通で次の形にする。

- `metric_key`
- `metric_value`
- `metric_type`
- `metric_group`

### provider 非依存

LLM provider も固定しない。

- OpenAI
- Claude
- local model
- ルールベース生成器

同じ run schema で扱い、`provider`, `model_name`, `invocation_params` を記録するだけにする。

### repo ごとの設定ファイル

他 repo で導入しやすくするため、repo 側には薄い設定ファイルだけを置く。

例:

```yaml
project: rdf-config-agent
adapter: rdf_config
registry_dir: prompting
ledger_db: .promptops/promptops.db
default_experiment_mode: three_arm
default_repair_history_limit: 3
families:
  - variable-line
  - query-description
```

別 repo では `adapter` と `families` だけ差し替えれば動く構成にする。

### パッケージ構成の方向性

最終的には次のような構成がよい。

```text
promptops/
  lib/prompt_ops/...
  exe/promptops
  adapters/
    rdf_config/
    generic_file/
    json_field/
```

- `rdf_config` adapter: 今の repo 向け
- `generic_file` adapter: Markdown や text file の更新向け
- `json_field` adapter: JSON/YAML の特定 field 更新向け

これがあると、他リポジトリで最初から custom adapter を書かなくても入りやすい。

### 最小の導入条件

他 repo で使うための最低条件はこれだけに絞るべき。

1. prompt family/version を置く directory がある
2. adapter が artifact を読める
3. adapter が output を評価できる
4. ledger を置ける

この 4 つさえ満たせば導入できるようにする。

## モジュール分割案

```text
lib/prompt_ops/
  registry.rb
  template.rb
  renderer.rb
  ledger.rb
  history.rb
  schemas.rb
  cli.rb
  adapters/
    rdf_variable_docs.rb
    rdf_query_description.rb
```

## 実装順

1. Registry 読み込み
2. Template render
3. SQLite ledger
4. Artifact revision API
5. `incremental_variable_docs.rb` の `build_variable_line` を差し替え
6. `build_query_description` / `infer_variables_from_description` / `repair_*` を差し替え
7. dashboard 連携

## 判断

この repo では、単なる prompt versioning より **prompt + output lineage** の枠組みが適切。  
実装の第一歩は、新しい汎用 library を作って既存の `monitoring/prompt-registry.json` をその manifest source にしつつ、`scripts/incremental_variable_docs.rb` の実行点をそこへ寄せること。

その方向なら、GitHub は「変更の保管」、library は「意味のある履歴参照」を担当できる。
