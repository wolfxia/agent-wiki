import re
from collections.abc import Iterable


_LATIN_OR_DIGIT = re.compile(r"[A-Za-z0-9]+")
_CJK = re.compile(r"[㐀-䶿一-鿿]+")


def _iter_segments(text: str) -> Iterable[str]:
    index = 0
    while index < len(text):
        latin_match = _LATIN_OR_DIGIT.match(text, index)
        if latin_match:
            yield latin_match.group(0)
            index = latin_match.end()
            continue

        cjk_match = _CJK.match(text, index)
        if cjk_match:
            yield cjk_match.group(0)
            index = cjk_match.end()
            continue

        index += 1


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for segment in _iter_segments(text):
        if _LATIN_OR_DIGIT.fullmatch(segment):
            tokens.append(segment.lower())
            continue
        if _CJK.fullmatch(segment):
            if len(segment) <= 2:
                tokens.append(segment)
            else:
                tokens.extend(segment[i : i + 2] for i in range(len(segment) - 1))
    return tokens
