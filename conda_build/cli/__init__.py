# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from ..user_agent import conda_build_user_agent

if TYPE_CHECKING:
    from collections.abc import Sequence


@conda_build_user_agent
def execute(command: str, args: Sequence[str] | None = None) -> int:
    module = import_module(f".main_{command}", __name__)
    return module.execute(args)
