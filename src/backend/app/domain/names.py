"""Name keys and word tokens (E0-WorldCore.4, AD-9, AR-9). Pure: stdlib only.

    normalize_name("  Brother   Áldric ")   -> "aldric"
    normalize_name("The King")              -> "king"   (never the last token)
    name_tokens("Brother Áldric's")         -> [Token("brother", 0, 7), Token("aldric", 8, 14), Token("s", 15, 16)]

`normalize_name` is the one comparison key of an Entity name or alias: NFKC,
casefold, diacritics stripped (NFD, combining marks dropped, recomposed),
whitespace collapsed, and leading `NAME_PREFIXES` tokens dropped repeatedly,
but never the last token. It is idempotent. The stored `alias` keeps its
surface form; only `normalized_alias` takes this key.

`name_tokens` splits text into word tokens (letters and digits; a combining
mark stays in its word) with their spans in the original text, each folded
like `normalize_name` folds (`fold`). The matcher in
app/services/world_matching.py compares these tokens, so "Mira" never
matches inside "Miranda".
"""
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

# Leading articles and honorifics a name key drops (AD-9).
NAME_PREFIXES: tuple[str, ...] = (
    "the", "a", "an", "brother", "sister", "lord", "lady", "sir", "captain", "king", "queen",
)
PREFIX_SET = frozenset(NAME_PREFIXES)

_WORD = re.compile(r"[^\W_]+")


class Token(NamedTuple):
    text: str   # folded
    start: int  # span in the original text
    end: int


def _is_mark(ch: str) -> bool:
    return unicodedata.category(ch).startswith("M")


def fold(text: str) -> str:
    """NFKC, casefold, diacritics stripped (NFD, combining marks dropped, NFC)."""
    s = unicodedata.normalize("NFKC", text).casefold()
    s = "".join(ch for ch in unicodedata.normalize("NFD", s) if not _is_mark(ch))
    # NFKC again (it also recomposes), so a second fold changes nothing.
    return unicodedata.normalize("NFKC", s)


def normalize_name(text: str) -> str:
    """The comparison key of a name or alias ("" for blank text)."""
    tokens = fold(text).split()
    while len(tokens) > 1 and tokens[0] in PREFIX_SET:
        tokens.pop(0)
    return " ".join(tokens)


def name_tokens(text: str) -> list[Token]:
    """The word tokens of `text`, folded, with their spans in `text`."""
    spans: list[list[int]] = []
    for m in _WORD.finditer(text):
        start, end = m.span()
        if spans and all(_is_mark(ch) for ch in text[spans[-1][1]:start]):
            spans[-1][1] = end  # only combining marks between: one word ("Áldric")
        else:
            spans.append([start, end])
        # Trailing combining marks belong to the word.
        while spans[-1][1] < len(text) and _is_mark(text[spans[-1][1]]):
            spans[-1][1] += 1
    out: list[Token] = []
    for start, end in spans:
        folded = fold(text[start:end])
        if folded:
            out.append(Token(folded, start, end))
    return out


def key_tokens(text: str) -> tuple[str, ...]:
    """The folded word tokens of a name's key (`normalize_name`, then `name_tokens`)."""
    return tuple(t.text for t in name_tokens(normalize_name(text)))


__all__ = ["NAME_PREFIXES", "PREFIX_SET", "Token", "fold", "key_tokens", "name_tokens", "normalize_name"]
