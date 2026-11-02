"""E0-WorldCore.4: app/domain/names.py (normalize_name, fold, name_tokens)."""
import sys

import pytest

from app.domain.names import NAME_PREFIXES, Token, fold, key_tokens, name_tokens, normalize_name


@pytest.mark.parametrize("text, key", [
    ("  Brother   Áldric ", "aldric"),
    ("ALDRIC", "aldric"),
    ("Áldric", "aldric"),
    ("Áldric", "aldric"),           # decomposed accent
    ("The King", "king"),                 # never the last token
    ("King", "king"),
    ("the the", "the"),
    ("The Lady Mira Vale", "mira vale"),  # repeatedly
    ("Sir Lord Captain Aldric", "aldric"),
    ("Mira the Brave", "mira the brave"),  # only leading tokens
    ("Ｍｉｒａ", "mira"),                    # NFKC (full-width)
    ("Straße", "strasse"),                # casefold
    ("Anne", "anne"),                     # "an" is a token, not a prefix of a word
    ("Theodric", "theodric"),
    ("Mira\tVale\n", "mira vale"),
    ("", ""),
    ("   ", ""),
])
def test_normalize_name(text, key):
    assert normalize_name(text) == key


def test_prefixes_are_the_configured_list():
    assert NAME_PREFIXES == ("the", "a", "an", "brother", "sister", "lord", "lady", "sir", "captain", "king",
                             "queen")


@pytest.mark.parametrize("text", ["  Brother   Áldric ", "The King", "the the", "Ｓｉｒ Ǆemal", "İstanbul", "ﬁona",
                                  "Lady  Ⅻ", "A a a", "x̸y"])
def test_normalize_name_is_idempotent(text):
    once = normalize_name(text)
    assert normalize_name(once) == once


def test_fold_is_idempotent_on_every_code_point():
    for cp in range(0, sys.maxunicode + 1, 7):
        ch = chr(cp)
        assert fold(fold(ch)) == fold(ch), hex(cp)


def test_name_tokens_spans_point_into_the_original_text():
    text = "Brother Áldric's horse, Miranda-Vale.  O'Brien_x 42"
    toks = name_tokens(text)
    assert [t.text for t in toks] == ["brother", "aldric", "s", "horse", "miranda", "vale", "o", "brien", "x", "42"]
    assert toks[1] == Token("aldric", 8, 15) and text[toks[1].start:toks[1].end] == "Áldric"
    for t in toks:
        assert fold(text[t.start:t.end]) == t.text


def test_name_tokens_never_split_inside_a_word():
    assert [t.text for t in name_tokens("Miranda")] == ["miranda"]
    assert name_tokens("") == [] and name_tokens(" ,.- ") == []


def test_key_tokens():
    assert key_tokens("Brother Aldric") == ("aldric",)
    assert key_tokens("Jean-Luc of the Vale") == ("jean", "luc", "of", "the", "vale")
    assert key_tokens("The King") == ("king",)
