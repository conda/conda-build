# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import conda.plugins


# lazy-import to avoid nasty import-time side effects when not using conda-build
def build(*args, **kwargs):
    from .cli.main_build import execute

    execute(*args, **kwargs)


def convert(*args, **kwargs):
    from .cli.main_convert import execute

    execute(*args, **kwargs)


def debug(*args, **kwargs):
    from .cli.main_debug import execute

    execute(*args, **kwargs)


def develop(*args, **kwargs):
    from .cli.main_develop import execute

    execute(*args, **kwargs)


def index(*args, **kwargs):
    # deprecated! use conda-index!
    from .cli.main_index import execute

    execute(*args, **kwargs)


def inspect(*args, **kwargs):
    from .cli.main_inspect import execute

    execute(*args, **kwargs)


def metapackage(*args, **kwargs):
    from .cli.main_metapackage import execute

    execute(*args, **kwargs)


def render(*args, **kwargs):
    from .cli.main_render import execute

    execute(*args, **kwargs)


def skeleton(*args, **kwargs):
    from .cli.main_skeleton import execute

    execute(*args, **kwargs)


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
