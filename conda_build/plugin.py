# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from typing import TYPE_CHECKING

import conda.plugins

if TYPE_CHECKING:
    from typing import Sequence


# lazy-import to avoid nasty import-time side effects when not using conda-build
def build(args: Sequence[str]) -> int:
    from .cli.main_build import execute

    return execute(args)


def convert(args: Sequence[str]) -> int:
    from .cli.main_convert import execute

    return execute(args)


def debug(args: Sequence[str]) -> int:
    from .cli.main_debug import execute

    return execute(args)


def develop(args: Sequence[str]) -> int:
    from .cli.main_develop import execute

    return execute(args)


def inspect(args: Sequence[str]) -> int:
    from .cli.main_inspect import execute

    return execute(args)


def metapackage(args: Sequence[str]) -> int:
    from .cli.main_metapackage import execute

    return execute(args)


def render(args: Sequence[str]) -> int:
    from .cli.main_render import execute

    return execute(args)


def skeleton(args: Sequence[str]) -> int:
    from .cli.main_skeleton import execute

    return execute(args)


@conda.plugins.hookimpl
def conda_subcommands():
    yield conda.plugins.CondaSubcommand(
        name="build",
        summary="Build conda packages from a conda recipe.",
        action=build,
    )
    yield conda.plugins.CondaSubcommand(
        name="convert",
        summary="Convert pure Python packages to other platforms (a.k.a., subdirs).",
        action=convert,
    )
    yield conda.plugins.CondaSubcommand(
        name="debug",
        summary="Debug the build or test phases of conda recipes.",
        action=debug,
    )
    yield conda.plugins.CondaSubcommand(
        name="develop",
        summary=(
            "Install a Python package in 'development mode'. "
            "Similar to `pip install --editable`."
        ),
        action=develop,
    )
    yield conda.plugins.CondaSubcommand(
        name="inspect",
        summary="Tools for inspecting conda packages.",
        action=inspect,
    )
    yield conda.plugins.CondaSubcommand(
        name="metapackage",
        summary="Specialty tool for generating conda metapackage.",
        action=metapackage,
    )
    yield conda.plugins.CondaSubcommand(
        name="render",
        summary="Expand a conda recipe into a platform-specific recipe.",
        action=render,
    )
    yield conda.plugins.CondaSubcommand(
        name="skeleton",
        summary="Generate boilerplate conda recipes.",
        action=skeleton,
    )
