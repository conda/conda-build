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
from conda_build.utils import CONDA_TARBALL_EXTENSIONS
# we extend the render parser because we basically need to render the recipe before
#       we can say what env to create.  This is not really true for debugging tests, but meh...
from conda_build.cli.main_render import get_render_parser
from conda_build.cli.main_render import execute as render_execute


logging.basicConfig(level=logging.INFO)


def parse_args(args):
    p = get_render_parser()
    p.description = """

Set up environments and activation scripts to debug your build or test.

"""
    # we do this one separately because we only allow one entry to conda render
    p.add_argument(
        'recipe_or_package_file_path',
        help="Path to recipe directory or package file to use for dependency and source information",
    )
    p.add_argument("-t", "--test", action="store_true",
                   help=("Generate debugging env for test environment, rather than build-time.  Requires a"
                         " package (not a recipe) as input."))
    p.add_argument("-p", "--path",
                   help=("root path in which to place envs, source and activation script.  Defaults to a "
                         "standard conda-build work folder (packagename_timestamp) in your conda-bld folder."))
    p.add_argument("-o", "--output-id",
                   help=("fnmatch pattern that is associated with the output that you want to create an env for.  "
                         "Must match only one file, as we don't support creating envs for more than one output at a time. "
                         "The top-level recipe can be specified by passing 'TOPLEVEL' here"))
    p.add_argument("-a", "--activate-path-only", action="store_true",
                   help="Output only the path to the generated activation script.  Use this for creating envs in scripted "
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
    try:
        if not any(os.path.splitext(_args.recipe_or_package_file_path)[1] in ext for ext in CONDA_TARBALL_EXTENSIONS):
            if _args.test:
                raise ValueError("Error: debugging for test mode is only supported for package files that already exist. "
                                "Please build your package first, then use it to create the debugging environment.")
            thing_to_debug = render_execute(args, print_results=False)
        else:
            thing_to_debug = _args.recipe_or_package_file_path
        api.debug(thing_to_debug, **_args.__dict__)
    except ValueError as e:
        print(str(e))
        sys.exit(1)


def main():
    return execute(sys.argv[1:])
