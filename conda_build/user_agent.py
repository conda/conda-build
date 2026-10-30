# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from contextlib import contextmanager
from inspect import signature
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_active = False


def is_conda_build_active() -> bool:
    return _active


@contextmanager
def _conda_build_user_agent() -> Iterator[None]:
    """Identify requests from nested calls and conda's download threads.

    Like conda-build's other process-wide settings, this assumes independent
    API calls do not overlap across threads.
    """
    from conda.base.context import context

    global _active

    previous = _active
    _active = True
    try:
        if not previous:
            context.plugin_manager.get_cached_session_headers.cache_clear()
        yield
    finally:
        _active = previous
        if not previous:
            context.plugin_manager.get_cached_session_headers.cache_clear()


def conda_build_user_agent(func):
    wrapped = _conda_build_user_agent()(func)
    # getfullargspec does not follow __wrapped__, unlike inspect.signature.
    wrapped.__signature__ = signature(func)
    return wrapped
