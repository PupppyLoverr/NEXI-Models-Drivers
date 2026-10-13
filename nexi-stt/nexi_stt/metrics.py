from __future__ import annotations

import re
import unicodedata
from typing import Any


def words(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", normalized)


def word_error_rate(reference: str, hypothesis: str) -> dict[str, Any]:
    expected, actual = words(reference), words(hypothesis)
    if not expected:
        raise ValueError("WER reference must have at least one word")
    previous = list(range(len(actual) + 1))
    for i, wanted in enumerate(expected, 1):
        current = [i]
        for j, got in enumerate(actual, 1):
            current.append(
                min(current[-1] + 1, previous[j] + 1, previous[j - 1] + int(wanted != got))
            )
        previous = current
    return {
        "word_errors": previous[-1],
        "reference_words": len(expected),
        "wer": previous[-1] / len(expected),
        "normalization": "NFKC, casefold, English letters/digits/apostrophes; strip punctuation",
    }
