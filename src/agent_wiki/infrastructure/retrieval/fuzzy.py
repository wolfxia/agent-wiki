from difflib import SequenceMatcher


SIMILARITY_THRESHOLD = 0.85


def fuzzy_match(expected: str, candidate: str) -> bool:
    left = expected.lower().strip()
    right = candidate.lower().strip()
    if not left or not right:
        return False
    if left == right:
        return True
    return SequenceMatcher(None, left, right).ratio() >= SIMILARITY_THRESHOLD
