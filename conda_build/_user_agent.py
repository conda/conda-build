# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from contextlib import contextmanager
from functools import cache
from inspect import signature
from threading import RLock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_active_calls = 0
_lock = RLock()


def is_conda_build_active() -> bool:
    with _lock:
        return _active_calls > 0


@contextmanager
def _conda_build_user_agent() -> Iterator[None]:
    """Identify conda-build requests, including those made by download threads."""

    global _active_calls

    with _lock:
        if _active_calls == 0:
            _reset_session_headers()
        _active_calls += 1
    try:
        yield
    finally:
        with _lock:
            _active_calls -= 1
            if _active_calls == 0:
                _reset_session_headers()


def _reset_session_headers() -> None:
    from conda.base.context import context

    manager = context.plugin_manager
    # In-flight requests may still populate the old cache after a transition.
    manager.get_cached_session_headers = cache(manager.get_session_headers)


def conda_build_user_agent(func):
    wrapped = _conda_build_user_agent()(func)
    # getfullargspec does not follow __wrapped__, unlike inspect.signature.
    wrapped.__signature__ = signature(func)
    return wrapped
