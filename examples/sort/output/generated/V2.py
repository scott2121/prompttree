def solve(records):
    items = list(records)
    items.sort(key=lambda record: (record['age'], -record['score'], record['name']))
    return items
