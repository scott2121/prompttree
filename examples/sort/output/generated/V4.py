def solve(records):
    records = list(records)
    records.sort(key=lambda r: r['name'])
    records.sort(key=lambda r: r['score'], reverse=True)
    records.sort(key=lambda r: r['age'])
    return records
