def solve(records):
    return sorted(records, key=lambda r: (r['age'], -r['score'], r['name']))
