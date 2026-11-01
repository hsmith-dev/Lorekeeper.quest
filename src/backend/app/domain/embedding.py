"""The single embedding contract: which model, how many dimensions.

Everything in the backend that stores, produces or checks an embedding
(pgvector columns, embedding_service, the ml sidecar client) imports these
instead of keeping its own copy. The ml sidecar (src/services/ml) cannot
import this package, so it carries the same values in ml_service/config.py;
tests/test_ml_client.py fails if the two drift.

Migrations 7ffedba22a12 / 402ad2866114 hardcode Vector(384) and stay that
way: changing the dimension needs a new migration, not an edit here alone.
"""

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
