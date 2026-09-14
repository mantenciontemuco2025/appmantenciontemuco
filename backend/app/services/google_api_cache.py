"""Thread-local cache for Google API discovery clients.

``googleapiclient`` clients keep an ``httplib2`` transport.  Sharing one
transport between concurrent worker threads is unsafe, so the cache is
thread-local rather than a process-wide singleton.  A thread builds each
client only once and reuses it for subsequent operations.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable


_thread_cache = threading.local()


def build_cached_service(
    *,
    cache_name: str,
    service_name: str,
    version: str,
    credentials,
    credentials_key: Iterable[str],
):
    """Build a Google client once per thread and credential configuration."""
    from googleapiclient.discovery import build

    services = getattr(_thread_cache, "services", None)
    if services is None:
        services = {}
        _thread_cache.services = services

    # Include the build function identity so tests/config reloads cannot reuse
    # a client created with a previously monkeypatched discovery builder.
    credentials_fingerprint = hashlib.sha256(
        "\0".join(credentials_key).encode("utf-8")
    ).hexdigest()
    key = (
        cache_name,
        service_name,
        version,
        id(build),
        credentials_fingerprint,
    )
    cached = services.get(key)
    if cached is None:
        cached = build(service_name, version, credentials=credentials)
        services[key] = cached
    return cached
