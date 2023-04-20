# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import logging
import sys

from conda.base.context import context, determine_target_prefix

from conda_build import api
from conda_build.conda_interface import ArgumentParser, add_parser_prefix

logging.basicConfig(level=logging.INFO)


def parse_args(args):
    p = ArgumentParser(
        description="""

Install a Python package in 'development mode'.

This works by creating a conda.pth file in site-packages."""
        # TODO: Use setup.py to determine any entry-points to install.
    )

    p.add_argument(
        "source", metavar="PATH", nargs="+", help="Path to the source directory."
    )
    p.add_argument(
        "-npf",
        "--no-pth-file",
        action="store_true",
        help=(
            "Relink compiled extension dependencies against "
            "libraries found in current conda env. "
            "Do not add source to conda.pth."
        ),
    )
    p.add_argument(
        "-b",
        "--build_ext",
        action="store_true",
        help=(
            "Build extensions inplace, invoking: "
            "python setup.py build_ext --inplace; "
            "add to conda.pth; relink runtime libraries to "
            "environment's lib/."
        ),
    )
    p.add_argument(
        "-c",
        "--clean",
        action="store_true",
        help=(
            "Invoke clean on setup.py: "
            "python setup.py clean "
            "use with build_ext to clean before building."
        ),
    )
    p.add_argument(
        "-u",
        "--uninstall",
        action="store_true",
        help=(
            "Removes package if installed in 'development mode' "
            "by deleting path from conda.pth file. Ignore other "
            "options - just uninstall and exit"
        ),
    )

    add_parser_prefix(p)
    p.set_defaults(func=execute)

    args = p.parse_args(args)
    return p, args


def execute(args):
    _, args = parse_args(args)
    prefix = determine_target_prefix(context, args)
    api.develop(
        args.source,
        prefix=prefix,
        no_pth_file=args.no_pth_file,
        build_ext=args.build_ext,
        clean=args.clean,
        uninstall=args.uninstall,
    )


def main():
    return execute(sys.argv[1:])
