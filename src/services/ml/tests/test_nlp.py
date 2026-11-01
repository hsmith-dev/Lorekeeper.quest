"""Real-model NER cases, moved from src/backend/tests/test_nlp.py.

The sidecar returns raw spaCy labels (PERSON, GPE/LOC/FAC, ORG, plus the
Matcher's ITEM/QUEST); mapping them to TagTypes and de-duplicating by name
stays with the backend caller. Skipped when en_core_web_trf is not installed.
"""

from __future__ import annotations

import importlib.util

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("spacy") is None or importlib.util.find_spec("en_core_web_trf") is None,
    reason="spaCy en_core_web_trf not installed",
)

LOCATION_LABELS = {"GPE", "LOC", "FAC"}


@pytest.fixture(scope="module")
def ner():
    from ml_service.models import SpacyNer

    return SpacyNer("en_core_web_trf")


def _check_offsets(text, ents):
    for e in ents:
        assert text[e.start:e.end] == e.text


def test_extracts_person(ner):
    text = "Aldric the cleric healed the party after the battle at Waterdeep."
    ents = ner.extract(text)
    _check_offsets(text, ents)
    assert "PERSON" in {e.label for e in ents}


def test_extracts_location(ner):
    text = "The party traveled through the Underdark toward Menzoberranzan."
    ents = ner.extract(text)
    _check_offsets(text, ents)
    assert LOCATION_LABELS & {e.label for e in ents}


def test_no_duplicate_spans(ner):
    # Backend original asserted no duplicate character tags after its name
    # de-dup; the sidecar's equivalent guarantee is no span reported twice.
    text = "Aldric fought Aldric's shadow self at the temple."
    ents = ner.extract(text)
    _check_offsets(text, ents)
    spans = [(e.start, e.end, e.label) for e in ents]
    assert len(spans) == len(set(spans))
    assert any(e.label == "PERSON" and e.text.startswith("Aldric") for e in ents)


def test_borin_stonebeard(ner):
    # The story's acceptance narrative.
    text = "Borin Stonebeard carried a ring of shadows back to Karak Dun."
    ents = ner.extract(text)
    _check_offsets(text, ents)
    persons = [e.text for e in ents if e.label == "PERSON"]
    assert any("Borin" in p for p in persons), ents
    labels = [e.label for e in ents]
    # spaCy entities come first, Matcher spans after them.
    matcher_at = [i for i, lab in enumerate(labels) if lab in ("ITEM", "QUEST")]
    spacy_at = [i for i, lab in enumerate(labels) if lab not in ("ITEM", "QUEST")]
    assert not matcher_at or not spacy_at or max(spacy_at) < min(matcher_at)
    assert any(e.label == "ITEM" and e.text == "ring of shadows" for e in ents), ents
    assert any("Karak" in e.text for e in ents if e.label not in ("ITEM", "QUEST")), ents
