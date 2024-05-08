# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import logging
from os.path import abspath, expanduser
from typing import TYPE_CHECKING

from conda.base.context import context

from .. import api

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace
    from typing import Sequence

logging.basicConfig(level=logging.INFO)

epilog = """

Tool to convert packages

conda convert converts pure Python packages to other platforms.

Packages are automatically organized in subdirectories according to platform,
e.g.,

osx-64/
  package-1.0-py33.tar.bz2
win-32/
  package-1.0-py33.tar.bz2

Examples:

Convert a package built with conda build to Windows 64-bit, and place the
resulting package in the current directory (supposing a default Anaconda
install on Mac OS X):

    conda convert package-1.0-py33.tar.bz2 -p win-64

"""


def parse_args(args: Sequence[str] | None) -> tuple[ArgumentParser, Namespace]:
    from conda.cli.conda_argparse import ArgumentParser

    parser = ArgumentParser(
        prog="conda convert",
        description="""
Various tools to convert conda packages. Takes a pure Python package build for
one platform and converts it to work on one or more other platforms, or
all.""",
        epilog=epilog,
    )

    # TODO: Factor this into a subcommand, since it's python package specific
    parser.add_argument("files", nargs="+", help="Package files to convert.")
    parser.add_argument(
        "-p",
        "--platform",
        dest="platforms",
        action="append",
        choices=[
            "osx-64",
            "osx-arm64",
            "linux-32",
            "linux-64",
            "linux-ppc64",
            "linux-ppc64le",
            "linux-s390x",
            "linux-armv6l",
            "linux-armv7l",
            "linux-aarch64",
            "win-32",
            "win-64",
            "win-arm64",
            "all",
        ],
        help="Platform to convert the packages to.",
        default=None,
    )
    parser.add_argument(
        "--dependencies",
        "-d",
        nargs="*",
        help="""Additional (besides python) dependencies of the converted
        package.  To specify a version restriction for a dependency, wrap
        the dependency in quotes, like 'package >=2.0'.""",
    )
    parser.add_argument(
        "--show-imports",
        action="store_true",
        default=False,
        help="Show Python imports for compiled parts of the package.",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force convert, even when a package has compiled C extensions.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=".",
        help="""Directory to write the output files. The packages will be
        organized in platform/ subdirectories, e.g.,
        win-32/package-1.0-py27_0.tar.bz2.""",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        default=False,
        action="store_true",
        help="Print verbose output.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only display what would have been done.",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Don't print as much output."
    )

    return parser, parser.parse_args(args)


def execute(args: Sequence[str] | None = None) -> int:
    _, parsed = parse_args(args)
    context.__init__(argparse_args=parsed)

    files = parsed.files
    del parsed.__dict__["files"]

    for f in files:
        f = abspath(expanduser(f))
        api.convert(f, **parsed.__dict__)

    return 0
