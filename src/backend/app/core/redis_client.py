"""Deprecated: renamed to app.core.valkey_client (the server is now Valkey).

Kept so code written against the old names still imports. New code uses
get_valkey / init_valkey / close_valkey.
"""

from app.core.valkey_client import close_valkey as close_redis  # noqa: F401
from app.core.valkey_client import get_valkey as get_redis  # noqa: F401
from app.core.valkey_client import init_valkey as init_redis  # noqa: F401
