# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from conda.base.context import context

from .. import api

try:
    from conda.cli.helpers import add_parser_channels
except ImportError:
    # conda<23.11
    from conda.cli.conda_argparse import add_parser_channels

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace
    from typing import Sequence

logging.basicConfig(level=logging.INFO)


def parse_args(args: Sequence[str] | None) -> tuple[ArgumentParser, Namespace]:
    from conda.cli.conda_argparse import ArgumentParser

    parser = ArgumentParser(
        prog="conda metapackage",
        description="""
Tool for building conda metapackages.  A metapackage is a package with no
files, only metadata.  They are typically used to collect several packages
together into a single package via dependencies.

NOTE: Metapackages can also be created by creating a recipe with the necessary
metadata in the meta.yaml, but a metapackage can be created entirely from the
command line with the conda metapackage command.
""",
    )

    parser.add_argument(
        "--no-anaconda-upload",
        action="store_false",
        help="Do not ask to upload the package to anaconda.org.",
        dest="anaconda_upload",
        default=context.binstar_upload,
    )
    parser.add_argument(
        "--no-binstar-upload",
        action="store_false",
        help=argparse.SUPPRESS,
        dest="anaconda_upload",
        default=context.binstar_upload,
    )
    parser.add_argument("--token", help="Token to pass through to anaconda upload")
    parser.add_argument(
        "--user", help="User/organization to upload packages to on anaconda.org"
    )
    parser.add_argument(
        "--label",
        action="append",
        dest="labels",
        default=[],
        help="Label argument to pass through to anaconda upload",
    )
    parser.add_argument(
        "name",
        help="Name of the created package.",
    )
    parser.add_argument(
        "version",
        help="Version of the created package.",
    )
    parser.add_argument(
        "--build-number",
        type=int,
        default=0,
        help="Build number for the package (default is 0).",
    )
    parser.add_argument(
        "--build-string",
        default=None,
        help="Build string for the package (default is automatically generated).",
    )
    parser.add_argument(
        "--dependencies",
        "-d",
        nargs="*",
        default=(),
        help="""The dependencies of the package. To specify a version restriction for a
        dependency, wrap the dependency in quotes, like 'package >=2.0'.""",
    )
    parser.add_argument(
        "--home",
        help="The homepage for the metapackage.",
    )
    parser.add_argument(
        "--license", help="The license of the metapackage.", dest="license_name"
    )
    parser.add_argument(
        "--summary",
        help="""Summary of the package.  Pass this in as a string on the command
        line, like --summary 'A metapackage for X'. It is recommended to use
        single quotes if you are not doing variable substitution to avoid
        interpretation of special characters.""",
    )
    parser.add_argument(
        "--entry-points",
        nargs="*",
        default=(),
        help="""Python entry points to create automatically. They should use the same
        syntax as in the meta.yaml of a recipe, e.g., --entry-points
        bsdiff4=bsdiff4.cli:main_bsdiff4 will create an entry point called
        bsdiff4 that calls bsdiff4.cli.main_bsdiff4(). """,
    )

    add_parser_channels(parser)

    return parser, parser.parse_args(args)


def execute(args: Sequence[str] | None = None) -> int:
    _, parsed = parse_args(args)
    context.__init__(argparse_args=parsed)

    api.create_metapackage(
        channel_urls=context.channels,
        **parsed.__dict__,
    )

    return 0
