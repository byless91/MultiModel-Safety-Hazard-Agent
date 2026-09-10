"""Lexical matching helpers shared by the evidence judge."""

from __future__ import annotations

import re

CJK_CHAR = re.compile(r"[\u4e00-\u9fff]")
WORD = re.compile(r"[a-zA-Z0-9_]{2,}")


def cjk_bigrams(text: str) -> set[str]:
    chars = [char for char in text if CJK_CHAR.match(char)]
    return {
        "".join(chars[index : index + 2])
        for index in range(len(chars) - 1)
        if chars[index + 1]
    }


def tokens(text: str) -> set[str]:
    result = set(cjk_bigrams(text))
    result.update(WORD.findall(text.lower()))
    return result
