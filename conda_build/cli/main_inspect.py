# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import logging
import sys
from os.path import expanduser
from pprint import pprint
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
        prog="conda inspect",
        description="Tools for inspecting conda packages.",
        epilog="""
Run --help on the subcommands like 'conda inspect linkages --help' to see the
options available.
        """,
    )
    subcommand = parser.add_subparsers(
        dest="subcommand",
    )

    linkages_help = """
Investigates linkages of binary libraries in a package (works in Linux and
OS X). This is an advanced command to aid building packages that link against
C libraries. Aggregates the output of ldd (on Linux) and otool -L (on OS X) by
dependent packages. Useful for finding broken links, or links against system
libraries that ought to be dependent conda packages.  """
    linkages = subcommand.add_parser(
        "linkages",
        # help controls conda inspect -h and description controls conda
        # inspect linkages -h
        help=linkages_help,
        description=linkages_help,
    )
    linkages.add_argument(
        "packages",
        action="store",
        nargs="*",
        help="Conda packages to inspect.",
    )
    linkages.add_argument(
        "--untracked",
        action="store_true",
        help="""Inspect the untracked files in the environment. This is useful when used in
        conjunction with conda build --build-only.""",
    )
    linkages.add_argument(
        "--show-files",
        action="store_true",
        help="Show the files in the package that link to each library",
    )
    linkages.add_argument(
        "--groupby",
        action="store",
        default="package",
        choices=("package", "dependency"),
        help="""Attribute to group by (default: %(default)s). Useful when used
        in conjunction with --all.""",
    )
    linkages.add_argument(
        "--sysroot",
        action="store",
        help="System root in which to look for system libraries.",
        default="",
    )
    linkages.add_argument(
        "--all",
        action="store_true",
        help="Generate a report for all packages in the environment.",
    )
    add_parser_prefix(linkages)

    objects_help = """
Investigate binary object files in a package (only works on OS X). This is an
advanced command to aid building packages that have compiled
libraries. Aggregates the output of otool on all the binary object files in a
package.
"""
    objects = subcommand.add_parser(
        "objects",
        help=objects_help,
        description=objects_help,
    )
    objects.add_argument(
        "packages",
        action="store",
        nargs="*",
        help="Conda packages to inspect.",
    )
    objects.add_argument(
        "--untracked",
        action="store_true",
        help="""Inspect the untracked files in the environment. This is useful when used
        in conjunction with conda build --build-only.""",
    )
    # TODO: Allow groupby to include the package (like for --all)
    objects.add_argument(
        "--groupby",
        action="store",
        default="filename",
        choices=("filename", "filetype", "rpath"),
        help="Attribute to group by (default: %(default)s).",
    )
    objects.add_argument(
        "--all",
        action="store_true",
        help="Generate a report for all packages in the environment.",
    )
    add_parser_prefix(objects)

    channels_help = """
Tools for investigating conda channels.
"""
    channels = subcommand.add_parser(
        "channels",
        help=channels_help,
        description=channels_help,
    )
    channels.add_argument(
        "--verbose",
        action="store_true",
        help="""Show verbose output. Note that error output to stderr will
        always be shown regardless of this flag. """,
    )
    channels.add_argument(
        "--test-installable",
        "-t",
        action="store_true",
        help=(
            "DEPRECATED. This is the default (and only) behavior. "
            "Test every package in the channel to see if it is installable by conda."
        ),
    )
    channels.add_argument(
        "channel",
        nargs="?",
        default="defaults",
        help="The channel to test. The default is %(default)s.",
    )

    prefix_lengths = subcommand.add_parser(
        "prefix-lengths",
        help="""Inspect packages in given path, finding those with binary
            prefixes shorter than specified""",
        description=linkages_help,
    )
    prefix_lengths.add_argument(
        "packages",
        action="store",
        nargs="+",
        help="Conda packages to inspect.",
    )
    prefix_lengths.add_argument(
        "--min-prefix-length",
        "-m",
        help="Minimum length.  Only packages with prefixes below this are shown.",
        default=api.Config().prefix_length,
        type=int,
    )

    hash_inputs = subcommand.add_parser(
        "hash-inputs",
        help="Show data used to compute hash identifier for package",
        description="Show data used to compute hash identifier for package",
    )
    hash_inputs.add_argument(
        "packages",
        action="store",
        nargs="*",
        help="Conda packages to inspect.",
    )

    return parser, parser.parse_args(args)


def execute(args: Sequence[str] | None = None) -> int:
    parser, parsed = parse_args(args)
    context.__init__(argparse_args=parsed)

    if not parsed.subcommand:
        parser.print_help()
        sys.exit(0)
    elif parsed.subcommand == "channels":
        print(api.test_installable(parsed.channel))
    elif parsed.subcommand == "linkages":
        print(
            api.inspect_linkages(
                parsed.packages,
                prefix=context.target_prefix,
                untracked=parsed.untracked,
                all_packages=parsed.all,
                show_files=parsed.show_files,
                groupby=parsed.groupby,
                sysroot=expanduser(parsed.sysroot),
            )
        )
    elif parsed.subcommand == "objects":
        print(
            api.inspect_objects(
                parsed.packages,
                prefix=context.target_prefix,
                groupby=parsed.groupby,
            )
        )
    elif parsed.subcommand == "prefix-lengths":
        if not api.inspect_prefix_length(
            parsed.packages, min_prefix_length=parsed.min_prefix_length
        ):
            sys.exit(1)
    elif parsed.subcommand == "hash-inputs":
        pprint(api.inspect_hash_inputs(parsed.packages))
    else:
        parser.error(f"Unrecognized subcommand: {parsed.subcommand}.")

    return 0
