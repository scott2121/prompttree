from operator import itemgetter


def solve(records):
    result = list(records)
    result.sort(key=itemgetter('name'))
    result.sort(key=itemgetter('score'), reverse=True)
    result.sort(key=itemgetter('age'))
    return result
