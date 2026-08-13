"""HTTP helpers for official API calls that must not inherit ambient proxies."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import requests


@contextmanager
def direct_http_session() -> Iterator[requests.Session]:
    """Yield a session that ignores proxy variables inherited from the parent."""
    session = requests.Session()
    session.trust_env = False
    try:
        yield session
    finally:
        session.close()
