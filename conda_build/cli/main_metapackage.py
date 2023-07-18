# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import argparse
import logging
import sys

from .. import api
from ..conda_interface import ArgumentParser, add_parser_channels, binstar_upload
from ..deprecations import deprecated

logging.basicConfig(level=logging.INFO)


def parse_args(args):
    p = ArgumentParser(
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

    p.add_argument(
        "--no-anaconda-upload",
        action="store_false",
        help="Do not ask to upload the package to anaconda.org.",
        dest="anaconda_upload",
        default=binstar_upload,
    )
    p.add_argument(
        "--no-binstar-upload",
        action="store_false",
        help=argparse.SUPPRESS,
        dest="anaconda_upload",
        default=binstar_upload,
    )
    p.add_argument("--token", help="Token to pass through to anaconda upload")
    p.add_argument(
        "--user", help="User/organization to upload packages to on anaconda.org"
    )
    p.add_argument(
        "--label",
        action="append",
        dest="labels",
        default=[],
        help="Label argument to pass through to anaconda upload",
    )
    p.add_argument(
        "name",
        help="Name of the created package.",
    )
    p.add_argument(
        "version",
        help="Version of the created package.",
    )
    p.add_argument(
        "--build-number",
        type=int,
        default=0,
        help="Build number for the package (default is 0).",
    )
    p.add_argument(
        "--build-string",
        default=None,
        help="Build string for the package (default is automatically generated).",
    )
    p.add_argument(
        "--dependencies",
        "-d",
        nargs="*",
        default=(),
        help="""The dependencies of the package. To specify a version restriction for a
        dependency, wrap the dependency in quotes, like 'package >=2.0'.""",
    )
    p.add_argument(
        "--home",
        help="The homepage for the metapackage.",
    )
    p.add_argument(
        "--license", help="The license of the metapackage.", dest="license_name"
    )
    p.add_argument(
        "--summary",
        help="""Summary of the package.  Pass this in as a string on the command
        line, like --summary 'A metapackage for X'. It is recommended to use
        single quotes if you are not doing variable substitution to avoid
        interpretation of special characters.""",
    )
    p.add_argument(
        "--entry-points",
        nargs="*",
        default=(),
        help="""Python entry points to create automatically. They should use the same
        syntax as in the meta.yaml of a recipe, e.g., --entry-points
        bsdiff4=bsdiff4.cli:main_bsdiff4 will create an entry point called
        bsdiff4 that calls bsdiff4.cli.main_bsdiff4(). """,
    )

    add_parser_channels(p)
    args = p.parse_args(args)
    return p, args


def execute(args):
    _, args = parse_args(args)
    channel_urls = args.__dict__.get("channel") or args.__dict__.get("channels") or ()
    api.create_metapackage(channel_urls=channel_urls, **args.__dict__)


@deprecated("3.26.0", "4.0.0", addendum="Use `conda metapackage` instead.")
def main():
    return execute(sys.argv[1:])
