def solve(records):
    decorated = [((record["age"], -record["score"], record["name"]), record) for record in records]
    decorated.sort(key=lambda item: item[0])
    return [record for _, record in decorated]
