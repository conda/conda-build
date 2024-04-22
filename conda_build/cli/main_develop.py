# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from conda.base.context import context

from .. import api

try:
    from conda.cli.helpers import add_parser_prefix
except ImportError:
    # conda<23.11
    from conda.cli.conda_argparse import add_parser_prefix

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace
    from typing import Sequence

logging.basicConfig(level=logging.INFO)


def parse_args(args: Sequence[str] | None) -> tuple[ArgumentParser, Namespace]:
    from conda.cli.conda_argparse import ArgumentParser

    parser = ArgumentParser(
        prog="conda develop",
        description="""

Install a Python package in 'development mode'.

This works by creating a conda.pth file in site-packages.""",
        # TODO: Use setup.py to determine any entry-points to install.
    )

    parser.add_argument(
        "source", metavar="PATH", nargs="+", help="Path to the source directory."
    )
    parser.add_argument(
        "-npf",
        "--no-pth-file",
        action="store_true",
        help=(
            "Relink compiled extension dependencies against "
            "libraries found in current conda env. "
            "Do not add source to conda.pth."
        ),
    )
    parser.add_argument(
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
    parser.add_argument(
        "-c",
        "--clean",
        action="store_true",
        help=(
            "Invoke clean on setup.py: "
            "python setup.py clean "
            "use with build_ext to clean before building."
        ),
    )
    parser.add_argument(
        "-u",
        "--uninstall",
        action="store_true",
        help=(
            "Removes package if installed in 'development mode' "
            "by deleting path from conda.pth file. Ignore other "
            "options - just uninstall and exit"
        ),
    )

    add_parser_prefix(parser)
    parser.set_defaults(func=execute)

    return parser, parser.parse_args(args)


def execute(args: Sequence[str] | None = None) -> int:
    _, parsed = parse_args(args)
    context.__init__(argparse_args=parsed)

    api.develop(
        parsed.source,
        prefix=context.target_prefix,
        no_pth_file=parsed.no_pth_file,
        build_ext=parsed.build_ext,
        clean=parsed.clean,
        uninstall=parsed.uninstall,
    )

    return 0
