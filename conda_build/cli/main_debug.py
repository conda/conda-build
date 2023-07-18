# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import logging
import sys
from argparse import ArgumentParser

from .. import api
from ..deprecations import deprecated
from ..utils import on_win
from . import validators as valid
from .main_render import get_render_parser

logging.basicConfig(level=logging.INFO)


def get_parser() -> ArgumentParser:
    """Returns a parser object for this command"""
    p = get_render_parser()
    p.prog = "conda debug"
    p.description = """

Set up environments and activation scripts to debug your build or test phase.

"""
    # we do this one separately because we only allow one entry to conda render
    p.add_argument(
        "recipe_or_package_file_path",
        help=(
            "Path to recipe directory or package file to use for dependency and source information. "
            "If you use a recipe, you get the build/host env and source work directory.  If you use "
            "a package file, you get the test environments and the test_tmp folder."
        ),
        type=valid.validate_is_conda_pkg_or_recipe_dir,
    )
    p.add_argument(
        "-p",
        "--path",
        help=(
            "root path in which to place envs, source and activation script.  Defaults to a "
            "standard conda-build work folder (packagename_timestamp) in your conda-bld folder."
        ),
    )
    p.add_argument(
        "-o",
        "--output-id",
        help=(
            "fnmatch pattern that is associated with the output that you want to create an env for.  "
            "Must match only one file, as we don't support creating envs for more than one output at a time. "
            "The top-level recipe can be specified by passing 'TOPLEVEL' here"
        ),
    )
    p.add_argument(
        "-a",
        "--activate-string-only",
        action="store_true",
        help="Output only the string to the used generated activation script.  Use this for creating envs in scripted "
        "environments.",
    )

    # cut out some args from render that don't make sense here
    #    https://stackoverflow.com/a/32809642/1170370
    p._handle_conflict_resolve(
        None,
        [("--output", [_ for _ in p._actions if _.option_strings == ["--output"]][0])],
    )
    p._handle_conflict_resolve(
        None,
        [
            (
                "--bootstrap",
                [_ for _ in p._actions if _.option_strings == ["--bootstrap"]][0],
            )
        ],
    )
    p._handle_conflict_resolve(
        None,
        [
            (
                "--old-build-string",
                [_ for _ in p._actions if _.option_strings == ["--old-build-string"]][
                    0
                ],
            )
        ],
    )
    return p


def execute(args):
    parser = get_parser()
    args = parser.parse_args(args)

    try:
        activation_string = api.debug(
            args.recipe_or_package_file_path,
            verbose=(not args.activate_string_only),
            **args.__dict__,
        )

        if not args.activate_string_only:
            print("#" * 80)
            print(
                "Test environment created for debugging.  To enter a debugging environment:\n"
            )

        print(activation_string)
        if not args.activate_string_only:
            test_file = "conda_test_runner.bat" if on_win else "conda_test_runner.sh"
            print(
                f"To run your tests, you might want to start with running the {test_file} file."
            )
            print("#" * 80)

    except ValueError as e:
        print(
            f"Error: conda-debug encountered the following error:\n{e}", file=sys.stderr
        )
        sys.exit(1)


@deprecated("3.26.0", "4.0.0", addendum="Use `conda debug` instead.")
def main():
    return execute(sys.argv[1:])
