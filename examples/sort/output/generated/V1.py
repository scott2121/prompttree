def solve(records):
    return sorted(records, key=lambda record: (record["age"], -record["score"], record["name"]))
