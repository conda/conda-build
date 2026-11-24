# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_active_calls = 0
_lock = Lock()


def is_conda_build_active() -> bool:
    return _active_calls > 0


@contextmanager
def conda_build_user_agent() -> Iterator[None]:
    """Identify requests while any conda-build call is active."""
    from conda.base.context import context

    global _active_calls

    with _lock:
        if not _active_calls:
            context.plugin_manager.get_cached_session_headers.cache_clear()
        _active_calls += 1
    try:
        yield
    finally:
        with _lock:
            _active_calls -= 1
            if not _active_calls:
                context.plugin_manager.get_cached_session_headers.cache_clear()
