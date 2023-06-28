# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import conda.plugins

from .main_build import execute as build
from .main_convert import execute as convert
from .main_debug import execute as debug
from .main_develop import execute as develop
from .main_index import execute as index
from .main_inspect import execute as inspect
from .main_metapackage import execute as metapackage
from .main_render import execute as render
from .main_skeleton import execute as skeleton


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
        summary="Install a Python package in 'development mode'. Similar to `pip install --editable`.",
        action=develop,
    )
    yield conda.plugins.CondaSubcommand(
        name="index",
        summary="Update package index metadata files. Pending deprecation, use https://github.com/conda/conda-index instead.",
        action=index,
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
