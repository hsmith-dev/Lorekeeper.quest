import pytest
from app.services.nlp_service import load_nlp_model, extract_tags
from app.db.models.tag import TagType


@pytest.fixture(scope="module", autouse=True)
def load_model():
    load_nlp_model()


def test_extracts_person():
    tags = extract_tags("Aldric the cleric healed the party after the battle at Waterdeep.")
    names = [t.name for t in tags]
    tag_types = [t.tag_type for t in tags]
    assert TagType.character in tag_types


def test_extracts_location():
    tags = extract_tags("The party traveled through the Underdark toward Menzoberranzan.")
    tag_types = [t.tag_type for t in tags]
    assert TagType.location in tag_types


def test_no_duplicates():
    tags = extract_tags("Aldric fought Aldric's shadow self at the temple.")
    character_tags = [t for t in tags if t.tag_type == TagType.character]
    names = [t.name.lower() for t in character_tags]
    assert len(names) == len(set(names))
