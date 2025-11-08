def match_block_expectation(expected: dict, actual: dict) -> bool:
    # Type must match if specified
    if "type" in expected and expected["type"] != actual.get("type"):
        return False
    # Content substring match if specified
    if "text_contains" in expected:
        txt = actual.get("text") or ""
        if expected["text_contains"] not in txt:
            return False
    # Allow future keys (e.g. items for lists) to be checked similarly
    return True

def blocks_satisfy_expectations(expected_blocks: list, actual_blocks: list) -> bool:
    """
    For each expected block spec, find a matching actual block in order.
    We don't require one-to-one or exact counts; it's a subsequence check.
    """
    if not isinstance(expected_blocks, list) or not isinstance(actual_blocks, list):
        return False
    j = 0
    for exp in expected_blocks:
        found = False
        while j < len(actual_blocks):
            if match_block_expectation(exp, actual_blocks[j]):
                found = True
                j += 1
                break
            j += 1
        if not found:
            return False
    return True
