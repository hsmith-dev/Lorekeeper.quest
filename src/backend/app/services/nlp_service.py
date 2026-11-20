"""Tag extraction through the `ml` sidecar's /v1/ner (E0-Platform.6).

The sidecar runs spaCy en_core_web_trf plus a Matcher for ITEM / QUEST
(src/services/ml/ml_service/models.py holds the patterns); this module only
maps its labels to TagType. Failures surface as ModelServiceError /
ModelServiceUnavailable (app/clients/errors.py) for the caller to handle.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.clients.ml import NamedEntity, get_ml_client
from app.db.models.tag import TagType

# The sidecar's /v1/ner limit (ml_service/config.py MAX_NER_CHARS); longer
# text is cut to it rather than rejected with a 422.
MAX_NER_CHARS = 100_000

# spaCy entity labels and the sidecar Matcher's ITEM / QUEST -> TagType.
LABEL_TO_TAG_TYPE: dict[str, TagType] = {
    "PERSON": TagType.character,
    "GPE": TagType.location,
    "LOC": TagType.location,
    "FAC": TagType.location,
    "ORG": TagType.faction,
    "ITEM": TagType.item,
    "QUEST": TagType.quest,
}


@dataclass
class ExtractedTag:
    name: str
    tag_type: TagType


def tags_from_entities(ents: list[NamedEntity]) -> list[ExtractedTag]:
    """Map entities to tags in sidecar order (spaCy ents, then Matcher
    spans), deduped on (lower(name), type); names are title-cased. Labels
    with no TagType (DATE, NORP, ...) are dropped."""
    tags: list[ExtractedTag] = []
    seen: set[tuple[str, TagType]] = set()
    for ent in ents:
        tag_type = LABEL_TO_TAG_TYPE.get(ent.label)
        if tag_type is None:
            continue
        key = (ent.text.lower(), tag_type)
        if key not in seen:
            seen.add(key)
            tags.append(ExtractedTag(name=ent.text.title(), tag_type=tag_type))
    return tags


async def extract_tags(text: str) -> list[ExtractedTag]:
    return tags_from_entities(await get_ml_client().ner(text[:MAX_NER_CHARS]))
