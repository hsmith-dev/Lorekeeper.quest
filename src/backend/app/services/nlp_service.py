import spacy
from spacy.language import Language
from spacy.matcher import Matcher
from dataclasses import dataclass
from app.db.models.tag import TagType

_nlp: Language | None = None
_matcher: Matcher | None = None

ITEM_PATTERNS = [
    [{"TEXT": {"REGEX": r"^\+\d$"}}, {"POS": {"IN": ["NOUN", "PROPN"]}}],
    [{"LOWER": {"IN": ["ring", "wand", "staff", "amulet", "sword", "dagger", "bow", "shield", "armor"]}},
     {"LOWER": "of"}, {"POS": {"IN": ["NOUN", "PROPN"]}, "OP": "+"}],
]

QUEST_PATTERNS = [
    [{"LOWER": {"IN": ["defeat", "find", "retrieve", "escort", "destroy", "investigate", "survive"]}},
     {"POS": {"IN": ["DET", "NOUN", "PROPN", "ADJ"]}, "OP": "*"},
     {"POS": {"IN": ["NOUN", "PROPN"]}}],
]


@dataclass
class ExtractedTag:
    name: str
    tag_type: TagType


def load_nlp_model() -> None:
    global _nlp, _matcher
    _nlp = spacy.load("en_core_web_trf")
    _matcher = Matcher(_nlp.vocab)
    _matcher.add("ITEM", ITEM_PATTERNS)
    _matcher.add("QUEST", QUEST_PATTERNS)


def extract_tags(text: str) -> list[ExtractedTag]:
    if _nlp is None:
        raise RuntimeError("NLP model not loaded")

    doc = _nlp(text)
    tags: list[ExtractedTag] = []
    seen: set[tuple[str, TagType]] = set()

    def add_tag(name: str, tag_type: TagType) -> None:
        key = (name.lower(), tag_type)
        if key not in seen:
            seen.add(key)
            tags.append(ExtractedTag(name=name.title(), tag_type=tag_type))

    for ent in doc.ents:
        if ent.label_ == "PERSON":
            add_tag(ent.text, TagType.character)
        elif ent.label_ in ("GPE", "LOC", "FAC"):
            add_tag(ent.text, TagType.location)
        elif ent.label_ == "ORG":
            add_tag(ent.text, TagType.faction)

    if _matcher:
        matches = _matcher(doc)
        for match_id, start, end in matches:
            label = _nlp.vocab.strings[match_id]
            span_text = doc[start:end].text
            if label == "ITEM":
                add_tag(span_text, TagType.item)
            elif label == "QUEST":
                add_tag(span_text, TagType.quest)

    return tags
