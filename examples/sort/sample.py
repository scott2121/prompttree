import argparse
import json
import random
import string
from pathlib import Path
from typing import Dict, List, Set, Tuple, Any

SORT_SPEC = [
    {"field": "age", "order": "asc"},
    {"field": "score", "order": "desc"},
    {"field": "name", "order": "asc"},
]

INSTRUCTION_TEMPLATES = [
    "records を age 昇順、同点なら score 降順、さらに同点なら name 辞書順で並べ替えてください。",
    "次の records を age の昇順、age が同じ場合は score の降順、さらに同じ場合は name の辞書順でソートしてください。",
    "複合キーソートを行ってください。優先順位は age 昇順 → score 降順 → name 辞書順です。",
]

DEPARTMENTS = ["sales", "research", "ops", "design", "finance", "hr"]
CITIES = ["tokyo", "osaka", "nagoya", "fukuoka", "sapporo", "kyoto"]


def make_name(rng: random.Random, used: Set[str]) -> str:
    """各ケース内でユニークな lowercase 名を作る。"""
    vowels = "aeiou"
    consonants = "".join([c for c in string.ascii_lowercase if c not in vowels])

    while True:
        length = rng.randint(4, 8)
        start_with_consonant = rng.choice([True, False])
        chars = []
        for i in range(length):
            use_consonant = (i % 2 == 0 and start_with_consonant) or (i % 2 == 1 and not start_with_consonant)
            pool = consonants if use_consonant else vowels
            chars.append(rng.choice(pool))
        name = "".join(chars)
        if name not in used:
            used.add(name)
            return name


def difficulty_ranges(level: str) -> Tuple[int, int, int, int]:
    """
    tie が発生しやすいように hard は値域を狭くする。
    return: age_min, age_max, score_min, score_max
    """
    if level == "easy":
        return 18, 65, 0, 100
    if level == "medium":
        return 18, 35, 0, 50
    return 20, 25, 0, 10  # hard


def generate_records(rng: random.Random, n: int) -> Tuple[str, List[Dict[str, Any]]]:
    """
    複合キーの tie を作りやすいように、age/score のアンカー値を混ぜる。
    """
    difficulty = rng.choices(
        ["easy", "medium", "hard"],
        weights=[0.15, 0.35, 0.50],
        k=1,
    )[0]

    age_min, age_max, score_min, score_max = difficulty_ranges(difficulty)

    used_names: Set[str] = set()
    records: List[Dict[str, Any]] = []

    # tie を増やすためのアンカー
    anchor_count = max(1, min(6, n // 8))
    anchors: List[Tuple[int, int]] = [
        (rng.randint(age_min, age_max), rng.randint(score_min, score_max))
        for _ in range(anchor_count)
    ]

    for i in range(n):
        if rng.random() < 0.65:
            age, score = rng.choice(anchors)
            # 少し崩して単純すぎる分布を避ける
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
                # 無関係な列も少し入れておくと実データっぽくなる
                "department": rng.choice(DEPARTMENTS),
                "city": rng.choice(CITIES),
                "uid": f"u{i:04d}",
            }
        )

    rng.shuffle(records)
    return difficulty, records


def gold_sort(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """正解ソート。age 昇順、score 降順、name 辞書順。"""
    return sorted(records, key=lambda r: (r["age"], -r["score"], r["name"]))


def make_example(
    example_id: int,
    rng: random.Random,
    min_records: int,
    max_records: int,
) -> Dict[str, Any]:
    n = rng.randint(min_records, max_records)
    difficulty, records = generate_records(rng, n)
    expected_sorted_records = gold_sort(records)

    # 念のため検証
    assert expected_sorted_records == sorted(
        records,
        key=lambda r: (r["age"], -r["score"], r["name"])
    )

    example = {
        "id": f"complex_sort_{example_id:08d}",
        "task": "complex_key_sort",
        "instruction": rng.choice(INSTRUCTION_TEMPLATES),
        "sort_spec": SORT_SPEC,
        "records": records,
        "expected_sorted_records": expected_sorted_records,
        "metadata": {
            "num_records": n,
            "difficulty": difficulty,
        },
    }
    return example


def write_jsonl(
    output_path: Path,
    num_examples: int,
    min_records: int,
    max_records: int,
    seed: int,
) -> None:
    rng = random.Random(seed)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        for i in range(num_examples):
            ex = make_example(
                example_id=i,
                rng=rng,
                min_records=min_records,
                max_records=max_records,
            )
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"wrote: {output_path}")
    print(f"num_examples={num_examples}, min_records={min_records}, max_records={max_records}, seed={seed}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="複合キーソート用の大きめ jsonl を生成する"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="complex_sort_gold.jsonl",
        help="出力 jsonl パス",
    )
    parser.add_argument(
        "--num-examples",
        type=int,
        default=50000,
        help="生成する件数",
    )
    parser.add_argument(
        "--min-records",
        type=int,
        default=20,
        help="1ケースあたりの最小 record 数",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=200,
        help="1ケースあたりの最大 record 数",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="乱数 seed",
    )

    args = parser.parse_args()

    if args.num_examples <= 0:
        raise ValueError("--num-examples must be > 0")
    if args.min_records <= 0:
        raise ValueError("--min-records must be > 0")
    if args.max_records < args.min_records:
        raise ValueError("--max-records must be >= --min-records")

    write_jsonl(
        output_path=Path(args.output),
        num_examples=args.num_examples,
        min_records=args.min_records,
        max_records=args.max_records,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()