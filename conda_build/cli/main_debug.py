# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import logging
import os
import sys

from conda_build import api
from conda_build.utils import CONDA_PACKAGE_EXTENSIONS, on_win
# we extend the render parser because we basically need to render the recipe before
#       we can say what env to create.  This is not really true for debugging tests, but meh...
from conda_build.cli.main_render import get_render_parser
from conda_build.cli.main_render import execute as render_execute


logging.basicConfig(level=logging.INFO)


def parse_args(args):
    p = get_render_parser()
    p.description = """

Set up environments and activation scripts to debug your build or test phase.

"""
    # we do this one separately because we only allow one entry to conda render
    p.add_argument(
        'recipe_or_package_file_path',
        help=("Path to recipe directory or package file to use for dependency and source information. "
              "If you use a recipe, you get the build/host env and source work directory.  If you use "
              "a package file, you get the test environments and the test_tmp folder."),
    )
    p.add_argument("-p", "--path",
                   help=("root path in which to place envs, source and activation script.  Defaults to a "
                         "standard conda-build work folder (packagename_timestamp) in your conda-bld folder."))
    p.add_argument("-o", "--output-id",
                   help=("fnmatch pattern that is associated with the output that you want to create an env for.  "
                         "Must match only one file, as we don't support creating envs for more than one output at a time. "
                         "The top-level recipe can be specified by passing 'TOPLEVEL' here"))
    p.add_argument("-a", "--activate-string-only", action="store_true",
                   help="Output only the string to the used generated activation script.  Use this for creating envs in scripted "
                   "environments.")

    # cut out some args from render that don't make sense here
    #    https://stackoverflow.com/a/32809642/1170370
    p._handle_conflict_resolve(None, [('--output', [_ for _ in p._actions if _.option_strings == ['--output']][0])])
    p._handle_conflict_resolve(None, [('--bootstrap', [_ for _ in p._actions if _.option_strings == ['--bootstrap']][0])])
    p._handle_conflict_resolve(None, [('--old-build-string', [_ for _ in p._actions if
                                                              _.option_strings == ['--old-build-string']][0])])
    args = p.parse_args(args)
    return p, args


def execute(args):
    p, _args = parse_args(args)
    test = True

    try:
        if not any(os.path.splitext(_args.recipe_or_package_file_path)[1] in ext for ext in CONDA_PACKAGE_EXTENSIONS):
            # --output silences console output here
            thing_to_debug = render_execute(args, print_results=False)
            test = False
        else:
            thing_to_debug = _args.recipe_or_package_file_path
        activation_string = api.debug(thing_to_debug, verbose=(not _args.activate_string_only), **_args.__dict__)

        if not _args.activate_string_only:
            print("#" * 80)
            if test:
                print("Test environment created for debugging.  To enter a debugging environment:\n")
            else:
                print("Build and/or host environments created for debugging.  To enter a debugging environment:\n")
        print(activation_string)
        if not _args.activate_string_only:
            if test:
                test_file = "conda_test_runner.sh" if on_win else "conda_test_runner.sh"
                print("To run your tests, you might want to start with running the {} file.".format(test_file))
            else:
                build_file = "conda_build.bat" if on_win else "conda_build.sh"
                print("To run your build, you might want to start with running the {} file.".format(build_file))
            print("#" * 80)

    except ValueError as e:
        print(str(e))
        sys.exit(1)


def main():
    return execute(sys.argv[1:])
