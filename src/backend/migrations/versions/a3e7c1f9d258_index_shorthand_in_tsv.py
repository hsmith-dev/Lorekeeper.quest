"""index_shorthand_in_tsv

Revision ID: a3e7c1f9d258
Revises: 8c1d5f3a92e7
Create Date: 2026-08-28 07:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3e7c1f9d258'
down_revision: Union[str, None] = '8c1d5f3a92e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The full-text index previously covered only the generated narrative —
    # which is first-person prose ("we", "our blades") and often omits the
    # plain vocabulary of the GM's own notes ("party", "mill"). Lexical
    # retrieval (retrieval_service.py) was measurably blind to exactly the
    # words users search with. Index shorthand + narrative together, the same
    # text the RAG embeddings already use (journal_service embeds
    # f"{notes} {narrative}").
    op.execute(
        "UPDATE journal_entries SET narrative_tsv = "
        "to_tsvector('english', coalesce(shorthand,'') || ' ' || coalesce(narrative,''))"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE journal_entries SET narrative_tsv = "
        "to_tsvector('english', coalesce(narrative,''))"
    )
