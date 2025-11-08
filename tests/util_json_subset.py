def is_subset(expected, actual):
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(k in actual and is_subset(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        # every expected element must be matched by some element of actual
        if not isinstance(actual, list):
            return False
        ai = list(actual)
        for e in expected:
            found = any(is_subset(e, a) for a in ai)
            if not found:
                return False
        return True
    return expected == actual
