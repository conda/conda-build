# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import argparse
import os
import sys
from collections import deque
from glob import glob
from locale import getpreferredencoding
import warnings

import sys
import shutil
import tarfile
import tempfile
from os import makedirs
from os.path import abspath, isdir, isfile

import conda.config as cc
from conda.compat import PY3
from conda.cli.common import add_parser_channels
from conda.install import delete_trash
from conda.resolve import NoPackagesFound, Unsatisfiable

import conda_build.api as api
import conda_build.build as build
from conda_build.build import bldpkg_path
from conda_build.config import config
from conda_build.index import update_index
from conda_build.main_render import (set_language_env_vars, RecipeCompleter,
                                     render_recipe, get_render_parser, bldpkg_path)
import conda_build.source as source
from conda_build.utils import find_recipe, get_recipe_abspath

on_win = (sys.platform == 'win32')


def main():
    p = get_render_parser()
    p.description = """
Tool for building conda packages. A conda package is a binary tarball
containing system-level libraries, Python modules, executable programs, or
other components. conda keeps track of dependencies between packages and
platform specifics, making it simple to create working environments from
different sets of packages."""
    p.add_argument(
        "--check",
        action="store_true",
        help="Only check (validate) the recipe.",
    )
    p.add_argument(
        "--no-anaconda-upload",
        action="store_false",
        help="Do not ask to upload the package to anaconda.org.",
        dest='binstar_upload',
        default=cc.binstar_upload,
    )
    p.add_argument(
        "--no-binstar-upload",
        action="store_false",
        help=argparse.SUPPRESS,
        dest='binstar_upload',
        default=cc.binstar_upload,
    )
    p.add_argument(
        "--no-include-recipe",
        action="store_false",
        help="Don't include the recipe inside the built package.",
        dest='include_recipe',
        default=True,
    )
    p.add_argument(
        '-s', "--source",
        action="store_true",
        help="Only obtain the source (but don't build).",
    )
    p.add_argument(
        '-t', "--test",
        action="store_true",
        help="Test package (assumes package is already built).  RECIPE_DIR argument can be either "
        "recipe directory, in which case source download may be necessary to resolve package"
        "version, or path to built package .tar.bz2 file, in which case no source is necessary.",
    )
    p.add_argument(
        '--no-test',
        action='store_true',
        dest='notest',
        help="Do not test the package.",
    )
    p.add_argument(
        '-b', '--build-only',
        action="store_true",
        help="""Only run the build, without any post processing or
        testing. Implies --no-test and --no-anaconda-upload.""",
    )
    p.add_argument(
        '-p', '--post',
        action="store_true",
        help="Run the post-build logic. Implies --no-test and --no-anaconda-upload.",
    )
    p.add_argument(
        'recipe',
        action="store",
        metavar='RECIPE_PATH',
        nargs='+',
        choices=RecipeCompleter(),
        help="Path to recipe directory.",
    )
    p.add_argument(
        '--skip-existing',
        action='store_true',
        help="""Skip recipes for which there already exists an existing build
        (locally or in the channels). """
    )
    p.add_argument(
        '--keep-old-work',
        action='store_true',
        help="""Keep any existing, old work directory. Useful if debugging across
        callstacks involving multiple packages/recipes. """
    )
    p.add_argument(
        '--dirty',
        action='store_true',
        help='Do not remove work directory or _build environment, '
        'to speed up debugging.  Does not apply patches or download source.'
    )
    p.add_argument(
        '-q', "--quiet",
        action="store_true",
        help="do not display progress bar",
    )
    p.add_argument(
        '--token',
        action="store",
        help="Token to pass through to anaconda upload"
    )
    p.add_argument(
        '--user',
        action='store',
        help="User/organization to upload packages to on anaconda.org"
    )

    add_parser_channels(p)
    p.set_defaults(func=execute)

    args = p.parse_args()
    args_func(args, p)


def handle_binstar_upload(path, binstar_upload=None, token=None, user=None):
    import subprocess
    from conda_build.external import find_executable

    upload = False
    # this is the default, for no explicit argument.
    # remember that args.binstar_upload takes defaults from condarc
    if args.binstar_upload is None:
        args.yes = False
        args.dry_run = False
    # rc file has uploading explicitly turned off
    elif args.binstar_upload is False:
        print("# Automatic uploading is disabled")
    else:
        upload = True

    no_upload_message = """\
# If you want to upload this package to anaconda.org later, type:
#
# $ anaconda upload %s
#
# To have conda build upload to anaconda.org automatically, use
# $ conda config --set anaconda_upload yes
""" % path
    if not upload:
        print(no_upload_message)
        return

    binstar = find_executable('anaconda')
    if binstar is None:
        print(no_upload_message)
        sys.exit('''
Error: cannot locate anaconda command (required for upload)
# Try:
# $ conda install anaconda-client
''')
    print("Uploading to anaconda.org")
    cmd = [binstar, ]

    if token:
        cmd.extend(['--token', token])
    cmd.append('upload')
    if user:
        cmd.extend(['--user', user])
    cmd.append(path)
    try:
        subprocess.call(cmd)
    except:
        print(no_upload_message)
        raise


def check_external():
    import os
    import conda_build.external as external

    if sys.platform.startswith('linux'):
        patchelf = external.find_executable('patchelf')
        if patchelf is None:
            sys.exit("""\
Error:
    Did not find 'patchelf' in: %s
    'patchelf' is necessary for building conda packages on Linux with
    relocatable ELF libraries.  You can install patchelf using conda install
    patchelf.
""" % (os.pathsep.join(external.dir_paths)))


def build_tree(recipe_list, check=False, build_only=False, post=False, notest=False,
               binstar_upload=True, skip_existing=False, keep_old_work=False,
               include_recipe=True, need_source_download=True, already_built=None,
               token=None, user=None, dirty=False):
    to_build_recursive = []
    recipes = deque(recipe_list)
    if not already_built:
        already_built = set()
    while recipes:
        # This loop recursively builds dependencies if recipes exist
        if build_only:
            post = False
            notest = True
            binstar_upload = False
        elif post:
            post = True
            notest = True
            binstar_upload = False
        else:
            post = None

        try:
            recipe = recipes.popleft()
            ok_to_test = api.build(recipe, post=post,
                                   include_recipe=include_recipe,
                                   keep_old_work=keep_old_work,
                                   need_source_download=need_source_download,
                                   dirty=dirty, skip_existing=skip_existing,
                                   already_built=already_built)
            if not notest and ok_to_test:
                api.test(recipe)
        except (NoPackagesFound, Unsatisfiable) as e:
            error_str = str(e)
            # Typically if a conflict is with one of these
            # packages, the other package needs to be rebuilt
            # (e.g., a conflict with 'python 3.5*' and 'x' means
            # 'x' isn't build for Python 3.5 and needs to be
            # rebuilt).
            skip_names = ['python', 'r']
            # add the failed one back in
            add_recipes = [recipe]
            for line in error_str.splitlines():
                if not line.startswith('  - '):
                    continue
                pkg = line.lstrip('  - ').split(' -> ')[-1]
                pkg = pkg.strip().split(' ')[0]
                if pkg in skip_names:
                    continue
                recipe_glob = glob(pkg + '-[v0-9][0-9.]*')
                if os.path.exists(pkg):
                    recipe_glob.append(pkg)
                if recipe_glob:
                    for recipe_dir in recipe_glob:
                        if pkg in to_build_recursive:
                            sys.exit(str(e))
                        print(error_str)
                        print(("Missing dependency {0}, but found" +
                                " recipe directory, so building " +
                                "{0} first").format(pkg))
                        add_recipes.append(recipe_dir)
                        to_build_recursive.append(pkg)
                else:
                    raise
            recipes.extendleft(reversed(add_recipes))

        # outputs message, or does upload, depending on value of args.binstar_upload
        output_file = api.get_output_file_path(recipe)
        handle_binstar_upload(output_file, binstar_upload=binstar_upload,
                              token=token, user=user)

        already_built.add(output_file)


def output_action(metadata):
    print(bldpkg_path(metadata))


def source_action(metadata):
    source.provide(metadata.path, metadata.get_section('source'))
    print('Source tree in:', source.get_dir())


def test_action(metadata):
    return api.test(metadata.path, move_broken=False)


def execute(args, parser):
    check_external()

    # change globals in build module, see comment there as well
    build.channel_urls = args.channel or ()
    build.override_channels = args.override_channels
    build.verbose = not args.quiet

    if on_win:
        try:
            # needs to happen before any c extensions are imported that might be
            # hard-linked by files in the trash. one of those is markupsafe,
            # used by jinja2. see https://github.com/conda/conda-build/pull/520
            delete_trash(None)
        except:
            # when we can't delete the trash, don't crash on AssertionError,
            # instead inform the user and try again next time.
            # see https://github.com/conda/conda-build/pull/744
            warnings.warn("Cannot delete trash; some c extension has been "
                          "imported that is hard-linked by files in the trash. "
                          "Will try again on next run.")

    set_language_env_vars(args, parser, execute=execute)

    action = None
    if args.output:
        action = output_action
    elif args.test:
        action = test_action
    elif args.source:
        action = source_action
    elif args.check:
        action = check_action

    if action:
        for recipe in args.recipe:
            recipe_dir, need_cleanup = get_recipe_abspath(recipe)

            # recurse looking for meta.yaml that is potentially not in immediate folder
            recipe_dir = find_recipe(recipe_dir)
            if not isdir(recipe_dir):
                sys.exit("Error: no such directory: %s" % recipe_dir)

            # this fully renders any jinja templating, throwing an error if any data is missing
            m, need_source_download = render_recipe(recipe_dir, no_download_source=False,
                                                    verbose=False, dirty=args.dirty)
            action(m)

            if need_cleanup:
                shutil.rmtree(recipe_dir)
    else:
        build_tree(args.recipe, build_only=args.build_only, post=args.post,
                   notest=args.notest, binstar_upload=args.binstar_upload,
                   skip_existing=args.skip_existing, keep_old_work=args.keep_old_work,
                   include_recipe=args.include_recipe, already_built=None,
                   token=args.token, user=args.user, dirty=args.dirty)


def args_func(args, p):
    try:
        args.func(args, p)
    except RuntimeError as e:
        if 'maximum recursion depth exceeded' in str(e):
            print_issue_message(e)
            raise
        sys.exit("Error: %s" % e)
    except Exception as e:
        print_issue_message(e)
        raise  # as if we did not catch it


def print_issue_message(e):
    if e.__class__.__name__ not in ('ScannerError', 'ParserError'):
        message = """\
An unexpected error has occurred, please consider sending the
following traceback to the conda GitHub issue tracker at:

    https://github.com/conda/conda-build/issues

Include the output of the command 'conda info' in your report.

"""
        print(message, file=sys.stderr)

if __name__ == '__main__':
    main()
